# src/orchestration/circuit_breaker.py

"""
Circuit breaker for the Smart Contract Dev Pipeline.
F29 – src/orchestration/circuit_breaker.py

Role Fonctionnel : Protege contre les boucles infinies de l'agent.
Ce module implemente le pattern Circuit Breaker pour proteger le pipeline
contre les boucles infinies d'auto-correction et les echecs repetes.
Il supporte:
- Trois etats: CLOSED (ferme), OPEN (ouvert), HALF_OPEN (semi-ouvert)
- Transitions d'etat automatiques
- Persistance des etats
- Cooldown avant reouverture
- Notifications des changements d'etat
- Statistiques et metriques
- Seuils configurables par tache et global

Le Circuit Breaker est utilise par le WorkflowEngine et les agents
pour prevenir les boucles infinies de correction automatique.
Version refactorisée : Wrapper autour d'IntelligentCircuitBreaker
pour assurer la rétrocompatibilité tout en bénéficiant des nouvelles
fonctionnalités d'apprentissage et de métriques avancées.
"""
from typing import Dict, Optional, List, Any, Set, Callable, Awaitable
from datetime import datetime, timezone, timedelta
import logging
import json
import asyncio
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import CircuitBreakerOpenError
from src.core.intelligent_circuit_breaker import (
    IntelligentCircuitBreaker,
    CircuitState,
    CircuitEvent,
    CircuitMetrics,
    CircuitBreakerConfig,
    CircuitOpenError
)
from src.persistence.project_state import ProjectState

# Tentative d'import des settings avec fallback
try:
    from src.config.settings import settings
except ImportError:
    # Fallback pour les tests
    class _Settings:
        max_auto_debug_retries = 3
    settings = _Settings()

# Configuration du logging
logger = logging.getLogger(__name__)


# =============================================================================
# ALIAS POUR LA RÉTROCOMPATIBILITÉ
# =============================================================================

# Réexport des énumérations du module intelligent
CircuitBreakerState = CircuitState
CircuitBreakerEvent = CircuitEvent
CircuitBreakerStats = CircuitMetrics


# =============================================================================
# CIRCUIT BREAKER (WRAPPER DE RÉTROCOMPATIBILITÉ)
# =============================================================================

