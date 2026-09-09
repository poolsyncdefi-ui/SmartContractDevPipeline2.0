# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Abstract Agent
# ==============================================================================
# Fichier: src/agents/base/abstract_agent.py
# Description: Classe de base abstraite définissant l'interface commune pour
#              tous les agents du pipeline avec gestion du circuit breaker,
#              du RAG, de la validation et du monitoring.
#              Version refactorisée avec intégration des nouveaux modules système.
# ==============================================================================

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime, timezone
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
from src.core.status_manager import StatusManager, status_manager, normalize_status
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy, RetryCancelledError
from src.core.intelligent_circuit_breaker import IntelligentCircuitBreaker, CircuitBreakerConfig
from src.core.contract_validator import ContractValidator, validate_contract
from src.models.execution_log import ExecutionLogModel

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
        self.average_duration = self.total_duration / self.total_executions if self.total_executions > 0 else 0.0
        self.success_rate = self.successful_executions / self.total_executions if self.total_executions > 0 else 0.0
        
        now_utc = datetime.now(timezone.utc)
        self.last_execution_time = now_utc
        if not self.first_execution_time:
            self.first_execution_time = now_utc
        
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
            "min_duration": self.min_duration if self.min_duration != float('inf') else 0.0,
            "total_retries": self.total_retries,
            "success_rate": self.success_rate,
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
            "first_execution_time": self.first_execution_time.isoformat() if self.first_execution_time else None,
            "skills_used": self.skills_used
        }


