# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Adaptive Retry
# ==============================================================================
# Fichier: src/core/adaptive_retry.py
# Description: Système de retry adaptatif avec jitter, backoff exponentiel,
#              annulation propre et métriques d'utilisation. Tolérance
#              aux pannes transitoires avec apprentissage des patterns.
# ==============================================================================

import asyncio
import random
import logging
import math
from typing import Callable, Any, Optional, List, Dict, Union, TypeVar, Tuple
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
import statistics
import time

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ==============================================================================
# ÉNUMÉRATIONS
# ==============================================================================

class RetryStrategy(str, Enum):
    """
    Stratégies de retry.
    """
    EXPONENTIAL = "exponential"          # Backoff exponentiel (2^n)
    LINEAR = "linear"                    # Backoff linéaire
    FIBONACCI = "fibonacci"              # Backoff de Fibonacci
    CONSTANT = "constant"                # Délai constant
    ADAPTIVE = "adaptive"                # Adaptatif basé sur l'historique


class RetryEvent(str, Enum):
    """
    Événements du système de retry.
    """
    ATTEMPT_START = "attempt_start"
    ATTEMPT_SUCCESS = "attempt_success"
    ATTEMPT_FAILURE = "attempt_failure"
    RETRY_SCHEDULED = "retry_scheduled"
    MAX_RETRIES_REACHED = "max_retries_reached"
    CANCELLED = "cancelled"
    RECOVERY = "recovery"


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class RetryAttempt:
    """
    Information sur une tentative de retry.
    """
    attempt_number: int
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    error: Optional[Exception] = None
    delay_before: float = 0.0
    success: bool = False
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit la tentative en dictionnaire."""
        return {
            "attempt_number": self.attempt_number,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "error": str(self.error) if self.error else None,
            "error_type": type(self.error).__name__ if self.error else None,
            "delay_before": self.delay_before,
            "success": self.success,
            "duration_ms": self.duration_ms
        }


@dataclass
class RetryMetrics:
    """
    Métriques du système de retry.
    """
    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    total_retries: int = 0
    total_duration_ms: float = 0.0
    average_duration_ms: float = 0.0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    average_delay: float = 0.0
    by_error_type: Dict[str, int] = field(default_factory=dict)
    by_strategy: Dict[str, int] = field(default_factory=dict)
    attempts_history: List[RetryAttempt] = field(default_factory=list)
    last_attempt_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "total_attempts": self.total_attempts,
            "successful_attempts": self.successful_attempts,
            "failed_attempts": self.failed_attempts,
            "total_retries": self.total_retries,
            "total_duration_ms": self.total_duration_ms,
            "average_duration_ms": self.average_duration_ms,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "average_delay": self.average_delay,
            "by_error_type": self.by_error_type,
            "by_strategy": self.by_strategy,
            "last_attempt_time": self.last_attempt_time.isoformat() if self.last_attempt_time else None,
        }


# ==============================================================================
# ADAPTIVE RETRY
# ==============================================================================

class AdaptiveRetry:
    """
    Système de retry adaptatif avec jitter et backoff exponentiel.
    
    Features:
    - Multiples stratégies de backoff (exponentiel, linéaire, Fibonacci, constant, adaptatif)
    - Jitter pour éviter les tempêtes de retry
    - Annulation propre avec granularité fine
    - Métriques détaillées d'utilisation
    - Apprentissage des patterns d'échec
    - Support des callbacks
    """
    
    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        max_retries: int = 3,
        strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
        jitter: bool = True,
        jitter_factor: float = 0.5,
        retryable_exceptions: tuple = (Exception,),
        enable_metrics: bool = True,
        listeners: Optional[List[Callable[[RetryEvent, Dict], None]]] = None,
        adaptive_window: int = 10,
    ):
        """
        Initialise le système de retry adaptatif.
        
        Args:
            base_delay: Délai de base en secondes
            max_delay: Délai maximum en secondes
            max_retries: Nombre maximum de tentatives
            strategy: Stratégie de backoff
            jitter: Activer le jitter
            jitter_factor: Facteur de jitter (0-1)
            retryable_exceptions: Exceptions réessayables
            enable_metrics: Activer les métriques
            listeners: Listeners d'événements
            adaptive_window: Fenêtre pour la stratégie adaptative
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.strategy = strategy
        self.jitter = jitter
        self.jitter_factor = jitter_factor
        self.retryable_exceptions = retryable_exceptions
        self.enable_metrics = enable_metrics
        self.listeners = listeners or []
        self.adaptive_window = adaptive_window
        
        self._cancelled = False
        self._metrics = RetryMetrics()
        self._attempt_history: List[RetryAttempt] = []
        self._failure_history: List[Dict[str, Any]] = []
        self._success_history: List[Dict[str, Any]] = []
        self._current_attempt = 0
        self._lock = asyncio.Lock()
        
        # ID unique
        self._retry_id = str(int(time.time() * 1000))[-8:]
        
        logger.info(f"AdaptiveRetry initialized: {self._retry_id} (strategy={strategy.value}, max_retries={max_retries})")
    
    # ==========================================================================
    # MÉTHODE PRINCIPALE
    # ==========================================================================
    
    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[T]],
        *args,
        max_retries: Optional[int] = None,
        retryable_exceptions: Optional[tuple] = None,
        **kwargs
    ) -> T:
        """
        Exécute une fonction avec retry adaptatif.
        
        Args:
            func: Fonction asynchrone à exécuter
            *args: Arguments positionnels
            max_retries: Nombre maximum de tentatives (écrase la valeur par défaut)
            retryable_exceptions: Exceptions réessayables (écrase la valeur par défaut)
            **kwargs: Arguments nommés
            
        Returns:
            T: Résultat de la fonction
            
        Raises:
            Exception: Dernière exception rencontrée si toutes les tentatives échouent
            RetryCancelledError: Si le retry est annulé
        """
        self._cancelled = False
        retries = max_retries if max_retries is not None else self.max_retries
        exceptions = retryable_exceptions if retryable_exceptions is not None else self.retryable_exceptions
        
        last_exception = None
        attempt = 0
        
        while attempt <= retries:
            # Vérifier l'annulation
            if self._cancelled:
                await self._emit_event(RetryEvent.CANCELLED, {
                    "attempt": attempt,
                    "total_retries": retries,
                    "reason": "cancelled"
                })
                raise RetryCancelledError("Retry cancelled")
            
            try:
                # Exécution de la fonction
                start_time = time.time()
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                await self._record_success(attempt, duration_ms)
                return result
                
            except exceptions as e:
                last_exception = e
                attempt += 1
                
                await self._record_failure(attempt, e)
                
                # Vérifier si c'est la dernière tentative
                if attempt > retries:
                    await self._emit_event(RetryEvent.MAX_RETRIES_REACHED, {
                        "attempt": attempt,
                        "max_retries": retries,
                        "error": str(e)
                    })
                    break
                
                # Calculer le délai
                delay = self._calculate_delay(attempt)
                
                await self._emit_event(RetryEvent.RETRY_SCHEDULED, {
                    "attempt": attempt,
                    "max_retries": retries,
                    "delay": delay,
                    "error": str(e)
                })
                
                # Attendre avec vérification d'annulation
                await self._sleep_with_cancel_check(delay)
                
            except Exception as e:
                # Exception non réessayable
                await self._record_failure(attempt, e)
                raise
        
        # Toutes les tentatives ont échoué
        raise last_exception or RetryError(f"All {retries} retries failed")
    
    # ==========================================================================
    # MÉTHODES DE CONTRÔLE
    # ==========================================================================
    
    def cancel(self) -> None:
        """
        Annule le retry en cours.
        """
        self._cancelled = True
        logger.info(f"Retry {self._retry_id} cancelled")
    
    def reset(self) -> None:
        """
        Réinitialise l'état du retry.
        """
        self._cancelled = False
        self._current_attempt = 0
        self._attempt_history.clear()
        logger.info(f"Retry {self._retry_id} reset")
    
    async def reset_metrics(self) -> None:
        """
        Réinitialise les métriques.
        """
        async with self._lock:
            self._metrics = RetryMetrics()
            self._failure_history.clear()
            self._success_history.clear()
            logger.info(f"Metrics reset for retry {self._retry_id}")
    
    # ==========================================================================
    # CALCUL DU DÉLAI
    # ==========================================================================
    
    def _calculate_delay(self, attempt: int) -> float:
        """
        Calcule le délai pour la tentative donnée.
        
        Args:
            attempt: Numéro de la tentative (1-indexé)
            
        Returns:
            float: Délai en secondes
        """
        # Calcul du délai de base selon la stratégie
        if self.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.base_delay * (2 ** (attempt - 1))
        elif self.strategy == RetryStrategy.LINEAR:
            delay = self.base_delay * attempt
        elif self.strategy == RetryStrategy.FIBONACCI:
            delay = self.base_delay * self._fibonacci(attempt)
        elif self.strategy == RetryStrategy.CONSTANT:
            delay = self.base_delay
        elif self.strategy == RetryStrategy.ADAPTIVE:
            delay = self._calculate_adaptive_delay(attempt)
        else:
            delay = self.base_delay * (2 ** (attempt - 1))
        
        # Appliquer le jitter
        if self.jitter and self.jitter_factor > 0:
            jitter_amount = delay * self.jitter_factor * random.random()
            delay = delay + jitter_amount - (jitter_amount / 2)  # Jitter symétrique
        
        # Borner le délai
        return min(max(delay, self.base_delay * 0.5), self.max_delay)
    
    def _calculate_adaptive_delay(self, attempt: int) -> float:
        """
        Calcule un délai adaptatif basé sur l'historique.
        
        Args:
            attempt: Numéro de la tentative
            
        Returns:
            float: Délai adaptatif
        """
        if not self._failure_history:
            return self.base_delay * (2 ** (attempt - 1))
        
        # Analyser les succès/échecs récents
        recent_failures = self._failure_history[-self.adaptive_window:]
        recent_successes = self._success_history[-self.adaptive_window:]
        
        failure_rate = len(recent_failures) / (len(recent_failures) + len(recent_successes)) if recent_failures or recent_successes else 0
        
        # Ajuster le délai en fonction du taux d'échec
        if failure_rate > 0.5:
            # Fort taux d'échec -> backoff plus agressif
            multiplier = 1.5 * (1 + failure_rate)
        elif failure_rate > 0.3:
            multiplier = 1.0
        else:
            # Faible taux d'échec -> backoff plus conservateur
            multiplier = 0.7
        
        return min(self.base_delay * (2 ** (attempt - 1)) * multiplier, self.max_delay)
    
    def _fibonacci(self, n: int) -> int:
        """
        Calcule le nombre de Fibonacci pour n.
        
        Args:
            n: Index
            
        Returns:
            int: Nombre de Fibonacci
        """
        if n <= 0:
            return 0
        elif n == 1:
            return 1
        else:
            a, b = 0, 1
            for _ in range(2, n + 1):
                a, b = b, a + b
            return b
    
    # ==========================================================================
    # ATTENTE AVEC ANNULATION
    # ==========================================================================
    
    async def _sleep_with_cancel_check(
        self,
        duration: float,
        interval: float = 0.5
    ) -> None:
        """
        Attend avec vérification périodique de l'annulation.
        
        Args:
            duration: Durée totale d'attente en secondes
            interval: Intervalle de vérification en secondes
            
        Raises:
            RetryCancelledError: Si le retry est annulé pendant l'attente
        """
        elapsed = 0.0
        while elapsed < duration:
            if self._cancelled:
                raise RetryCancelledError("Retry cancelled during sleep")
            
            remaining = min(interval, duration - elapsed)
            await asyncio.sleep(remaining)
            elapsed += remaining
    
    # ==========================================================================
    # ENREGISTREMENT DES RÉSULTATS
    # ==========================================================================
    
    async def _record_success(self, attempt: int, duration_ms: float) -> None:
        """
        Enregistre un succès.
        
        Args:
            attempt: Numéro de la tentative
            duration_ms: Durée en millisecondes
        """
        async with self._lock:
            self._metrics.total_attempts += 1
            self._metrics.successful_attempts += 1
            self._metrics.total_duration_ms += duration_ms
            self._metrics.average_duration_ms = self._metrics.total_duration_ms / self._metrics.total_attempts
            self._metrics.success_rate = self._metrics.successful_attempts / self._metrics.total_attempts
            self._metrics.failure_rate = 1 - self._metrics.success_rate
            self._metrics.last_attempt_time = datetime.now(timezone.utc)
            
            self._success_history.append({
                "attempt": attempt,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            await self._emit_event(RetryEvent.ATTEMPT_SUCCESS, {
                "attempt": attempt,
                "duration_ms": duration_ms,
                "total_attempts": self._metrics.total_attempts
            })
    
    async def _record_failure(self, attempt: int, error: Exception) -> None:
        """
        Enregistre un échec.
        
        Args:
            attempt: Numéro de la tentative
            error: Exception rencontrée
        """
        error_type = type(error).__name__
        
        async with self._lock:
            self._metrics.total_attempts += 1
            self._metrics.failed_attempts += 1
            self._metrics.total_retries += 1
            self._metrics.total_duration_ms += 0  # Durée inconnue pour les échecs
            self._metrics.failure_rate = self._metrics.failed_attempts / self._metrics.total_attempts
            self._metrics.success_rate = 1 - self._metrics.failure_rate
            self._metrics.by_error_type[error_type] = self._metrics.by_error_type.get(error_type, 0) + 1
            self._metrics.by_strategy[self.strategy.value] = self._metrics.by_strategy.get(self.strategy.value, 0) + 1
            self._metrics.last_attempt_time = datetime.now(timezone.utc)
            
            self._failure_history.append({
                "attempt": attempt,
                "error_type": error_type,
                "error_message": str(error),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            await self._emit_event(RetryEvent.ATTEMPT_FAILURE, {
                "attempt": attempt,
                "error": str(error),
                "error_type": error_type,
                "total_retries": self._metrics.total_retries
            })
    
    # ==========================================================================
    # MÉTRIQUES ET STATISTIQUES
    # ==========================================================================
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Retourne les métriques du système de retry.
        
        Returns:
            Dict[str, Any]: Métriques
        """
        return {
            "retry_id": self._retry_id,
            "strategy": self.strategy.value,
            "max_retries": self.max_retries,
            "base_delay": self.base_delay,
            "max_delay": self.max_delay,
            "jitter": self.jitter,
            "jitter_factor": self.jitter_factor,
            "metrics": self._metrics.to_dict(),
            "history_size": len(self._attempt_history),
            "failure_history_size": len(self._failure_history),
            "success_history_size": len(self._success_history),
        }
    
    def get_success_rate(self) -> float:
        """
        Retourne le taux de succès.
        
        Returns:
            float: Taux de succès (0-1)
        """
        total = self._metrics.successful_attempts + self._metrics.failed_attempts
        return self._metrics.successful_attempts / total if total > 0 else 0
    
    def get_failure_rate(self) -> float:
        """
        Retourne le taux d'échec.
        
        Returns:
            float: Taux d'échec (0-1)
        """
        total = self._metrics.successful_attempts + self._metrics.failed_attempts
        return self._metrics.failed_attempts / total if total > 0 else 0
    
    # ==========================================================================
    # ÉVÉNEMENTS
    # ==========================================================================
    
    def add_listener(self, listener: Callable[[RetryEvent, Dict], None]) -> None:
        """
        Ajoute un listener d'événements.
        
        Args:
            listener: Fonction de callback
        """
        self.listeners.append(listener)
    
    def remove_listener(self, listener: Callable[[RetryEvent, Dict], None]) -> None:
        """
        Supprime un listener d'événements.
        
        Args:
            listener: Fonction de callback
        """
        if listener in self.listeners:
            self.listeners.remove(listener)
    
    async def _emit_event(self, event_type: RetryEvent, data: Dict[str, Any]) -> None:
        """
        Émet un événement à tous les listeners.
        
        Args:
            event_type: Type d'événement
            data: Données de l'événement
        """
        event_data = {
            "retry_id": self._retry_id,
            "strategy": self.strategy.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data
        }
        
        for listener in self.listeners:
            try:
                listener(event_type, event_data)
            except Exception as e:
                logger.error(f"Listener error: {e}")


# ==============================================================================
# EXCEPTIONS PERSONNALISÉES
# ==============================================================================

class RetryError(Exception):
    """
    Exception levée lorsque toutes les tentatives de retry échouent.
    """
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "RETRY_ERROR"


class RetryCancelledError(Exception):
    """
    Exception levée lorsque le retry est annulé.
    """
    def __init__(self, message: str = "Retry cancelled"):
        super().__init__(message)
        self.code = "RETRY_CANCELLED"


# ==============================================================================
# FONCTION DE CONVENANCE - RETRY DECORATOR
# ==============================================================================

def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    jitter: bool = True,
    jitter_factor: float = 0.5,
    retryable_exceptions: tuple = (Exception,)
):
    """
    Décorateur pour ajouter un retry adaptatif à une fonction asynchrone.
    
    Args:
        max_retries: Nombre maximum de tentatives
        base_delay: Délai de base en secondes
        max_delay: Délai maximum en secondes
        strategy: Stratégie de backoff
        jitter: Activer le jitter
        jitter_factor: Facteur de jitter
        retryable_exceptions: Exceptions réessayables
        
    Returns:
        Callable: Décorateur configuré
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args, **kwargs) -> T:
            retry = AdaptiveRetry(
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                strategy=strategy,
                jitter=jitter,
                jitter_factor=jitter_factor,
                retryable_exceptions=retryable_exceptions
            )
            return await retry.execute_with_retry(func, *args, **kwargs)
        return wrapper
    return decorator


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_retry():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Adaptive Retry")
        print("=" * 60)
        
        # Test du retry avec succès immédiat
        print("\n📋 Test de base avec succès immédiat:")
        retry = AdaptiveRetry(max_retries=3)
        
        async def success_func():
            return "Success!"
        
        result = await retry.execute_with_retry(success_func)
        print(f"  Résultat: {result}")
        
        # Test du retry avec échecs puis succès
        print("\n📋 Test avec échecs puis succès:")
        retry = AdaptiveRetry(max_retries=5, base_delay=0.1)
        attempts = 0
        
        async def eventually_success():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError(f"Erreur simulée #{attempts}")
            return "Réussi après 2 échecs"
        
        result = await retry.execute_with_retry(eventually_success)
        print(f"  Tentatives: {attempts}")
        print(f"  Résultat: {result}")
        
        # Test des différentes stratégies
        print("\n📋 Test des stratégies de backoff:")
        strategies = [
            RetryStrategy.EXPONENTIAL,
            RetryStrategy.LINEAR,
            RetryStrategy.FIBONACCI,
            RetryStrategy.CONSTANT,
        ]
        
        for strategy in strategies:
            retry = AdaptiveRetry(
                max_retries=5,
                base_delay=0.5,
                strategy=strategy,
                jitter=False
            )
            
            print(f"\n  Stratégie {strategy.value}:")
            for attempt in range(1, 6):
                delay = retry._calculate_delay(attempt)
                print(f"    Tentative {attempt}: {delay:.3f}s")
        
        # Test de l'annulation
        print("\n📋 Test de l'annulation:")
        retry = AdaptiveRetry(max_retries=5, base_delay=2.0)
        
        async def slow_func():
            await asyncio.sleep(1)
            raise ValueError("Erreur")
        
        # Annuler après un délai
        async def cancel_after():
            await asyncio.sleep(0.5)
            retry.cancel()
        
        try:
            await asyncio.gather(
                retry.execute_with_retry(slow_func),
                cancel_after()
            )
        except RetryCancelledError as e:
            print(f"  ✅ Annulation capturée: {e}")
        
        # Métriques
        print("\n📋 Métriques:")
        metrics = retry.get_metrics()
        for key, value in metrics.items():
            if key == "metrics":
                print(f"  {key}:")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {key}: {value}")
        
        print("\n✅ Tests terminés.")
    
    asyncio.run(test_retry())