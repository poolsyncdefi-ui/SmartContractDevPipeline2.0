# src/agents/base/abstract_agent.py

"""
Abstract base agent class for the Smart Contract Dev Pipeline.
F14 – src/agents/base/abstract_agent.py

Rôle Fonctionnel : Classe de base abstraite definissant l'interface commune pour tous les agents.
Cette classe fournit le squelette de base pour tous les agents du pipeline,
incluant la gestion des competences, l'historique d'execution, et les methodes
de validation et de monitoring. Tous les agents specifiques (Architect, Developer,
Security, Feedback) doivent heriter de cette classe.

Cette implementation est conforme aux specifications du pipeline et inclut
le support pour le circuit breaker, le RAG, et la validation des competences.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Type, Union, Callable, Awaitable
from datetime import datetime
import asyncio
import logging
import json
import time
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.agents.base.skill import BaseSkill
from src.core.exceptions import (
    PipelineError, 
    LLMError, 
    SkillNotFoundError,
    CircuitBreakerOpenError,
    TaskExecutionError
)
from src.config.settings import settings
from src.models.execution_log import (
    ExecutionLogModel, 
    LogLevel, 
    LogCategory,
    LoggableMixin
)

# Configuration du logging
logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    """
    Enum des statuts possibles pour un agent.
    """
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class AgentEvent(str, Enum):
    """
    Événements possibles d'un agent.
    """
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_CLOSED = "circuit_closed"
    SKILL_ATTACHED = "skill_attached"
    SKILL_REMOVED = "skill_removed"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCELLED = "cancelled"


@dataclass
class AgentMetrics:
    """
    Métriques de performance d'un agent.
    
    Attributes:
        total_executions (int): Nombre total d'exécutions
        successful_executions (int): Exécutions réussies
        failed_executions (int): Exécutions échouées
        total_duration (float): Durée totale d'exécution (secondes)
        average_duration (float): Durée moyenne d'exécution (secondes)
        max_duration (float): Durée maximale d'exécution (secondes)
        min_duration (float): Durée minimale d'exécution (secondes)
        total_retries (int): Nombre total de tentatives
        success_rate (float): Taux de succès (0-1)
        last_execution_time (Optional[datetime]): Dernière exécution
        first_execution_time (Optional[datetime]): Première exécution
        skills_used (Dict[str, int]): Compétences utilisées et leur nombre d'utilisations
    """
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_duration: float = 0.0
    average_duration: float = 0.0
    max_duration: float = 0.0
    min_duration: float = float('inf')
    total_retries: int = 0
    success_rate: float = 0.0
    last_execution_time: Optional[datetime] = None
    first_execution_time: Optional[datetime] = None
    skills_used: Dict[str, int] = field(default_factory=dict)
    
    def update(self, duration: float, success: bool, retries: int = 0, skill_ids: List[str] = None) -> None:
        """
        Met à jour les métriques avec une nouvelle exécution.
        
        Args:
            duration: Durée de l'exécution (secondes)
            success: Succès de l'exécution
            retries: Nombre de tentatives
            skill_ids: IDs des compétences utilisées
        """
        self.total_executions += 1
        self.total_duration += duration
        self.total_retries += retries
        
        if success:
            self.successful_executions += 1
        else:
            self.failed_executions += 1
        
        self.max_duration = max(self.max_duration, duration)
        self.min_duration = min(self.min_duration, duration)
        self.average_duration = self.total_duration / self.total_executions
        self.success_rate = self.successful_executions / self.total_executions if self.total_executions > 0 else 0
        
        self.last_execution_time = datetime.utcnow()
        if not self.first_execution_time:
            self.first_execution_time = datetime.utcnow()
        
        # Mise à jour des compétences utilisées
        if skill_ids:
            for skill_id in skill_ids:
                self.skills_used[skill_id] = self.skills_used.get(skill_id, 0) + 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "total_duration": self.total_duration,
            "average_duration": self.average_duration,
            "max_duration": self.max_duration,
            "min_duration": self.min_duration if self.min_duration != float('inf') else 0,
            "total_retries": self.total_retries,
            "success_rate": self.success_rate,
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
            "first_execution_time": self.first_execution_time.isoformat() if self.first_execution_time else None,
            "skills_used": self.skills_used
        }


class AbstractAgent(ABC, LoggableMixin):
    """
    Classe de base abstraite pour tous les agents du pipeline.
    
    Cette classe fournit l'infrastructure commune pour tous les agents,
    incluant:
    - Gestion des competences (skills)
    - Historique d'execution
    - Circuit breaker pour eviter les boucles infinies
    - Support RAG pour la generation augmentee par recuperation
    - Validation des entrees et sorties
    - Monitoring et health checks
    - Métriques de performance
    - Événements et notifications
    
    Attributes:
        agent_id (str): Identifiant unique de l'agent
        name (str): Nom descriptif de l'agent
        skills (List[BaseSkill]): Liste des competences de l'agent
        history (List[Dict]): Historique des executions
        status (AgentStatus): Statut actuel de l'agent
        max_retries (int): Nombre maximum de tentatives
        retry_count (int): Compteur de tentatives actuel
        llm_client (Optional): Client LLM pour les appels IA
        knowledge_base (Optional): Base de connaissances pour le RAG
        metrics (AgentMetrics): Métriques de performance
        _event_listeners (List[Callable]): Listeners d'événements
        _task_timeout (Optional[int]): Timeout par tâche en secondes
    """
    
    def __init__(
        self, 
        agent_id: str, 
        name: str, 
        skills: Optional[List[BaseSkill]] = None,
        llm_client = None,
        knowledge_base = None,
        max_retries: int = 3,
        task_timeout: Optional[int] = None,
        log_callback: Optional[Callable] = None
    ):
        """
        Initialise un nouvel agent.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom descriptif de l'agent
            skills: Liste initiale des competences (optionnelle)
            llm_client: Client LLM pour les appels IA (optionnel)
            knowledge_base: Base de connaissances pour le RAG (optionnel)
            max_retries: Nombre maximum de tentatives (defaut: 3)
            task_timeout: Timeout par tâche en secondes (optionnel)
            log_callback: Callback pour la persistance des logs (optionnel)
        """
        # Initialisation du mixin
        LoggableMixin.__init__(self)
        
        self.agent_id = agent_id
        self.name = name
        self.skills = skills or []
        self.history: List[Dict] = []
        self.status = AgentStatus.IDLE
        self.max_retries = max_retries
        self.retry_count = 0
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self.task_timeout = task_timeout
        
        # Circuit breaker
        self._circuit_breaker_state = False
        self._circuit_breaker_failures = 0
        self._circuit_breaker_threshold = max_retries * 2  # Seuil d'ouverture
        
        # Métriques
        self.metrics = AgentMetrics()
        
        # Événements
        self._event_listeners: List[Callable[[AgentEvent, Dict], Awaitable[None]]] = []
        
        # Verrouillage
        self._execution_lock = asyncio.Lock()
        
        # Callback de log
        if log_callback:
            self.set_log_callback(log_callback)
        
        # État d'annulation
        self._cancelled = False
        
        logger.info(f"Agent initialized: {agent_id} ({name})")
    
    # =========================================================================
    # METHODES ABSTRAITES
    # =========================================================================
    
    @abstractmethod
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute une tache specifique.
        
        Cette methode doit etre implementee par chaque type d'agent.
        Elle inclut automatiquement la gestion du circuit breaker,
        la validation des entrees, et l'enregistrement des logs.
        
        Args:
            task_data: Dictionnaire contenant les donnees de la tache
                      Doit inclure au minimum:
                      - 'task_id': Identifiant de la tache
                      - 'action': Action a executer
                      - 'payload': Donnees de la tache
            
        Returns:
            Dict contenant:
            - 'status': SUCCESS, FAILED, ou CIRCUIT_OPEN
            - 'result': Resultat de l'execution (si succes)
            - 'error': Message d'erreur (si echec)
            - 'retry_count': Nombre de tentatives effectuees
            - 'duration': Duree d'execution en secondes
        """
        pass
    
    # =========================================================================
    # EXECUTION AVEC CIRCUIT BREAKER
    # =========================================================================
    
    async def execute_with_circuit_breaker(
        self, 
        task_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute une tache avec protection du circuit breaker.
        
        Cette methode encapsule l'execution de la tache avec:
        - Verification de l'etat du circuit breaker
        - Gestion des tentatives automatiques
        - Logging des erreurs
        - Mise a jour du statut
        
        Args:
            task_data: Donnees de la tache a executer
            
        Returns:
            Dict: Resultat de l'execution
            
        Raises:
            CircuitBreakerOpenError: Si le circuit est ouvert
        """
        async with self._execution_lock:
            if self._cancelled:
                return {
                    "status": "CANCELLED",
                    "error": "Task cancelled",
                    "retry_count": 0,
                    "duration": 0
                }
            
            start_time = datetime.utcnow()
            self.status = AgentStatus.RUNNING
            self.retry_count = 0
            
            # Verification du circuit breaker
            if self._circuit_breaker_state:
                logger.warning(f"Circuit breaker open for agent {self.agent_id}")
                self.status = AgentStatus.CIRCUIT_OPEN
                await self._emit_event(AgentEvent.CIRCUIT_OPENED, {
                    "failures": self._circuit_breaker_failures,
                    "threshold": self._circuit_breaker_threshold
                })
                return {
                    "status": "CIRCUIT_OPEN",
                    "error": "Circuit breaker is open. Please reset or wait.",
                    "retry_count": self.retry_count,
                    "duration": (datetime.utcnow() - start_time).total_seconds()
                }
            
            # Notification de début
            await self._emit_event(AgentEvent.STARTED, {
                "task_id": task_data.get("task_id"),
                "action": task_data.get("action")
            })
            
            # Récupération des IDs des compétences utilisées
            skill_ids = [s.skill_id for s in self.skills]
            
            while self.retry_count < self.max_retries:
                try:
                    # Validation des entrées
                    self._validate_task_data(task_data)
                    
                    # Exécution de la tâche avec timeout
                    if self.task_timeout:
                        result = await asyncio.wait_for(
                            self.execute_task(task_data),
                            timeout=self.task_timeout
                        )
                    else:
                        result = await self.execute_task(task_data)
                    
                    # Validation de la sortie
                    self._validate_result(result)
                    
                    # Succès
                    self._circuit_breaker_state = False
                    self._circuit_breaker_failures = 0
                    self.status = AgentStatus.COMPLETED
                    
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    
                    # Mise à jour des métriques
                    self.metrics.update(duration, True, self.retry_count, skill_ids)
                    
                    # Ajout des métriques au résultat
                    result.update({
                        "retry_count": self.retry_count,
                        "duration": duration,
                        "execution_count": self.metrics.total_executions
                    })
                    
                    # Logging
                    await self._log_execution(
                        task_data=task_data,
                        result=result,
                        success=True,
                        duration=duration
                    )
                    
                    # Notification de succès
                    await self._emit_event(AgentEvent.COMPLETED, {
                        "task_id": task_data.get("task_id"),
                        "duration": duration,
                        "result": result
                    })
                    
                    logger.info(f"Task executed successfully by {self.agent_id} in {duration:.2f}s")
                    return result
                    
                except asyncio.TimeoutError:
                    self.retry_count += 1
                    logger.warning(
                        f"Task timed out (attempt {self.retry_count}/{self.max_retries})"
                    )
                    
                    await self._log_error(
                        task_data.get("task_id", "unknown"),
                        f"Timeout after {self.task_timeout}s",
                        tool_output="Task execution timed out"
                    )
                    
                    if self.retry_count >= self.max_retries:
                        self._circuit_breaker_state = True
                        self._circuit_breaker_failures += 1
                        self.status = AgentStatus.FAILED
                        
                        error_msg = f"Max retries ({self.max_retries}) exceeded"
                        logger.error(f"{error_msg} for agent {self.agent_id}")
                        
                        await self._emit_event(AgentEvent.CIRCUIT_OPENED, {
                            "reason": "timeout",
                            "failures": self._circuit_breaker_failures
                        })
                        
                        return {
                            "status": "FAILED",
                            "error": error_msg,
                            "retry_count": self.retry_count,
                            "duration": (datetime.utcnow() - start_time).total_seconds(),
                            "last_error": "Timeout"
                        }
                    
                    wait_time = 2 ** self.retry_count
                    await asyncio.sleep(wait_time)
                    
                except (PipelineError, LLMError, TaskExecutionError) as e:
                    self.retry_count += 1
                    logger.warning(
                        f"Task failed (attempt {self.retry_count}/{self.max_retries}): {str(e)}"
                    )
                    
                    # Log de l'erreur
                    await self._log_error(
                        task_data.get("task_id", "unknown"),
                        str(e),
                        tool_output=getattr(e, 'tool_output', None)
                    )
                    
                    # Si max retries atteint
                    if self.retry_count >= self.max_retries:
                        self._circuit_breaker_state = True
                        self._circuit_breaker_failures += 1
                        self.status = AgentStatus.FAILED
                        
                        error_msg = f"Max retries ({self.max_retries}) exceeded"
                        logger.error(f"{error_msg} for agent {self.agent_id}")
                        
                        await self._emit_event(AgentEvent.CIRCUIT_OPENED, {
                            "reason": "max_retries",
                            "failures": self._circuit_breaker_failures
                        })
                        
                        return {
                            "status": "FAILED",
                            "error": error_msg,
                            "retry_count": self.retry_count,
                            "duration": (datetime.utcnow() - start_time).total_seconds(),
                            "last_error": str(e)
                        }
                    
                    # Notification de retry
                    await self._emit_event(AgentEvent.RETRY, {
                        "task_id": task_data.get("task_id"),
                        "attempt": self.retry_count,
                        "max_retries": self.max_retries
                    })
                    
                    # Attente avant retry (backoff exponentiel)
                    wait_time = 2 ** self.retry_count
                    await asyncio.sleep(wait_time)
                    
                except Exception as e:
                    # Erreur inattendue
                    logger.error(f"Unexpected error in agent {self.agent_id}: {str(e)}")
                    self._circuit_breaker_state = True
                    self._circuit_breaker_failures += 1
                    self.status = AgentStatus.FAILED
                    
                    await self._emit_event(AgentEvent.FAILED, {
                        "task_id": task_data.get("task_id"),
                        "error": str(e)
                    })
                    
                    return {
                        "status": "FAILED",
                        "error": f"Unexpected error: {str(e)}",
                        "retry_count": self.retry_count,
                        "duration": (datetime.utcnow() - start_time).total_seconds()
                    }
            
            # Fallback
            return {
                "status": "FAILED",
                "error": "Unknown error in circuit breaker",
                "retry_count": self.retry_count,
                "duration": (datetime.utcnow() - start_time).total_seconds()
            }
    
    # =========================================================================
    # GESTION DES COMPETENCES
    # =========================================================================
    
    def attach_skill(self, skill: BaseSkill) -> None:
        """
        Ajoute une competence a l'agent avec validation.
        
        Args:
            skill: Competence a ajouter
            
        Raises:
            ValueError: Si la competence n'est pas valide
        """
        if not isinstance(skill, BaseSkill):
            raise ValueError(f"Skill must be a BaseSkill instance, got {type(skill)}")
        
        # Verification des doublons
        if any(s.skill_id == skill.skill_id for s in self.skills):
            logger.warning(f"Skill {skill.skill_id} already attached to agent {self.agent_id}")
            return
        
        self.skills.append(skill)
        logger.info(f"Skill {skill.skill_id} attached to agent {self.agent_id}")
        
        # Événement
        asyncio.create_task(self._emit_event(AgentEvent.SKILL_ATTACHED, {
            "skill_id": skill.skill_id,
            "skill_name": skill.name
        }))
    
    def remove_skill(self, skill_id: str) -> bool:
        """
        Supprime une competence de l'agent.
        
        Args:
            skill_id: ID de la competence a supprimer
            
        Returns:
            bool: True si supprime, False sinon
        """
        for i, skill in enumerate(self.skills):
            if skill.skill_id == skill_id:
                removed = self.skills.pop(i)
                logger.info(f"Skill {skill_id} removed from agent {self.agent_id}")
                
                asyncio.create_task(self._emit_event(AgentEvent.SKILL_REMOVED, {
                    "skill_id": skill_id,
                    "skill_name": removed.name
                }))
                return True
        
        return False
    
    def get_skill(self, skill_id: str) -> Optional[BaseSkill]:
        """
        Recupere une competence par son ID.
        
        Args:
            skill_id: ID de la competence
            
        Returns:
            Optional[BaseSkill]: Competence ou None
        """
        for skill in self.skills:
            if skill.skill_id == skill_id:
                return skill
        return None
    
    def has_skill(self, skill_id: str) -> bool:
        """
        Verifie si une competence est presente.
        
        Args:
            skill_id: ID de la competence
            
        Returns:
            bool: True si presente
        """
        return any(s.skill_id == skill_id for s in self.skills)
    
    # =========================================================================
    # GESTION DES EVENEMENTS
    # =========================================================================
    
    def add_event_listener(
        self,
        listener: Callable[[AgentEvent, Dict], Awaitable[None]]
    ) -> None:
        """
        Ajoute un listener d'événements.
        
        Args:
            listener: Fonction async appelée avec (event_type, data)
        """
        self._event_listeners.append(listener)
    
    def remove_event_listener(
        self,
        listener: Callable[[AgentEvent, Dict], Awaitable[None]]
    ) -> None:
        """
        Supprime un listener d'événements.
        
        Args:
            listener: Fonction de callback à supprimer
        """
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)
    
    async def _emit_event(self, event_type: AgentEvent, data: Dict) -> None:
        """
        Émet un événement à tous les listeners.
        
        Args:
            event_type: Type d'événement
            data: Données de l'événement
        """
        for listener in self._event_listeners:
            try:
                await listener(event_type, data)
            except Exception as e:
                logger.error(f"Event listener error: {str(e)}")
    
    # =========================================================================
    # LOGGING
    # =========================================================================
    
    async def _log_execution(
        self,
        task_data: Dict[str, Any],
        result: Dict[str, Any],
        success: bool,
        duration: float
    ) -> None:
        """
        Log l'exécution d'une tâche.
        
        Args:
            task_data: Données de la tâche
            result: Résultat de l'exécution
            success: Succès de l'exécution
            duration: Durée de l'exécution (secondes)
        """
        if self._log_callback:
            try:
                log = ExecutionLogModel.create_log(
                    agent_id=self.agent_id,
                    task_id=task_data.get("task_id"),
                    level=LogLevel.INFO if success else LogLevel.ERROR,
                    category=LogCategory.AGENT,
                    prompt_sent=json.dumps(task_data.get("payload", {}))[:5000],
                    raw_response=json.dumps(result.get("result", {}))[:5000],
                    tool_output=json.dumps(result.get("tool_output", ""))[:5000],
                    metadata={
                        "success": success,
                        "duration": duration,
                        "retry_count": self.retry_count,
                        "action": task_data.get("action")
                    },
                    tags=["execution", "success" if success else "failed"],
                    duration_ms=int(duration * 1000)
                )
                await self._log_callback(log)
            except Exception as e:
                logger.error(f"Failed to persist log: {str(e)}")
    
    async def _log_error(
        self,
        task_id: str,
        error: str,
        tool_output: Optional[str] = None
    ) -> None:
        """
        Log une erreur.
        
        Args:
            task_id: ID de la tâche
            error: Message d'erreur
            tool_output: Sortie de l'outil (optionnel)
        """
        # Historique mémoire
        entry = {
            "task_id": task_id,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
            "type": "ERROR"
        }
        self.history.append(entry)
        
        # Persistance
        if self._log_callback:
            try:
                log = ExecutionLogModel.create_error_log(
                    agent_id=self.agent_id,
                    error_message=error,
                    task_id=task_id,
                    tool_output=tool_output,
                    metadata={"retry_count": self.retry_count},
                    tags=["error"]
                )
                await self._log_callback(log)
            except Exception as e:
                logger.error(f"Failed to persist error log: {str(e)}")
        
        logger.error(f"Error logged for task {task_id}: {error}")
    
    # =========================================================================
    # ANNULATION ET PAUSE
    # =========================================================================
    
    def cancel(self) -> None:
        """
        Annule l'exécution en cours.
        """
        self._cancelled = True
        self.status = AgentStatus.CANCELLED
        asyncio.create_task(self._emit_event(AgentEvent.CANCELLED, {
            "agent_id": self.agent_id
        }))
        logger.info(f"Agent {self.agent_id} cancelled")
    
    def pause(self) -> None:
        """
        Met l'agent en pause.
        """
        self.status = AgentStatus.PAUSED
        asyncio.create_task(self._emit_event(AgentEvent.PAUSED, {
            "agent_id": self.agent_id
        }))
        logger.info(f"Agent {self.agent_id} paused")
    
    def resume(self) -> None:
        """
        Reprend l'exécution après une pause.
        """
        self.status = AgentStatus.IDLE
        asyncio.create_task(self._emit_event(AgentEvent.RESUMED, {
            "agent_id": self.agent_id
        }))
        logger.info(f"Agent {self.agent_id} resumed")
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    
    def _validate_task_data(self, task_data: Dict[str, Any]) -> None:
        """
        Valide les donnees de la tache.
        
        Args:
            task_data: Donnees a valider
            
        Raises:
            ValueError: Si les donnees sont invalides
        """
        if not isinstance(task_data, dict):
            raise ValueError("task_data must be a dictionary")
        
        required_fields = ["task_id", "action"]
        for field in required_fields:
            if field not in task_data:
                raise ValueError(f"Missing required field: {field}")
        
        if not task_data.get("task_id"):
            raise ValueError("task_id cannot be empty")
        
        if not task_data.get("action"):
            raise ValueError("action cannot be empty")
    
    def _validate_result(self, result: Dict[str, Any]) -> None:
        """
        Valide le resultat de l'execution.
        
        Args:
            result: Resultat a valider
            
        Raises:
            ValueError: Si le resultat est invalide
        """
        if not isinstance(result, dict):
            raise ValueError("Result must be a dictionary")
        
        if "status" not in result:
            raise ValueError("Result missing 'status' field")
        
        if result["status"] not in ["SUCCESS", "FAILED", "CIRCUIT_OPEN"]:
            raise ValueError(f"Invalid status: {result['status']}")
    
    # =========================================================================
    # CIRCUIT BREAKER
    # =========================================================================
    
    def reset_circuit_breaker(self) -> None:
        """
        Reinitialise le circuit breaker.
        """
        self._circuit_breaker_state = False
        self._circuit_breaker_failures = 0
        self.retry_count = 0
        self.status = AgentStatus.IDLE
        
        asyncio.create_task(self._emit_event(AgentEvent.CIRCUIT_CLOSED, {
            "agent_id": self.agent_id
        }))
        
        logger.info(f"Circuit breaker reset for agent {self.agent_id}")
    
    def is_circuit_open(self) -> bool:
        """
        Vérifie si le circuit est ouvert.
        
        Returns:
            bool: True si ouvert
        """
        return self._circuit_breaker_state
    
    # =========================================================================
    # CAPACITES ET STATISTIQUES
    # =========================================================================
    
    def get_capabilities(self) -> List[Dict]:
        """
        Retourne la liste des competences de l'agent.
        
        Returns:
            List[Dict]: Liste des competences avec leurs metadonnees
        """
        return [
            {
                "id": s.skill_id, 
                "name": s.name,
                "description": getattr(s, 'description', 'No description'),
                "input_schema": getattr(s, 'input_schema', None)
            } 
            for s in self.skills
        ]
    
    def health_check(self) -> Dict:
        """
        Verifie l'etat de sante de l'agent.
        
        Returns:
            Dict: Informations de sante de l'agent
        """
        return {
            "status": self.status.value,
            "agent_id": self.agent_id,
            "name": self.name,
            "skills_count": len(self.skills),
            "circuit_breaker_state": self._circuit_breaker_state,
            "circuit_breaker_failures": self._circuit_breaker_failures,
            "execution_count": self.metrics.total_executions,
            "success_rate": self.metrics.success_rate,
            "last_execution": self.metrics.last_execution_time.isoformat() if self.metrics.last_execution_time else None,
            "history_size": len(self.history),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "is_healthy": self.status not in [AgentStatus.FAILED, AgentStatus.CIRCUIT_OPEN],
            "is_cancelled": self._cancelled
        }

    def get_history(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Retourne l'historique des executions.
        
        Args:
            limit: Nombre maximum d'entrees a retourner (optionnel)
            
        Returns:
            List[Dict]: Historique des executions
        """
        if limit:
            return self.history[-limit:]
        return self.history

    def get_performance_stats(self) -> Dict:
        """
        Retourne les statistiques de performance de l'agent.
        
        Returns:
            Dict: Statistiques de performance
        """
        return self.metrics.to_dict()
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================

    def __repr__(self) -> str:
        """
        Representation lisible de l'agent pour le debogage.
        """
        return f"<AbstractAgent(agent_id='{self.agent_id}', name='{self.name}', status='{self.status.value}')>"

    def to_dict(self) -> Dict:
        """
        Convertit l'objet en dictionnaire pour la serialisation.
        
        Returns:
            Dict: Representation dictionnaire de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status.value,
            "skills": [s.skill_id for s in self.skills],
            "history_size": len(self.history),
            "metrics": self.metrics.to_dict(),
            "circuit_breaker_state": self._circuit_breaker_state,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "is_healthy": self.status not in [AgentStatus.FAILED, AgentStatus.CIRCUIT_OPEN],
            "is_cancelled": self._cancelled,
            "task_timeout": self.task_timeout
        }