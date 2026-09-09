# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Intelligent Circuit Breaker
# ==============================================================================
# Fichier: src/core/intelligent_circuit_breaker.py
# Description: Circuit breaker avec apprentissage, métriques et analyse des
#              patterns d'échec pour une protection adaptative contre
#              les boucles infinies et les cascades d'erreurs.
# ==============================================================================

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Callable, Awaitable, Union
import asyncio
import logging
import json
from enum import Enum
from dataclasses import dataclass, field
import uuid
import statistics

logger = logging.getLogger(__name__)


# ==============================================================================
# ÉNUMÉRATIONS
# ==============================================================================

class CircuitState(str, Enum):
    """
    États possibles du circuit breaker.
    """
    CLOSED = "closed"          # Circuit fermé - les requêtes passent
    OPEN = "open"              # Circuit ouvert - les requêtes sont bloquées
    HALF_OPEN = "half_open"    # Semi-ouvert - test de récupération


class CircuitEvent(str, Enum):
    """
    Événements du circuit breaker.
    """
    OPENED = "opened"
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    RESET = "reset"
    TIMEOUT = "timeout"
    FAILURE = "failure"
    SUCCESS = "success"
    THRESHOLD_REACHED = "threshold_reached"
    RECOVERY_ATTEMPT = "recovery_attempt"
    RECOVERY_FAILED = "recovery_failed"


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class CircuitMetrics:
    """
    Métriques détaillées du circuit breaker.
    """
    total_failures: int = 0
    total_successes: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_openings: int = 0
    total_closings: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    last_state_change: Optional[datetime] = None
    failure_rate: float = 0.0
    success_rate: float = 0.0
    avg_failure_interval: float = 0.0
    failure_history: List[Dict[str, Any]] = field(default_factory=list)
    error_type_counts: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_openings": self.total_openings,
            "total_closings": self.total_closings,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "last_state_change": self.last_state_change.isoformat() if self.last_state_change else None,
            "failure_rate": self.failure_rate,
            "success_rate": self.success_rate,
            "avg_failure_interval": self.avg_failure_interval,
            "error_type_counts": self.error_type_counts,
            "failure_history": self.failure_history[-10:]  # Derniers 10 échecs
        }


@dataclass
class CircuitBreakerConfig:
    """
    Configuration du circuit breaker.
    """
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_attempts: int = 1
    success_threshold: int = 2
    failure_window_seconds: int = 300
    min_samples_for_analysis: int = 10
    error_type_weights: Dict[str, float] = field(default_factory=lambda: {
        "ConnectionError": 1.5,
        "TimeoutError": 1.2,
        "ValidationError": 0.8,
        "CircuitBreakerError": 2.0,
        "RateLimitError": 1.3,
        "LLMError": 1.1,
    })
    enable_learning: bool = True
    enable_metrics: bool = True
    name: str = "default"


# ==============================================================================
# INTELLIGENT CIRCUIT BREAKER
# ==============================================================================

