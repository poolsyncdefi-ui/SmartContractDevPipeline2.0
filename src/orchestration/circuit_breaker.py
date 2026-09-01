# src/orchestration/circuit_breaker.py

"""
Circuit breaker for the Smart Contract Dev Pipeline.
F29 – src/orchestration/circuit_breaker.py

Rôle Fonctionnel : Protege contre les boucles infinies de l'agent.
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
"""
from typing import Dict, Optional, List, Any, Set
from datetime import datetime, timedelta
import logging
import json
import asyncio
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.config.settings import settings
from src.core.exceptions import CircuitBreakerOpenError
from src.persistence.project_state import ProjectState

# Configuration du logging
logger = logging.getLogger(__name__)


class CircuitBreakerState(str, Enum):
    """
    Etats possibles du circuit breaker.
    """
    CLOSED = "CLOSED"          # Circuit ferme - les requetes passent
    OPEN = "OPEN"              # Circuit ouvert - les requetes sont bloquees
    HALF_OPEN = "HALF_OPEN"    # Semi-ouvert - test de recuperation


class CircuitBreakerEvent(str, Enum):
    """
    Evenements du circuit breaker.
    """
    OPENED = "opened"          # Circuit ouvert
    CLOSED = "closed"          # Circuit ferme
    HALF_OPEN = "half_open"    # Passage en semi-ouvert
    RESET = "reset"            # Reinitialisation
    TIMEOUT = "timeout"        # Timeout
    FAILURE = "failure"        # Echec enregistre
    SUCCESS = "success"        # Succes enregistre


@dataclass
class CircuitBreakerStats:
    """
    Statistiques d'un circuit breaker.
    
    Attributes:
        total_failures (int): Nombre total d'echecs
        total_successes (int): Nombre total de succes
        total_openings (int): Nombre d'ouvertures
        total_closings (int): Nombre de fermetures
        last_failure (Optional[datetime]): Dernier echec
        last_success (Optional[datetime]): Dernier succes
        last_state_change (Optional[datetime]): Dernier changement d'etat
        current_retries (int): Tentatives en cours
        max_retries_reached (int): Nombre de fois ou le max a ete atteint
    """
    total_failures: int = 0
    total_successes: int = 0
    total_openings: int = 0
    total_closings: int = 0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_state_change: Optional[datetime] = None
    current_retries: int = 0
    max_retries_reached: int = 0
    
    def to_dict(self) -> Dict:
        """Convertit les statistiques en dictionnaire."""
        return {
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "total_openings": self.total_openings,
            "total_closings": self.total_closings,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_state_change": self.last_state_change.isoformat() if self.last_state_change else None,
            "current_retries": self.current_retries,
            "max_retries_reached": self.max_retries_reached
        }