class AbstractAgent(ABC):
    """
    Classe de base abstraite pour tous les agents du pipeline.
    
    Cette classe fournit l'infrastructure commune pour tous les agents,
    incluant:
    - Gestion des compétences (skills)
    - Historique d'exécution
    - Circuit breaker pour éviter les boucles infinies
    - Support RAG pour la génération augmentée par récupération
    - Validation des entrées et sorties
    - Monitoring et health checks
    - Métriques de performance
    - Événements et notifications
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str,
        skills: Optional[List[BaseSkill]] = None,
        llm_client=None,
        knowledge_base=None,
        max_retries: int = 3,
        task_timeout: Optional[int] = None,
        log_callback: Optional[Callable] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None
    ):
        """
        Initialise un nouvel agent.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom descriptif de l'agent
            skills: Liste initiale des compétences (optionnelle)
            llm_client: Client LLM pour les appels IA (optionnel)
            knowledge_base: Base de connaissances pour le RAG (optionnel)
            max_retries: Nombre maximum de tentatives (défaut: 3)
            task_timeout: Timeout par tâche en secondes (optionnel)
            log_callback: Callback pour la persistance des logs (optionnel)
            circuit_breaker_config: Configuration du circuit breaker (optionnel)
        """
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
        
        # Circuit breaker intelligent
        self.circuit_breaker = IntelligentCircuitBreaker(
            config=circuit_breaker_config or CircuitBreakerConfig(
                failure_threshold=max_retries * 2,
                recovery_timeout=60,
                name=f"agent_{agent_id}"
            )
        )
        
        # Système de retry adaptatif
        self.retry_handler = AdaptiveRetry(
            base_delay=1.0,
            max_delay=60.0,
            max_retries=max_retries,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=True,
            retryable_exceptions=(PipelineError, LLMError, CircuitBreakerOpenError)
        )
        
        # Logger structuré
        self.logger = StructuredLogger(
            component_name=name,
            log_level=LogLevel.INFO
        )
        self.logger.set_context(agent_id=agent_id)
        
        # Métriques
        self.metrics = AgentMetrics()
        
        # Événements
        self._event_listeners: List[Callable[[AgentEvent, Dict], Awaitable[None]]] = []
        
        # Verrouillage
        self._execution_lock = asyncio.Lock()
        
        # Callback de log
        self._log_callback = log_callback
        
        # État d'annulation
        self._cancelled = False
        
        # Validation du contrat
        self._validate_contract()
        
        logger.info(f"Agent initialized: {agent_id} ({name})")
    
    def _validate_contract(self) -> None:
        """
        Valide que l'agent implémente bien le contrat attendu.
        """
        # Vérifier que la méthode execute_task est implémentée
        if not ContractValidator.validate_method_exists(self, 'execute_task'):
            raise AttributeError(
                f"Agent {self.agent_id} must implement execute_task method"
            )
    
    # =========================================================================
    # MÉTHODES ABSTRAITES
    # =========================================================================
    
    @abstractmethod
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute une tâche spécifique.
        
        Cette méthode doit être implémentée par chaque type d'agent.
        """
        pass
    
    # =========================================================================
    # EXÉCUTION AVEC CIRCUIT BREAKER
    # =========================================================================
    
    async def execute_with_circuit_breaker(
        self,
        task_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Exécute une tâche avec protection du circuit breaker.
        """
        async with self._execution_lock:
            if self._cancelled:
                self.logger.log_warning("Task cancelled before execution", "task_cancelled")
                return {
                    "status": normalize_status("cancelled"),
                    "error": "Task cancelled",
                    "retry_count": 0,
                    "duration": 0.0
                }
            
            start_time = datetime.now(timezone.utc)
            self.status = AgentStatus.RUNNING
            self.retry_count = 0
            self.logger.set_context(task_id=task_data.get("task_id"))
            
            # Vérification du circuit breaker
            circuit_status = self.circuit_breaker.get_status()
            if circuit_status["state"] == "open":
                logger.warning(f"Circuit breaker open for agent {self.agent_id}")
                self.status = AgentStatus.CIRCUIT_OPEN
                await self._emit_event(AgentEvent.CIRCUIT_OPENED, {
                    "failures": circuit_status["failure_count"],
                    "threshold": circuit_status.get("config", {}).get("failure_threshold", 5)
                })
                return {
                    "status": normalize_status("circuit_broken"),
                    "error": "Circuit breaker is open. Please reset or wait.",
                    "retry_count": self.retry_count,
                    "duration": (datetime.now(timezone.utc) - start_time).total_seconds()
                }
            
            # Notification de début
            await self._emit_event(AgentEvent.STARTED, {
                "task_id": task_data.get("task_id"),
                "action": task_data.get("action")
            })
            
            # Récupération des IDs des compétences utilisées
            skill_ids = [s.skill_id for s in self.skills]
            
            # Validation des entrées
            try:
                self._validate_task_data(task_data)
            except ValueError as e:
                self.logger.log_error("Task data validation failed", e, task_id=task_data.get("task_id"))
                return {
                    "status": normalize_status("failed"),
                    "error": str(e),
                    "retry_count": self.retry_count,
                    "duration": (datetime.now(timezone.utc) - start_time).total_seconds()
                }
            
            # Exécution de la tâche avec retry adaptatif
            try:
                result = await self.retry_handler.execute_with_retry(
                    self._execute_with_timeout,
                    task_data,
                    max_retries=self.max_retries
                )
                
                # Succès
                self.circuit_breaker._record_success()
                self.status = AgentStatus.COMPLETED
                
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                
                # Mise à jour des métriques
                self.metrics.update(duration, True, self.retry_count, skill_ids)
                
                # Ajout des métriques au résultat
                result.update({
                    "retry_count": self.retry_count,
                    "duration": duration,
                    "execution_count": self.metrics.total_executions
                })
                
                # Logging
                self.logger.log_info(
                    f"Task completed successfully",
                    "task_completed",
                    duration=duration,
                    retry_count=self.retry_count,
                    skill_ids=skill_ids
                )
                
                # Notification de succès
                await self._emit_event(AgentEvent.COMPLETED, {
                    "task_id": task_data.get("task_id"),
                    "duration": duration,
                    "result": result
                })
                
                logger.info(f"Task executed successfully by {self.agent_id} in {duration:.2f}s")
                return result
                
            except RetryCancelledError as e:
                self.logger.log_warning(f"Task cancelled during retry: {str(e)}", "task_cancelled")
                return {
                    "status": normalize_status("cancelled"),
                    "error": str(e),
                    "retry_count": self.retry_count,
                    "duration": (datetime.now(timezone.utc) - start_time).total_seconds()
                }
                
            except (PipelineError, LLMError, TaskExecutionError) as e:
                # Enregistrer l'échec dans le circuit breaker
                await self.circuit_breaker._record_failure(e)
                
                self.logger.log_error(f"Task failed: {str(e)}", e, task_id=task_data.get("task_id"))
                
                # Si le circuit breaker est ouvert, retourner une erreur spécifique
                if self.circuit_breaker.state == "open":
                    self.status = AgentStatus.CIRCUIT_OPEN
                    await self._emit_event(AgentEvent.CIRCUIT_OPENED, {
                        "reason": "max_retries",
                        "failures": self.circuit_breaker.failure_count
                    })
                    return {
                        "status": normalize_status("circuit_broken"),
                        "error": f"Circuit breaker open: {str(e)}",
                        "retry_count": self.retry_count,
                        "duration": (datetime.now(timezone.utc) - start_time).total_seconds(),
                        "last_error": str(e)
                    }
                
                self.status = AgentStatus.FAILED
                return {
                    "status": normalize_status("failed"),
                    "error": str(e),
                    "retry_count": self.retry_count,
                    "duration": (datetime.now(timezone.utc) - start_time).total_seconds(),
                    "last_error": str(e)
                }
                
            except Exception as e:
                self.logger.log_error(f"Unexpected error: {str(e)}", e, task_id=task_data.get("task_id"))
                self.status = AgentStatus.FAILED
                
                await self._emit_event(AgentEvent.FAILED, {
                    "task_id": task_data.get("task_id"),
                    "error": str(e)
                })
                
                return {
                    "status": normalize_status("failed"),
                    "error": f"Unexpected error: {str(e)}",
                    "retry_count": self.retry_count,
                    "duration": (datetime.now(timezone.utc) - start_time).total_seconds()
                }
            
            finally:
                # Réinitialiser le contexte du logger
                self.logger.clear_context()
    
    async def _execute_with_timeout(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute la tâche avec timeout.
        
        Args:
            task_data: Données de la tâche
            
        Returns:
            Dict[str, Any]: Résultat de l'exécution
            
        Raises:
            asyncio.TimeoutError: Si le timeout est dépassé
        """
        if self.task_timeout:
            return await asyncio.wait_for(
                self.execute_task(task_data),
                timeout=self.task_timeout
            )
        return await self.execute_task(task_data)
    
    # =========================================================================
    # GESTION DES COMPÉTENCES
    # =========================================================================
    
    def attach_skill(self, skill: BaseSkill) -> None:
        """
        Ajoute une compétence à l'agent avec validation.
        """
        if not isinstance(skill, BaseSkill):
            raise ValueError(f"Skill must be a BaseSkill instance, got {type(skill)}")
        
        if any(s.skill_id == skill.skill_id for s in self.skills):
            logger.warning(f"Skill {skill.skill_id} already attached to agent {self.agent_id}")
            return
        
        self.skills.append(skill)
        logger.info(f"Skill {skill.skill_id} attached to agent {self.agent_id}")
        
        asyncio.create_task(self._emit_event(AgentEvent.SKILL_ATTACHED, {
            "skill_id": skill.skill_id,
            "skill_name": skill.name
        }))
    
    def remove_skill(self, skill_id: str) -> bool:
        """
        Supprime une compétence de l'agent.
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
        Récupère une compétence par son ID.
        """
        for skill in self.skills:
            if skill.skill_id == skill_id:
                return skill
        return None
    
    def has_skill(self, skill_id: str) -> bool:
        """
        Vérifie si une compétence est présente.
        """
        return any(s.skill_id == skill_id for s in self.skills)
    
    # =========================================================================
    # GESTION DES ÉVÉNEMENTS
    # =========================================================================
    
    def add_event_listener(
        self,
        listener: Callable[[AgentEvent, Dict], Awaitable[None]]
    ) -> None:
        """
        Ajoute un listener d'événements.
        """
        self._event_listeners.append(listener)
    
    def remove_event_listener(
        self,
        listener: Callable[[AgentEvent, Dict], Awaitable[None]]
    ) -> None:
        """
        Supprime un listener d'événements.
        """
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)
    
    async def _emit_event(self, event_type: AgentEvent, data: Dict) -> None:
        """
        Émet un événement à tous les listeners.
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
        Log l'exécution d'une tâche via le logger structuré.
        """
        if not self._log_callback:
            return
        
        try:
            def safe_serialize(data: Any, max_len: int = 5000) -> str:
                try:
                    if data is None:
                        return ""
                    if isinstance(data, (str, int, float, bool)):
                        return str(data)
                    return json.dumps(data, default=str)[:max_len]
                except Exception:
                    return str(data)[:max_len]
            
            # Utiliser le logger structuré
            log_data = {
                "agent_id": self.agent_id,
                "task_id": task_data.get("task_id"),
                "success": success,
                "duration": duration,
                "retry_count": self.retry_count,
                "action": task_data.get("action")
            }
            
            if success:
                self.logger.log_info(
                    f"Task executed successfully",
                    "execution",
                    **log_data,
                    result_preview=safe_serialize(result.get("result", {}))
                )
            else:
                self.logger.log_error(
                    f"Task execution failed",
                    error=None,
                    task_id=task_data.get("task_id"),
                    **log_data,
                    error_message=result.get("error", "Unknown error")
                )
            
        except Exception as e:
            logger.error(f"Failed to persist log: {str(e)}")
    
    async def _log_error(
        self,
        task_id: str,
        error: str,
        tool_output: Optional[str] = None
    ) -> None:
        """
        Log une erreur via le logger structuré.
        """
        entry = {
            "task_id": task_id,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "ERROR"
        }
        self.history.append(entry)
        
        # Utiliser le logger structuré
        self.logger.log_error(
            f"Error logged for task {task_id}: {error}",
            error=None,
            task_id=task_id,
            tool_output=tool_output,
            retry_count=self.retry_count
        )
        
        logger.error(f"Error logged for task {task_id}: {error}")
    
    # =========================================================================
    # ANNULATION ET PAUSE
    # =========================================================================
    
    def cancel(self) -> None:
        """
        Annule l'exécution en cours.
        """
        self._cancelled = True
        self.retry_handler.cancel()
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
        Valide les données de la tâche.
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
        Valide le résultat de l'exécution.
        """
        if not isinstance(result, dict):
            raise ValueError("Result must be a dictionary")
        
        if "status" not in result:
            raise ValueError("Result missing 'status' field")
        
        # Utiliser StatusManager pour valider le statut
        if not status_manager.validate_status(result["status"], {"success", "failed", "circuit_broken", "cancelled"}):
            raise ValueError(f"Invalid status: {result['status']}")
    
    # =========================================================================
    # CIRCUIT BREAKER (CONTRÔLE)
    # =========================================================================
    
    async def reset_circuit_breaker(self) -> None:
        """
        Réinitialise le circuit breaker.
        """
        await self.circuit_breaker.reset()
        self.status = AgentStatus.IDLE
        
        asyncio.create_task(self._emit_event(AgentEvent.CIRCUIT_CLOSED, {
            "agent_id": self.agent_id
        }))
        
        logger.info(f"Circuit breaker reset for agent {self.agent_id}")
    
    async def is_circuit_open(self) -> bool:
        """
        Vérifie si le circuit est ouvert.
        """
        return self.circuit_breaker.state == "open"
    
    # =========================================================================
    # CAPACITÉS ET STATISTIQUES
    # =========================================================================
    
    def get_capabilities(self) -> List[Dict]:
        """
        Retourne la liste des compétences de l'agent.
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
        Vérifie l'état de santé de l'agent.
        """
        circuit_status = self.circuit_breaker.get_status()
        
        return {
            "status": self.status.value,
            "agent_id": self.agent_id,
            "name": self.name,
            "skills_count": len(self.skills),
            "circuit_breaker_state": circuit_status["state"],
            "circuit_breaker_failures": circuit_status["failure_count"],
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
        Retourne l'historique des exécutions.
        """
        if limit:
            return self.history[-limit:]
        return self.history

    def get_performance_stats(self) -> Dict:
        """
        Retourne les statistiques de performance de l'agent.
        """
        return self.metrics.to_dict()
    
    def get_logger(self) -> StructuredLogger:
        """
        Retourne le logger structuré de l'agent.
        """
        return self.logger
    
    # =========================================================================
    # REPRÉSENTATION
    # =========================================================================

    def __repr__(self) -> str:
        return f"<AbstractAgent(agent_id='{self.agent_id}', name='{self.name}', status='{self.status.value}')>"

    def to_dict(self) -> Dict:
        """
        Convertit l'objet en dictionnaire pour la sérialisation.
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status.value,
            "skills": [s.skill_id for s in self.skills],
            "history_size": len(self.history),
            "metrics": self.metrics.to_dict(),
            "circuit_breaker_state": self.circuit_breaker.state,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "is_healthy": self.status not in [AgentStatus.FAILED, AgentStatus.CIRCUIT_OPEN],
            "is_cancelled": self._cancelled,
            "task_timeout": self.task_timeout
        }