class IntelligentCircuitBreaker:
    """
    Circuit breaker avec apprentissage et métriques avancées.
    
    Features:
    - Pattern d'échec et apprentissage des comportements
    - Métriques détaillées pour l'analyse
    - Backoff adaptatif basé sur les patterns
    - Classification des types d'erreurs
    - Seuils dynamiques ajustables
    - Persistance des métriques
    """
    
    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        listeners: Optional[List[Callable[[CircuitEvent, Dict], Awaitable[None]]]] = None
    ):
        """
        Initialise le circuit breaker intelligent.
        
        Args:
            config: Configuration du circuit breaker
            listeners: Listeners d'événements
        """
        self.config = config or CircuitBreakerConfig()
        self.listeners = listeners or []
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_success_time: Optional[datetime] = None
        self.last_state_change: Optional[datetime] = None
        self.half_open_attempts = 0
        
        # Cache des métriques
        self.metrics = CircuitMetrics()
        
        # Analyse d'erreurs
        self._error_patterns: Dict[str, List[Dict]] = {}
        self._state_history: List[Dict] = []
        self._failure_timestamps: List[datetime] = []
        self._success_timestamps: List[datetime] = []
        
        # Verrou
        self._lock = asyncio.Lock()
        
        # ID unique
        self._circuit_id = str(uuid.uuid4())[:8]
        
        logger.info(f"IntelligentCircuitBreaker initialized: {self.config.name} (id={self._circuit_id})")
    
    # ==========================================================================
    # EXÉCUTION PRINCIPALE
    # ==========================================================================
    
    async def execute(
        self,
        func: Callable,
        *args,
        error_classification: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Exécute une fonction avec la protection du circuit breaker.
        
        Args:
            func: Fonction asynchrone à exécuter
            *args: Arguments positionnels
            error_classification: Classification de l'erreur (optionnel)
            **kwargs: Arguments nommés
            
        Returns:
            Any: Résultat de la fonction
            
        Raises:
            CircuitOpenError: Si le circuit est ouvert
            Exception: Toute exception levée par la fonction
        """
        async with self._lock:
            # Vérifier l'état du circuit
            if self.state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_attempts = 0
                    self.last_state_change = datetime.now(timezone.utc)
                    await self._emit_event(CircuitEvent.HALF_OPEN, {
                        "recovery_attempt": self._get_recovery_attempt_count()
                    })
                    logger.info(f"Circuit {self.config.name} transitioning to HALF_OPEN")
                else:
                    await self._emit_event(CircuitEvent.OPENED, {
                        "reason": "circuit_open_blocked",
                        "failures": self.failure_count,
                        "threshold": self.config.failure_threshold
                    })
                    raise CircuitOpenError(
                        f"Circuit is open for {self.config.name}. "
                        f"Failures: {self.failure_count}/{self.config.failure_threshold}"
                    )
            
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_attempts >= self.config.half_open_max_attempts:
                    await self._emit_event(CircuitEvent.OPENED, {
                        "reason": "half_open_max_attempts_exceeded",
                        "attempts": self.half_open_attempts
                    })
                    raise CircuitOpenError(
                        f"Circuit {self.config.name} is half-open and max attempts exceeded"
                    )
                self.half_open_attempts += 1
        
        # Exécuter la fonction
        try:
            start_time = datetime.now(timezone.utc)
            result = await func(*args, **kwargs)
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            await self._record_success(error_classification=error_classification, duration=duration)
            return result
            
        except Exception as e:
            await self._record_failure(e, error_classification=error_classification)
            raise
    
    # ==========================================================================
    # ENREGISTREMENT DES RÉSULTATS
    # ==========================================================================
    
    async def _record_success(self, error_classification: Optional[str] = None, duration: float = 0.0) -> None:
        """
        Enregistre un succès.
        
        Args:
            error_classification: Classification de l'erreur (optionnel)
            duration: Durée de l'exécution en secondes
        """
        async with self._lock:
            self.success_count += 1
            self.failure_count = 0
            self.last_success_time = datetime.now(timezone.utc)
            self._success_timestamps.append(self.last_success_time)
            
            # Mise à jour des métriques
            self.metrics.total_successes += 1
            self.metrics.consecutive_successes += 1
            self.metrics.consecutive_failures = 0
            self.metrics.last_success_time = self.last_success_time
            
            # Garder un historique limité
            if len(self._success_timestamps) > self.config.min_samples_for_analysis:
                self._success_timestamps = self._success_timestamps[-self.config.min_samples_for_analysis:]
            
            # Si en HALF_OPEN et assez de succès consécutifs, fermer le circuit
            if self.state == CircuitState.HALF_OPEN:
                if self.metrics.consecutive_successes >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.last_state_change = datetime.now(timezone.utc)
                    self.metrics.total_closings += 1
                    await self._emit_event(CircuitEvent.CLOSED, {
                        "consecutive_successes": self.metrics.consecutive_successes,
                        "required": self.config.success_threshold
                    })
                    logger.info(f"Circuit {self.config.name} closed after {self.metrics.consecutive_successes} successes")
            
            self._update_rates()
    
    async def _record_failure(self, error: Exception, error_classification: Optional[str] = None) -> None:
        """
        Enregistre un échec.
        
        Args:
            error: Exception capturée
            error_classification: Classification de l'erreur (optionnel)
        """
        error_type = error_classification or type(error).__name__
        
        async with self._lock:
            self.failure_count += 1
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            self.last_failure_time = datetime.now(timezone.utc)
            self._failure_timestamps.append(self.last_failure_time)
            
            # Mise à jour des métriques
            self.metrics.total_failures += 1
            self.metrics.last_failure_time = self.last_failure_time
            self.metrics.error_type_counts[error_type] = self.metrics.error_type_counts.get(error_type, 0) + 1
            
            # Ajout à l'historique
            self.metrics.failure_history.append({
                "timestamp": self.last_failure_time.isoformat(),
                "error_type": error_type,
                "error_message": str(error)[:200],
                "state": self.state.value
            })
            
            # Garder un historique limité
            if len(self.metrics.failure_history) > 100:
                self.metrics.failure_history = self.metrics.failure_history[-100:]
            if len(self._failure_timestamps) > self.config.min_samples_for_analysis:
                self._failure_timestamps = self._failure_timestamps[-self.config.min_samples_for_analysis:]
            
            # Calcul du taux d'échec
            self._update_rates()
            
            # Détection de pattern (seuil dynamique)
            dynamic_threshold = self._calculate_dynamic_threshold(error_type)
            effective_threshold = min(self.config.failure_threshold, dynamic_threshold)
            
            # Vérifier si le seuil est atteint
            if self.failure_count >= effective_threshold:
                await self._emit_event(CircuitEvent.THRESHOLD_REACHED, {
                    "failures": self.failure_count,
                    "threshold": effective_threshold,
                    "dynamic_threshold": dynamic_threshold,
                    "error_type": error_type
                })
                
                self.state = CircuitState.OPEN
                self.last_state_change = datetime.now(timezone.utc)
                self.metrics.total_openings += 1
                self.half_open_attempts = 0
                
                await self._emit_event(CircuitEvent.OPENED, {
                    "failures": self.failure_count,
                    "threshold": effective_threshold,
                    "error_type": error_type,
                    "reason": "threshold_reached"
                })
                logger.warning(
                    f"Circuit {self.config.name} opened after {self.failure_count} "
                    f"failures (threshold={effective_threshold})"
                )
    
    # ==========================================================================
    # ANALYSE ET APPRENTISSAGE
    # ==========================================================================
    
    def _update_rates(self) -> None:
        """Met à jour les taux de succès et d'échec."""
        total = self.metrics.total_failures + self.metrics.total_successes
        if total > 0:
            self.metrics.failure_rate = self.metrics.total_failures / total
            self.metrics.success_rate = self.metrics.total_successes / total
        
        # Calcul de l'intervalle moyen entre les échecs
        if len(self._failure_timestamps) >= 2:
            intervals = []
            for i in range(1, len(self._failure_timestamps)):
                interval = (self._failure_timestamps[i] - self._failure_timestamps[i-1]).total_seconds()
                intervals.append(interval)
            if intervals:
                self.metrics.avg_failure_interval = statistics.mean(intervals)
    
    def _calculate_dynamic_threshold(self, error_type: str) -> int:
        """
        Calcule un seuil dynamique basé sur le type d'erreur et l'historique.
        
        Args:
            error_type: Type de l'erreur
            
        Returns:
            int: Seuil dynamique
        """
        if not self.config.enable_learning:
            return self.config.failure_threshold
        
        # Ajustement basé sur le type d'erreur
        weight = self.config.error_type_weights.get(error_type, 1.0)
        base_threshold = self.config.failure_threshold
        
        # Ajuster en fonction de l'intervalle moyen entre les échecs
        if self.metrics.avg_failure_interval > 0:
            # Si les échecs sont espacés, on peut être plus tolérant
            interval_factor = min(2.0, self.metrics.avg_failure_interval / 10)
            adjusted_threshold = int(base_threshold * weight / interval_factor)
        else:
            adjusted_threshold = int(base_threshold * weight)
        
        return max(1, min(adjusted_threshold, 20))
    
    def _should_attempt_recovery(self) -> bool:
        """
        Vérifie si une tentative de récupération doit être effectuée.
        
        Returns:
            bool: True si une récupération doit être tentée
        """
        if self.last_failure_time is None:
            return True
        
        elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
        
        # Si le temps écoulé dépasse le timeout de récupération
        if elapsed >= self.config.recovery_timeout:
            # Ajouter un facteur d'apprentissage basé sur la fréquence des échecs
            if len(self._failure_timestamps) >= 3:
                # Si les échecs sont fréquents, augmenter le temps d'attente
                recent_failures = [t for t in self._failure_timestamps 
                                 if (datetime.now(timezone.utc) - t).total_seconds() < 300]
                if len(recent_failures) >= 3:
                    # Bonus de temps basé sur la densité des échecs
                    density_factor = min(2.0, len(recent_failures) / 3)
                    adjusted_timeout = self.config.recovery_timeout * density_factor
                    return elapsed >= adjusted_timeout
            
            return True
        
        return False
    
    def _get_recovery_attempt_count(self) -> int:
        """
        Retourne le nombre de tentatives de récupération.
        
        Returns:
            int: Nombre de tentatives
        """
        return self.metrics.total_openings
    
    # ==========================================================================
    # GESTION DES ÉVÉNEMENTS
    # ==========================================================================
    
    def add_listener(
        self,
        listener: Callable[[CircuitEvent, Dict], Awaitable[None]]
    ) -> None:
        """
        Ajoute un listener d'événements.
        
        Args:
            listener: Fonction de callback
        """
        self.listeners.append(listener)
    
    def remove_listener(
        self,
        listener: Callable[[CircuitEvent, Dict], Awaitable[None]]
    ) -> None:
        """
        Supprime un listener d'événements.
        
        Args:
            listener: Fonction de callback
        """
        if listener in self.listeners:
            self.listeners.remove(listener)
    
    async def _emit_event(self, event_type: CircuitEvent, data: Dict[str, Any]) -> None:
        """
        Émet un événement à tous les listeners.
        
        Args:
            event_type: Type d'événement
            data: Données de l'événement
        """
        event_data = {
            "circuit_id": self._circuit_id,
            "name": self.config.name,
            "state": self.state.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": self.metrics.to_dict(),
            **data
        }
        
        for listener in self.listeners:
            try:
                await listener(event_type, event_data)
            except Exception as e:
                logger.error(f"Listener error: {e}")
    
    # ==========================================================================
    # MÉTHODES DE CONTRÔLE
    # ==========================================================================
    
    async def reset(self) -> None:
        """
        Réinitialise le circuit breaker.
        """
        async with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.half_open_attempts = 0
            self.last_failure_time = None
            self.last_success_time = None
            self.last_state_change = datetime.now(timezone.utc)
            self._failure_timestamps.clear()
            self._success_timestamps.clear()
            
            await self._emit_event(CircuitEvent.RESET, {})
            logger.info(f"Circuit {self.config.name} reset")
    
    async def force_open(self, reason: str = "manual") -> None:
        """
        Force l'ouverture du circuit.
        
        Args:
            reason: Raison de l'ouverture
        """
        async with self._lock:
            self.state = CircuitState.OPEN
            self.last_state_change = datetime.now(timezone.utc)
            self.metrics.total_openings += 1
            await self._emit_event(CircuitEvent.OPENED, {
                "reason": reason,
                "forced": True
            })
            logger.info(f"Circuit {self.config.name} forced open: {reason}")
    
    async def force_close(self, reason: str = "manual") -> None:
        """
        Force la fermeture du circuit.
        
        Args:
            reason: Raison de la fermeture
        """
        async with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.last_state_change = datetime.now(timezone.utc)
            self.metrics.total_closings += 1
            await self._emit_event(CircuitEvent.CLOSED, {
                "reason": reason,
                "forced": True
            })
            logger.info(f"Circuit {self.config.name} forced closed: {reason}")
    
    async def force_half_open(self) -> None:
        """
        Force le passage en semi-ouvert.
        """
        async with self._lock:
            self.state = CircuitState.HALF_OPEN
            self.half_open_attempts = 0
            self.last_state_change = datetime.now(timezone.utc)
            await self._emit_event(CircuitEvent.HALF_OPEN, {
                "forced": True
            })
            logger.info(f"Circuit {self.config.name} forced half-open")
    
    # ==========================================================================
    # STATUT ET MÉTRIQUES
    # ==========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """
        Retourne le statut du circuit breaker.
        
        Returns:
            Dict[str, Any]: Statut détaillé
        """
        return {
            "name": self.config.name,
            "circuit_id": self._circuit_id,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "half_open_attempts": self.half_open_attempts,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "last_state_change": self.last_state_change.isoformat() if self.last_state_change else None,
            "metrics": self.metrics.to_dict(),
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "half_open_max_attempts": self.config.half_open_max_attempts,
                "success_threshold": self.config.success_threshold,
                "enable_learning": self.config.enable_learning,
            }
        }
    
    def get_metrics(self) -> CircuitMetrics:
        """
        Retourne les métriques du circuit breaker.
        
        Returns:
            CircuitMetrics: Métriques
        """
        return self.metrics
    
    async def clear_metrics(self) -> None:
        """
        Efface les métriques sans changer l'état du circuit.
        """
        async with self._lock:
            self.metrics = CircuitMetrics()
            self._failure_timestamps.clear()
            self._success_timestamps.clear()
            logger.info(f"Metrics cleared for circuit {self.config.name}")
    
    # ==========================================================================
    # ANALYSE DES PATTERNS
    # ==========================================================================
    
    def analyze_patterns(self) -> Dict[str, Any]:
        """
        Analyse les patterns d'échec pour détecter des tendances.
        
        Returns:
            Dict[str, Any]: Analyse des patterns
        """
        analysis = {
            "total_failures": self.metrics.total_failures,
            "total_successes": self.metrics.total_successes,
            "failure_rate": self.metrics.failure_rate,
            "error_type_distribution": self.metrics.error_type_counts,
            "consecutive_failures": self.metrics.consecutive_failures,
            "consecutive_successes": self.metrics.consecutive_successes,
        }
        
        # Analyse des tendances temporelles
        if len(self._failure_timestamps) >= 3:
            # Fréquence des échecs
            recent_failures = [t for t in self._failure_timestamps 
                             if (datetime.now(timezone.utc) - t).total_seconds() < 300]
            analysis["recent_failures_5min"] = len(recent_failures)
            
            # Tendance (augmentation ou diminution)
            if len(self._failure_timestamps) >= 5:
                first_half = self._failure_timestamps[:len(self._failure_timestamps)//2]
                second_half = self._failure_timestamps[len(self._failure_timestamps)//2:]
                if len(first_half) > 1 and len(second_half) > 1:
                    first_rate = len(first_half) / ((first_half[-1] - first_half[0]).total_seconds() / 60)
                    second_rate = len(second_half) / ((second_half[-1] - second_half[0]).total_seconds() / 60)
                    analysis["trend"] = "increasing" if second_rate > first_rate * 1.2 else "decreasing" if first_rate > second_rate * 1.2 else "stable"
        
        return analysis


# ==============================================================================
# EXCEPTIONS PERSONNALISÉES
# ==============================================================================

class CircuitOpenError(Exception):
    """
    Exception levée lorsque le circuit est ouvert.
    """
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "CIRCUIT_OPEN_ERROR"


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_circuit_breaker():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Intelligent Circuit Breaker")
        print("=" * 60)
        
        # Création du circuit breaker
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=5,
            success_threshold=2,
            name="test_circuit"
        )
        
        circuit = IntelligentCircuitBreaker(config)
        
        # Ajout d'un listener
        async def on_event(event_type: CircuitEvent, data: Dict):
            print(f"  📢 Event: {event_type.value} - {data.get('reason', '')}")
        
        circuit.add_listener(on_event)
        
        print("\n📋 Test d'exécution avec succès:")
        async def success_func():
            return "Success!"
        
        try:
            result = await circuit.execute(success_func)
            print(f"  ✅ Résultat: {result}")
        except Exception as e:
            print(f"  ❌ Erreur: {e}")
        
        print("\n📋 Test d'exécution avec échecs répétés:")
        failure_count = 0
        
        async def fail_func():
            nonlocal failure_count
            failure_count += 1
            if failure_count <= 5:
                raise ValueError(f"Erreur simulée #{failure_count}")
            return "Success after failures"
        
        for i in range(6):
            try:
                result = await circuit.execute(fail_func)
                print(f"  ✅ Tentative {i+1}: {result}")
            except CircuitOpenError as e:
                print(f"  🔒 Tentative {i+1}: Circuit ouvert - {e}")
            except Exception as e:
                print(f"  ❌ Tentative {i+1}: {e}")
        
        print("\n📋 Statut final:")
        status = circuit.get_status()
        for key, value in status.items():
            if key == "metrics":
                print(f"  {key}: {json.dumps(value, indent=2, default=str)}")
            else:
                print(f"  {key}: {value}")
        
        print("\n📋 Analyse des patterns:")
        analysis = circuit.analyze_patterns()
        for key, value in analysis.items():
            print(f"  {key}: {value}")
        
        print("\n✅ Tests terminés.")
    
    asyncio.run(test_circuit_breaker())