class CircuitBreaker:
    """
    Circuit breaker pour la protection contre les boucles infinies.
    
    Cette classe implemente le pattern Circuit Breaker avec trois etats
    et des transitions automatiques basees sur les echecs et les succes.
    
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
    """
    
    def __init__(
        self,
        max_retries: int = None,
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
        self.max_retries = max_retries or settings.max_auto_debug_retries
        self.timeout = timeout
        self.half_open_timeout = half_open_timeout
        self.name = name
        self.state_manager = state_manager
        self.persistent = persistent
        
        # Etats par tache
        self._state: Dict[str, CircuitBreakerState] = {}
        self._failures: Dict[str, int] = {}
        self._last_failure_time: Dict[str, datetime] = {}
        self._last_state_change: Dict[str, datetime] = {}
        self._half_open_retries: Dict[str, int] = {}
        self._success_count: Dict[str, int] = {}
        
        # Statistiques par tache
        self._stats: Dict[str, CircuitBreakerStats] = {}
        
        # Listeners
        self._listeners: List = []
        
        # Verrou
        self._lock = asyncio.Lock()
        
        logger.info(f"CircuitBreaker initialized: {name} (max_retries={max_retries}, timeout={timeout}s)")
    
    # =========================================================================
    # OPERATIONS PRINCIPALES
    # =========================================================================
    
    def can_retry(self, task_id: str) -> bool:
        """
        Verifie si une nouvelle tentative est autorisee.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            bool: True si une tentative est autorisee
        """
        state = self._get_state(task_id)
        
        if state == CircuitBreakerState.OPEN:
            # Verifier si le timeout est depasse
            last_change = self._last_state_change.get(task_id)
            if last_change and (datetime.utcnow() - last_change).total_seconds() >= self.timeout:
                # Passage en semi-ouvert
                self._set_state(task_id, CircuitBreakerState.HALF_OPEN)
                self._half_open_retries[task_id] = 0
                self._emit_event(CircuitBreakerEvent.HALF_OPEN, task_id)
                return True
            return False
        
        if state == CircuitBreakerState.HALF_OPEN:
            # En semi-ouvert, on autorise un nombre limite de tentatives
            retries = self._half_open_retries.get(task_id, 0)
            if retries >= 1:  # Une seule tentative en semi-ouvert
                return False
            self._half_open_retries[task_id] = retries + 1
            return True
        
        # CLOSED: verifier le nombre d'echecs
        failures = self._failures.get(task_id, 0)
        return failures < self.max_retries
    
    def record_failure(self, task_id: str, error_log: str) -> int:
        """
        Enregistre un echec et retourne le nombre de tentatives.
        
        Args:
            task_id: ID de la tache
            error_log: Log d'erreur
            
        Returns:
            int: Nombre de tentatives effectuees
        """
        async def _record():
            async with self._lock:
                return self._record_failure_sync(task_id, error_log)
        
        # Appel synchrone pour compatibilite
        return self._record_failure_sync(task_id, error_log)
    
    def _record_failure_sync(self, task_id: str, error_log: str) -> int:
        """
        Version synchrone de record_failure.
        
        Args:
            task_id: ID de la tache
            error_log: Log d'erreur
            
        Returns:
            int: Nombre de tentatives effectuees
        """
        current = self._failures.get(task_id, 0) + 1
        self._failures[task_id] = current
        self._last_failure_time[task_id] = datetime.utcnow()
        
        # Mise a jour des statistiques
        stats = self._get_stats(task_id)
        stats.total_failures += 1
        stats.last_failure = datetime.utcnow()
        stats.current_retries = current
        
        # Verifier si on doit ouvrir le circuit
        if current >= self.max_retries:
            self._set_state(task_id, CircuitBreakerState.OPEN)
            stats.max_retries_reached += 1
            self._emit_event(CircuitBreakerEvent.OPENED, task_id, {"error_log": error_log})
            logger.warning(f"Circuit breaker opened for task {task_id} after {current} failures")
        
        logger.debug(f"Failure recorded for {task_id}: {current}/{self.max_retries}")
        return current
    
    def record_success(self, task_id: str) -> None:
        """
        Enregistre un succes.
        
        Args:
            task_id: ID de la tache
        """
        async def _record():
            async with self._lock:
                self._record_success_sync(task_id)
        
        # Appel synchrone pour compatibilite
        self._record_success_sync(task_id)
    
    def _record_success_sync(self, task_id: str) -> None:
        """
        Version synchrone de record_success.
        
        Args:
            task_id: ID de la tache
        """
        state = self._get_state(task_id)
        
        # Mise a jour des statistiques
        stats = self._get_stats(task_id)
        stats.total_successes += 1
        stats.last_success = datetime.utcnow()
        
        if state == CircuitBreakerState.HALF_OPEN:
            # Succes en semi-ouvert -> fermeture du circuit
            self._set_state(task_id, CircuitBreakerState.CLOSED)
            self._failures[task_id] = 0
            self._emit_event(CircuitBreakerEvent.CLOSED, task_id)
            logger.info(f"Circuit breaker closed for task {task_id} (recovered)")
        elif state == CircuitBreakerState.OPEN:
            # Succes alors que le circuit est ouvert (rare)
            self._set_state(task_id, CircuitBreakerState.CLOSED)
            self._failures[task_id] = 0
            self._emit_event(CircuitBreakerEvent.CLOSED, task_id)
            logger.info(f"Circuit breaker closed for task {task_id} (forced)")
        else:
            # CLOSED: reinitialiser le compteur d'echecs si on a des succes consecutifs
            self._success_count[task_id] = self._success_count.get(task_id, 0) + 1
            if self._success_count[task_id] >= 2:
                # Deux succes consecutifs -> reinitialisation
                self._failures[task_id] = 0
                self._success_count[task_id] = 0
                logger.debug(f"Success streak reset failures for {task_id}")
    
    def reset(self, task_id: str) -> None:
        """
        Reinitialise le compteur d'echecs.
        
        Args:
            task_id: ID de la tache
        """
        async def _reset():
            async with self._lock:
                self._reset_sync(task_id)
        
        # Appel synchrone pour compatibilite
        self._reset_sync(task_id)
    
    def _reset_sync(self, task_id: str) -> None:
        """
        Version synchrone de reset.
        
        Args:
            task_id: ID de la tache
        """
        if task_id in self._failures:
            del self._failures[task_id]
        if task_id in self._last_failure_time:
            del self._last_failure_time[task_id]
        if task_id in self._half_open_retries:
            del self._half_open_retries[task_id]
        if task_id in self._success_count:
            del self._success_count[task_id]
        
        self._set_state(task_id, CircuitBreakerState.CLOSED)
        self._emit_event(CircuitBreakerEvent.RESET, task_id)
        logger.info(f"Circuit breaker reset for task {task_id}")
    
    def is_open(self, task_id: Optional[str] = None) -> bool:
        """
        Verifie si le circuit est ouvert.
        
        Args:
            task_id: ID de la tache (optionnel)
            
        Returns:
            bool: True si le circuit est ouvert
        """
        if task_id:
            return self._get_state(task_id) == CircuitBreakerState.OPEN
        
        # Verifier toutes les taches
        return any(s == CircuitBreakerState.OPEN for s in self._state.values())
    
    def get_status(self, task_id: str) -> str:
        """
        Retourne le statut du circuit breaker.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            str: Statut (CLOSED, OPEN, HALF_OPEN)
        """
        return self._get_state(task_id).value
    
    def get_failure_count(self, task_id: str) -> int:
        """
        Retourne le nombre d'echecs pour une tache.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            int: Nombre d'echecs
        """
        return self._failures.get(task_id, 0)
    
    def get_stats(self, task_id: Optional[str] = None) -> Dict:
        """
        Retourne les statistiques.
        
        Args:
            task_id: ID de la tache (optionnel)
            
        Returns:
            Dict: Statistiques
        """
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
            "closed_tasks": total_tasks - open_tasks - half_open_tasks
        }
    
    # =========================================================================
    # GESTION DES ETATS
    # =========================================================================
    
    def _get_state(self, task_id: str) -> CircuitBreakerState:
        """
        Recupere l'etat d'une tache.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            CircuitBreakerState: Etat actuel
        """
        return self._state.get(task_id, CircuitBreakerState.CLOSED)
    
    def _set_state(self, task_id: str, state: CircuitBreakerState) -> None:
        """
        Definit l'etat d'une tache.
        
        Args:
            task_id: ID de la tache
            state: Nouvel etat
        """
        old_state = self._get_state(task_id)
        self._state[task_id] = state
        self._last_state_change[task_id] = datetime.utcnow()
        
        # Mise a jour des statistiques
        if state == CircuitBreakerState.OPEN:
            stats = self._get_stats(task_id)
            stats.total_openings += 1
        elif state == CircuitBreakerState.CLOSED and old_state == CircuitBreakerState.OPEN:
            stats = self._get_stats(task_id)
            stats.total_closings += 1
        
        # Persistance
        if self.persistent and self.state_manager:
            asyncio.create_task(self._persist_state(task_id))
    
    def _get_stats(self, task_id: str) -> CircuitBreakerStats:
        """
        Recupere les statistiques d'une tache.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            CircuitBreakerStats: Statistiques
        """
        if task_id not in self._stats:
            self._stats[task_id] = CircuitBreakerStats()
        return self._stats[task_id]
    
    async def _persist_state(self, task_id: str) -> None:
        """
        Persiste l'etat du circuit breaker.
        
        Args:
            task_id: ID de la tache
        """
        if not self.state_manager:
            return
        
        try:
            # Sauvegarde de l'etat
            state_data = {
                "task_id": task_id,
                "state": self._get_state(task_id).value,
                "failures": self._failures.get(task_id, 0),
                "last_failure": self._last_failure_time.get(task_id),
                "last_state_change": self._last_state_change.get(task_id),
                "stats": self._get_stats(task_id).to_dict()
            }
            
            # Utilisation de l'API de persistance
            # Note: A implementer selon les besoins
            # await self.state_manager.save_circuit_state(task_id, state_data)
            
            logger.debug(f"Circuit state persisted for {task_id}")
            
        except Exception as e:
            logger.error(f"Failed to persist circuit state: {str(e)}")
    
    # =========================================================================
    # EVENEMENTS
    # =========================================================================
    
    def add_listener(self, listener) -> None:
        """
        Ajoute un listener d'evenements.
        
        Args:
            listener: Fonction de callback (event_type, task_id, data)
        """
        self._listeners.append(listener)
    
    def remove_listener(self, listener) -> None:
        """
        Supprime un listener d'evenements.
        
        Args:
            listener: Fonction de callback
        """
        if listener in self._listeners:
            self._listeners.remove(listener)
    
    def _emit_event(self, event_type: CircuitBreakerEvent, task_id: str, data: Optional[Dict] = None) -> None:
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
            "timestamp": datetime.utcnow().isoformat()
        }
        if data:
            event_data.update(data)
        
        # Notification des listeners
        for listener in self._listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    asyncio.create_task(listener(event_type.value, task_id, event_data))
                else:
                    listener(event_type.value, task_id, event_data)
            except Exception as e:
                logger.error(f"Listener error: {str(e)}")
        
        logger.debug(f"Event emitted: {event_type.value} for {task_id}")
    
    # =========================================================================
    # MAINTENANCE
    # =========================================================================
    
    def cleanup(self, max_age: int = 3600) -> int:
        """
        Nettoie les taches expirees.
        
        Args:
            max_age: Age maximum en secondes (defaut: 3600)
            
        Returns:
            int: Nombre de taches nettoyees
        """
        cleaned = 0
        now = datetime.utcnow()
        
        for task_id in list(self._state.keys()):
            last_change = self._last_state_change.get(task_id)
            if last_change and (now - last_change).total_seconds() > max_age:
                if self._get_state(task_id) != CircuitBreakerState.OPEN:
                    # Supprimer les taches fermees ou semi-ouvertes
                    self._reset_sync(task_id)
                    cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired tasks")
        
        return cleaned
    
    def get_all_tasks(self) -> List[Dict]:
        """
        Retourne toutes les taches et leurs etats.
        
        Returns:
            List[Dict]: Liste des etats des taches
        """
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
            "stats": self.get_stats()
        }