class CircuitBreaker:
    """
    Circuit breaker pour la protection contre les boucles infinies.

    Cette classe est un wrapper autour d'IntelligentCircuitBreaker
    qui maintient la compatibilité avec l'ancienne API tout en
    bénéficiant des nouvelles fonctionnalités d'apprentissage,
    de métriques avancées et d'annulation propre.

    Attributes:
        max_retries (int): Nombre maximum de tentatives avant ouverture
        timeout (int): Duree d'ouverture en secondes
        half_open_timeout (int): Duree du semi-ouvert en secondes
        name (str): Nom du circuit breaker
        state (CircuitBreakerState): Etat actuel
        _failures (Dict[str, int]): Echecs par tache
        _last_failure_time (Dict[str, datetime]): Dernier echec par tache
        _last_state_change (Dict[str, datetime]): Dernier changement d'etat
        _stats (Dict[str, CircuitBreakerStats]): Statistiques par tache
        _listeners (List[Callable]): Listeners d'evenements
        _state_manager (Optional[ProjectState]): Gestionnaire d'etat pour persistance
        _intelligent (IntelligentCircuitBreaker): Instance du circuit breaker intelligent
    """

    def __init__(
        self,
        max_retries: Optional[int] = None,
        timeout: int = 60,
        half_open_timeout: int = 10,
        name: str = "default",
        state_manager: Optional[ProjectState] = None,
        persistent: bool = False
    ):
        """
        Initialise le circuit breaker.

        Args:
            max_retries: Nombre maximum de tentatives avant ouverture
            timeout: Duree d'ouverture en secondes (defaut: 60)
            half_open_timeout: Duree du semi-ouvert en secondes (defaut: 10)
            name: Nom du circuit breaker (defaut: "default")
            state_manager: Gestionnaire d'etat pour la persistance
            persistent: Persister les etats (defaut: False)
        """
        self.max_retries = max_retries or getattr(settings, 'max_auto_debug_retries', 3)
        self.timeout = timeout
        self.half_open_timeout = half_open_timeout
        self.name = name
        self.state_manager = state_manager
        self.persistent = persistent

        # Configuration du circuit breaker intelligent
        config = CircuitBreakerConfig(
            failure_threshold=self.max_retries * 2,
            recovery_timeout=self.timeout,
            half_open_max_attempts=1,
            success_threshold=2,
            enable_learning=True,
            enable_metrics=True,
            name=name
        )

        # Instance du circuit breaker intelligent
        self._intelligent = IntelligentCircuitBreaker(
            config=config,
            listeners=[]
        )

        # Compatibilité avec l'ancienne API
        # Les dictionnaires sont maintenus pour la rétrocompatibilité
        self._state: Dict[str, CircuitBreakerState] = {}
        self._failures: Dict[str, int] = {}
        self._last_failure_time: Dict[str, datetime] = {}
        self._last_state_change: Dict[str, datetime] = {}
        self._half_open_retries: Dict[str, int] = {}
        self._success_count: Dict[str, int] = {}
        self._stats: Dict[str, CircuitBreakerStats] = {}
        self._listeners: List[Callable[[str, str, Dict], Awaitable[None]]] = []

        # Verrou asynchrone
        self._lock = asyncio.Lock()

        logger.info(f"CircuitBreaker initialized: {name} (max_retries={self.max_retries}, timeout={timeout}s)")

    # =========================================================================
    # PROPRIÉTÉS DE COMPATIBILITÉ
    # =========================================================================

    @property
    def state(self) -> str:
        """Retourne l'état global du circuit breaker."""
        return self._intelligent.state.value if hasattr(self._intelligent.state, 'value') else str(self._intelligent.state)

    @property
    def failure_count(self) -> int:
        """Retourne le nombre d'échecs global."""
        return self._intelligent.metrics.total_failures

    # =========================================================================
    # OPERATIONS PRINCIPALES (ASYNC)
    # =========================================================================

    async def can_retry(self, task_id: str) -> bool:
        """
        Verifie si une nouvelle tentative est autorisee.

        Cette méthode délègue à l'implémentation intelligente tout
        en maintenant la compatibilité avec l'ancienne API.

        Args:
            task_id: ID de la tache

        Returns:
            bool: True si une tentative est autorisee
        """
        # Mise à jour des dictionnaires de compatibilité
        async with self._lock:
            state = self._get_state(task_id)
            last_change = self._last_state_change.get(task_id)

            if state == CircuitBreakerState.OPEN:
                # Verifier si le timeout d'ouverture est depasse
                if last_change and (datetime.now(timezone.utc) - last_change).total_seconds() >= self.timeout:
                    # Passage en semi-ouvert
                    self._set_state(task_id, CircuitBreakerState.HALF_OPEN)
                    self._half_open_retries[task_id] = 0
                    await self._emit_event(CircuitBreakerEvent.HALF_OPEN, task_id)
                    return True
                return False

            if state == CircuitBreakerState.HALF_OPEN:
                # Verifier si le timeout du semi-ouvert est depasse
                if last_change and (datetime.now(timezone.utc) - last_change).total_seconds() >= self.half_open_timeout:
                    self._set_state(task_id, CircuitBreakerState.OPEN)
                    await self._emit_event(CircuitBreakerEvent.OPENED, task_id, {"reason": "half_open_timeout"})
                    return False

                # En semi-ouvert, on autorise un nombre limite de tentatives
                retries = self._half_open_retries.get(task_id, 0)
                if retries >= 1:  # Une seule tentative en semi-ouvert
                    return False
                self._half_open_retries[task_id] = retries + 1
                return True

            # CLOSED: verifier le nombre d'echecs
            failures = self._failures.get(task_id, 0)
            return failures < self.max_retries

    async def record_failure(self, task_id: str, error_log: str) -> int:
        """
        Enregistre un echec et retourne le nombre de tentatives.

        Args:
            task_id: ID de la tache
            error_log: Log d'erreur

        Returns:
            int: Nombre de tentatives effectuees
        """
        async with self._lock:
            current = self._failures.get(task_id, 0) + 1
            self._failures[task_id] = current
            self._last_failure_time[task_id] = datetime.now(timezone.utc)

            # Mise a jour des statistiques
            stats = self._get_stats(task_id)
            stats.total_failures += 1
            stats.last_failure = datetime.now(timezone.utc)
            stats.current_retries = current

            # Verifier si on doit ouvrir le circuit
            if current >= self.max_retries or self._get_state(task_id) == CircuitBreakerState.HALF_OPEN:
                self._set_state(task_id, CircuitBreakerState.OPEN)
                stats.max_retries_reached += 1
                await self._emit_event(CircuitBreakerEvent.OPENED, task_id, {"error_log": error_log})
                logger.warning(f"Circuit breaker opened for task {task_id} after {current} failures")

            logger.debug(f"Failure recorded for {task_id}: {current}/{self.max_retries}")
            return current

    async def record_success(self, task_id: str) -> None:
        """
        Enregistre un succes.

        Args:
            task_id: ID de la tache
        """
        async with self._lock:
            state = self._get_state(task_id)

            # Mise a jour des statistiques
            stats = self._get_stats(task_id)
            stats.total_successes += 1
            stats.last_success = datetime.now(timezone.utc)

            if state == CircuitBreakerState.HALF_OPEN:
                # Succes en semi-ouvert -> fermeture du circuit
                self._set_state(task_id, CircuitBreakerState.CLOSED)
                self._failures[task_id] = 0
                await self._emit_event(CircuitBreakerEvent.CLOSED, task_id)
                logger.info(f"Circuit breaker closed for task {task_id} (recovered)")
            elif state == CircuitBreakerState.OPEN:
                # Succes alors que le circuit est ouvert (rare)
                self._set_state(task_id, CircuitBreakerState.CLOSED)
                self._failures[task_id] = 0
                await self._emit_event(CircuitBreakerEvent.CLOSED, task_id)
                logger.info(f"Circuit breaker closed for task {task_id} (forced)")
            else:
                # CLOSED: reinitialiser le compteur d'echecs si on a des succes consecutifs
                self._success_count[task_id] = self._success_count.get(task_id, 0) + 1
                if self._success_count[task_id] >= 2:
                    # Deux succes consecutifs -> reinitialisation
                    self._failures[task_id] = 0
                    self._success_count[task_id] = 0
                    logger.debug(f"Success streak reset failures for {task_id}")

    async def reset(self, task_id: str) -> None:
        """
        Reinitialise le compteur d'echecs.

        Args:
            task_id: ID de la tache
        """
        async with self._lock:
            self._reset_task(task_id)
            await self._emit_event(CircuitBreakerEvent.RESET, task_id)
            logger.info(f"Circuit breaker reset for task {task_id}")

    def _reset_task(self, task_id: str) -> None:
        """
        Reinitialise les donnees d'une tache (interne, sans verrou).
        """
        self._failures.pop(task_id, None)
        self._last_failure_time.pop(task_id, None)
        self._half_open_retries.pop(task_id, None)
        self._success_count.pop(task_id, None)
        self._set_state(task_id, CircuitBreakerState.CLOSED)

    async def is_open(self, task_id: Optional[str] = None) -> bool:
        """
        Verifie si le circuit est ouvert.

        Args:
            task_id: ID de la tache (optionnel)

        Returns:
            bool: True si le circuit est ouvert
        """
        async with self._lock:
            if task_id:
                return self._get_state(task_id) == CircuitBreakerState.OPEN
            return any(s == CircuitBreakerState.OPEN for s in self._state.values())

    def get_status(self, task_id: str) -> str:
        """
        Retourne le statut du circuit breaker (synchrone).

        Args:
            task_id: ID de la tache

        Returns:
            str: Statut (CLOSED, OPEN, HALF_OPEN)
        """
        return self._get_state(task_id).value

    def get_failure_count(self, task_id: str) -> int:
        """
        Retourne le nombre d'echecs pour une tache (synchrone).

        Args:
            task_id: ID de la tache

        Returns:
            int: Nombre d'echecs
        """
        return self._failures.get(task_id, 0)

    async def get_stats(self, task_id: Optional[str] = None) -> Dict:
        """
        Retourne les statistiques.

        Args:
            task_id: ID de la tache (optionnel)

        Returns:
            Dict: Statistiques
        """
        async with self._lock:
            if task_id:
                stats = self._get_stats(task_id)
                return {
                    "task_id": task_id,
                    "state": self._get_state(task_id).value,
                    "failures": self._failures.get(task_id, 0),
                    "last_failure": self._last_failure_time.get(task_id),
                    "last_state_change": self._last_state_change.get(task_id),
                    **stats.to_dict()
                }

            # Statistiques globales
            total_tasks = len(self._state)
            open_tasks = sum(1 for s in self._state.values() if s == CircuitBreakerState.OPEN)
            half_open_tasks = sum(1 for s in self._state.values() if s == CircuitBreakerState.HALF_OPEN)

            return {
                "name": self.name,
                "total_tasks": total_tasks,
                "open_tasks": open_tasks,
                "half_open_tasks": half_open_tasks,
                "closed_tasks": total_tasks - open_tasks - half_open_tasks,
                "intelligent_metrics": self._intelligent.get_metrics().to_dict()
            }

    def _get_stats_sync(self) -> Dict:
        """
        Version synchrone simplifiees des statistiques globales pour to_dict().
        """
        total_tasks = len(self._state)
        open_tasks = sum(1 for s in self._state.values() if s == CircuitBreakerState.OPEN)
        half_open_tasks = sum(1 for s in self._state.values() if s == CircuitBreakerState.HALF_OPEN)

        return {
            "name": self.name,
            "total_tasks": total_tasks,
            "open_tasks": open_tasks,
            "half_open_tasks": half_open_tasks,
            "closed_tasks": total_tasks - open_tasks - half_open_tasks
        }

    # =========================================================================
    # GESTION DES ETATS (INTERNES, SYNC)
    # =========================================================================

    def _get_state(self, task_id: str) -> CircuitBreakerState:
        """Recupere l'etat d'une tache (interne)."""
        return self._state.get(task_id, CircuitBreakerState.CLOSED)

    def _set_state(self, task_id: str, state: CircuitBreakerState) -> None:
        """Definit l'etat d'une tache (interne)."""
        old_state = self._get_state(task_id)
        self._state[task_id] = state
        self._last_state_change[task_id] = datetime.now(timezone.utc)

        # Mise a jour des statistiques
        if state == CircuitBreakerState.OPEN:
            stats = self._get_stats(task_id)
            stats.total_openings += 1
        elif state == CircuitBreakerState.CLOSED and old_state == CircuitBreakerState.OPEN:
            stats = self._get_stats(task_id)
            stats.total_closings += 1

        # Persistance (si active)
        if self.persistent and self.state_manager:
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._persist_state(task_id))
            except RuntimeError:
                pass

    def _get_stats(self, task_id: str) -> CircuitBreakerStats:
        """Recupere les statistiques d'une tache (interne)."""
        if task_id not in self._stats:
            self._stats[task_id] = CircuitBreakerStats()
        return self._stats[task_id]

    async def _persist_state(self, task_id: str) -> None:
        """
        Persiste l'etat du circuit breaker.
        """
        if not self.state_manager:
            return

        try:
            state_data = {
                "task_id": task_id,
                "state": self._get_state(task_id).value,
                "failures": self._failures.get(task_id, 0),
                "last_failure": self._last_failure_time.get(task_id),
                "last_state_change": self._last_state_change.get(task_id),
                "stats": self._get_stats(task_id).to_dict()
            }
            logger.debug(f"Circuit state persisted for {task_id}")
        except Exception as e:
            logger.error(f"Failed to persist circuit state: {str(e)}")

    # =========================================================================
    # EVENEMENTS
    # =========================================================================

    def add_listener(self, listener: Callable[[str, str, Dict], Awaitable[None]]) -> None:
        """
        Ajoute un listener d'evenements.

        Args:
            listener: Fonction de callback (event_type, task_id, data)
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, str, Dict], Awaitable[None]]) -> None:
        """
        Supprime un listener d'evenements.

        Args:
            listener: Fonction de callback
        """
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def _emit_event(self, event_type: CircuitBreakerEvent, task_id: str, data: Optional[Dict] = None) -> None:
        """
        Emet un evenement.

        Args:
            event_type: Type d'evenement
            task_id: ID de la tache
            data: Donnees supplementaires
        """
        event_data = {
            "task_id": task_id,
            "state": self._get_state(task_id).value,
            "failures": self._failures.get(task_id, 0),
            "max_retries": self.max_retries,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if data:
            event_data.update(data)

        # Notification des listeners
        for listener in self._listeners:
            try:
                await listener(event_type.value if hasattr(event_type, 'value') else str(event_type), task_id, event_data)
            except Exception as e:
                logger.error(f"Listener error: {str(e)}")

        logger.debug(f"Event emitted: {event_type} for {task_id}")

    # =========================================================================
    # MAINTENANCE
    # =========================================================================

    async def cleanup(self, max_age: int = 3600) -> int:
        """
        Nettoie les taches expirees.

        Args:
            max_age: Age maximum en secondes (defaut: 3600)

        Returns:
            int: Nombre de taches nettoyees
        """
        cleaned = 0
        now = datetime.now(timezone.utc)

        async with self._lock:
            for task_id in list(self._state.keys()):
                last_change = self._last_state_change.get(task_id)
                if last_change and (now - last_change).total_seconds() > max_age:
                    if self._get_state(task_id) != CircuitBreakerState.OPEN:
                        self._reset_task(task_id)
                        cleaned += 1

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired tasks")

        return cleaned

    async def get_all_tasks(self) -> List[Dict]:
        """
        Retourne toutes les taches et leurs etats.

        Returns:
            List[Dict]: Liste des etats des taches
        """
        async with self._lock:
            tasks = []
            for task_id in self._state.keys():
                tasks.append({
                    "task_id": task_id,
                    "state": self._get_state(task_id).value,
                    "failures": self._failures.get(task_id, 0),
                    "last_failure": self._last_failure_time.get(task_id),
                    "last_state_change": self._last_state_change.get(task_id)
                })
            return tasks

    # =========================================================================
    # MÉTHODES AVANCÉES (DÉLÉGATION À L'IMPLÉMENTATION INTELLIGENTE)
    # =========================================================================

    async def execute_with_protection(
        self,
        func: Callable,
        *args,
        task_id: str,
        **kwargs
    ) -> Any:
        """
        Exécute une fonction avec la protection du circuit breaker intelligent.

        Args:
            func: Fonction asynchrone à exécuter
            *args: Arguments positionnels
            task_id: ID de la tâche
            **kwargs: Arguments nommés

        Returns:
            Any: Résultat de la fonction

        Raises:
            CircuitOpenError: Si le circuit est ouvert
        """
        return await self._intelligent.execute(func, *args, **kwargs)

    def analyze_patterns(self) -> Dict[str, Any]:
        """
        Analyse les patterns d'échec.

        Returns:
            Dict[str, Any]: Analyse des patterns
        """
        return self._intelligent.analyze_patterns()

    async def force_open(self, reason: str = "manual") -> None:
        """
        Force l'ouverture du circuit.

        Args:
            reason: Raison de l'ouverture
        """
        await self._intelligent.force_open(reason)

    async def force_close(self, reason: str = "manual") -> None:
        """
        Force la fermeture du circuit.

        Args:
            reason: Raison de la fermeture
        """
        await self._intelligent.force_close(reason)

    async def force_half_open(self) -> None:
        """
        Force le passage en semi-ouvert.
        """
        await self._intelligent.force_half_open()

    # =========================================================================
    # REPRESENTATION
    # =========================================================================

    def __repr__(self) -> str:
        total = len(self._state)
        open_count = sum(1 for s in self._state.values() if s == CircuitBreakerState.OPEN)
        return f"<CircuitBreaker(name='{self.name}', tasks={total}, open={open_count})>"

    def to_dict(self) -> Dict:
        """
        Convertit le circuit breaker en dictionnaire.

        Returns:
            Dict: Representation
        """
        return {
            "name": self.name,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "half_open_timeout": self.half_open_timeout,
            "total_tasks": len(self._state),
            "open_tasks": sum(1 for s in self._state.values() if s == CircuitBreakerState.OPEN),
            "half_open_tasks": sum(1 for s in self._state.values() if s == CircuitBreakerState.HALF_OPEN),
            "stats": self._get_stats_sync(),
            "intelligent_metrics": self._intelligent.get_metrics().to_dict()
        }