# src/orchestration/workflow_engine.py

"""
Workflow engine for the Smart Contract Dev Pipeline.
F28 – src/orchestration/workflow_engine.py

Rôle Fonctionnel : Moteur d'execution asynchrone des taches (DAG).
Ce module implemente le moteur d'orchestration du pipeline, responsable de:
- L'execution des taches selon un ordre topologique (DAG)
- La gestion des dependances entre taches
- La paralellisation des taches independantes
- La reprise sur erreur avec retry
- L'integration avec le circuit breaker
- La persistance de l'etat d'execution
- La notification des evenements de progression

Le WorkflowEngine est le cœur orchestrateur du pipeline,
coordonnant l'execution des agents.
"""
from typing import List, Dict, Set, Any, Optional, Tuple, Callable, Awaitable
from collections import deque
from datetime import datetime
import logging
import asyncio
import json
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import TaskExecutionError, CircuitBreakerOpenError
from src.core.models import TaskState
from src.persistence.project_state import ProjectState
from src.communication.message_bus import MessageBus
from src.orchestration.circuit_breaker import CircuitBreaker

# Configuration du logging
logger = logging.getLogger(__name__)


class WorkflowStatus(str, Enum):
    """
    Statuts possibles pour un workflow.
    """
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskExecutionStatus(str, Enum):
    """
    Statuts d'execution d'une tache.
    """
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class TaskExecution:
    """
    Etat d'execution d'une tache.
    
    Attributes:
        task_id (str): Identifiant de la tache
        task_data (Dict): Donnees de la tache
        status (TaskExecutionStatus): Statut d'execution
        dependencies (Set[str]): Dependances
        start_time (Optional[datetime]): Heure de debut
        end_time (Optional[datetime]): Heure de fin
        retry_count (int): Nombre de tentatives
        max_retries (int): Nombre maximum de tentatives
        result (Optional[Dict]): Resultat de l'execution
        error (Optional[str]): Message d'erreur
        attempts (List[Dict]): Historique des tentatives
    """
    task_id: str
    task_data: Dict[str, Any]
    status: TaskExecutionStatus = TaskExecutionStatus.PENDING
    dependencies: Set[str] = field(default_factory=set)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convertit l'execution en dictionnaire."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "dependencies": list(self.dependencies),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "result": self.result,
            "error": self.error,
            "attempts": self.attempts
        }


@dataclass
class WorkflowExecution:
    """
    Etat d'execution d'un workflow.
    
    Attributes:
        workflow_id (str): Identifiant du workflow
        status (WorkflowStatus): Statut du workflow
        tasks (Dict[str, TaskExecution]): Taches du workflow
        start_time (Optional[datetime]): Heure de debut
        end_time (Optional[datetime]): Heure de fin
        current_task (Optional[str]): Tache en cours
        completed_count (int): Nombre de taches terminees
        total_count (int): Nombre total de taches
        error (Optional[str]): Message d'erreur
        metadata (Dict): Metadonnees
    """
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    tasks: Dict[str, TaskExecution] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    current_task: Optional[str] = None
    completed_count: int = 0
    total_count: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit l'execution en dictionnaire."""
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "current_task": self.current_task,
            "completed_count": self.completed_count,
            "total_count": self.total_count,
            "error": self.error,
            "metadata": self.metadata
        }


class WorkflowEngine:
    """
    Moteur d'execution de DAG de taches.
    
    Ce moteur orchestre l'execution des taches selon un ordre
    topologique, avec support de la paralellisation, des retries
    et de la persistance.
    
    Attributes:
        bus (Optional[MessageBus]): Bus de messages pour les notifications
        agents (Dict[str, Any]): Agents disponibles
        state_manager (Optional[ProjectState]): Gestionnaire d'etat
        circuit_breaker (Optional[CircuitBreaker]): Circuit breaker
        max_parallel (int): Nombre maximum de taches paralleles
        execution (Optional[WorkflowExecution]): Execution en cours
        _execution_history (List[WorkflowExecution]): Historique des executions
        _listeners (List[Callable]): Listeners d'evenements
        _running (bool): Indique si le moteur est en cours d'execution
    """
    
    def __init__(
        self,
        bus: Optional[MessageBus] = None,
        agents: Optional[Dict[str, Any]] = None,
        state_manager: Optional[ProjectState] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_parallel: int = 4,
        default_max_retries: int = 3
    ):
        """
        Initialise le moteur de workflow.
        
        Args:
            bus: Bus de messages pour les notifications
            agents: Agents disponibles
            state_manager: Gestionnaire d'etat pour la persistance
            circuit_breaker: Circuit breaker pour la protection
            max_parallel: Nombre maximum de taches paralleles
            default_max_retries: Nombre maximum de tentatives par defaut
        """
        self.bus = bus
        self.agents = agents or {}
        self.state_manager = state_manager
        self.circuit_breaker = circuit_breaker
        self.max_parallel = max_parallel
        self.default_max_retries = default_max_retries
        
        self.execution: Optional[WorkflowExecution] = None
        self._execution_history: List[WorkflowExecution] = []
        self._listeners: List[Callable[[str, Dict], Awaitable[None]]] = []
        self._running = False
        self._stop_requested = False
        
        # Verrous
        self._task_lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()
        
        logger.info("WorkflowEngine initialized")
    
    # =========================================================================
    # GESTION DES TACHES
    # =========================================================================
    
    def add_task(
        self,
        task_id: str,
        agent_id: str,
        action: str,
        parameters: Optional[Dict] = None,
        dependencies: Optional[List[str]] = None,
        max_retries: Optional[int] = None,
        priority: int = 5,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Ajoute une tache au workflow.
        
        Args:
            task_id: Identifiant de la tache
            agent_id: ID de l'agent qui executera la tache
            action: Action a executer
            parameters: Parametres de la tache
            dependencies: IDs des taches dependantes
            max_retries: Nombre maximum de tentatives
            priority: Priorite (1-10)
            metadata: Metadonnees supplementaires
        """
        if not self.execution:
            raise ValueError("No execution context. Call start() first.")
        
        if task_id in self.execution.tasks:
            raise ValueError(f"Task {task_id} already exists")
        
        # Creation de la tache
        task_data = {
            "id": task_id,
            "agent_id": agent_id,
            "action": action,
            "parameters": parameters or {},
            "priority": priority,
            "metadata": metadata or {}
        }
        
        task_exec = TaskExecution(
            task_id=task_id,
            task_data=task_data,
            dependencies=set(dependencies or []),
            max_retries=max_retries or self.default_max_retries
        )
        
        self.execution.tasks[task_id] = task_exec
        self.execution.total_count += 1
        
        logger.debug(f"Task added: {task_id} (agent={agent_id}, action={action})")
    
    def add_tasks(self, tasks: List[Dict]) -> None:
        """
        Ajoute plusieurs taches.
        
        Args:
            tasks: Liste des taches a ajouter
        """
        for task in tasks:
            self.add_task(
                task_id=task.get("id"),
                agent_id=task.get("agent_id"),
                action=task.get("action"),
                parameters=task.get("parameters"),
                dependencies=task.get("dependencies"),
                max_retries=task.get("max_retries"),
                priority=task.get("priority", 5),
                metadata=task.get("metadata")
            )
    
    def get_task(self, task_id: str) -> Optional[TaskExecution]:
        """
        Recupere une tache.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            Optional[TaskExecution]: Tache ou None
        """
        if not self.execution:
            return None
        return self.execution.tasks.get(task_id)
    
    def get_tasks_by_status(self, status: TaskExecutionStatus) -> List[TaskExecution]:
        """
        Recupere les taches par statut.
        
        Args:
            status: Statut a filtrer
            
        Returns:
            List[TaskExecution]: Taches avec le statut
        """
        if not self.execution:
            return []
        return [
            t for t in self.execution.tasks.values()
            if t.status == status
        ]
    
    # =========================================================================
    # EXECUTION
    # =========================================================================
    
    async def start(
        self,
        workflow_id: str,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Demarre l'execution du workflow.
        
        Args:
            workflow_id: Identifiant du workflow
            metadata: Metadonnees du workflow
            
        Returns:
            str: ID du workflow
            
        Raises:
            ValueError: Si le workflow est deja en cours
        """
        if self._running:
            raise ValueError("Workflow already running")
        
        self._running = True
        self._stop_requested = False
        
        # Initialisation de l'execution
        self.execution = WorkflowExecution(
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            metadata=metadata or {}
        )
        
        logger.info(f"Workflow started: {workflow_id}")
        
        # Notification de demarrage
        await self._notify("workflow_started", {
            "workflow_id": workflow_id,
            "total_tasks": self.execution.total_count
        })
        
        # Execution du pipeline
        try:
            await self._run_pipeline()
            
            # Mise a jour du statut
            if self._stop_requested:
                self.execution.status = WorkflowStatus.CANCELLED
            elif all(t.status == TaskExecutionStatus.COMPLETED for t in self.execution.tasks.values()):
                self.execution.status = WorkflowStatus.COMPLETED
            else:
                self.execution.status = WorkflowStatus.FAILED
            
        except Exception as e:
            self.execution.status = WorkflowStatus.FAILED
            self.execution.error = str(e)
            logger.error(f"Workflow failed: {str(e)}")
            raise
        
        finally:
            self.execution.end_time = datetime.utcnow()
            self._running = False
            self._execution_history.append(self.execution)
            
            # Notification de fin
            await self._notify("workflow_completed", {
                "workflow_id": workflow_id,
                "status": self.execution.status.value,
                "completed_tasks": self.execution.completed_count,
                "total_tasks": self.execution.total_count
            })
            
            logger.info(f"Workflow completed: {workflow_id} (status={self.execution.status.value})")
        
        return workflow_id
    
    async def stop(self) -> None:
        """
        Demande l'arret du workflow.
        """
        self._stop_requested = True
        logger.info("Stop requested for workflow")
    
    async def _run_pipeline(self) -> None:
        """
        Execute le pipeline complet.
        """
        if not self.execution:
            raise ValueError("No execution context")
        
        # Resolution de l'ordre topologique
        order = self._resolve_order()
        
        if not order:
            logger.warning("No tasks to execute")
            return
        
        logger.info(f"Executing {len(order)} tasks in topological order")
        
        # Execution des taches en parallele
        semaphore = asyncio.Semaphore(self.max_parallel)
        
        # File d'attente des taches pretes
        ready_queue = deque()
        
        # Fonction pour executer une tache
        async def execute_task_wrapper(task_id: str):
            async with semaphore:
                if self._stop_requested:
                    return
                await self._execute_task(task_id)
        
        # Tant qu'il reste des taches a executer
        while self.execution.completed_count < self.execution.total_count and not self._stop_requested:
            # Trouver les taches pretes
            pending_tasks = self.get_tasks_by_status(TaskExecutionStatus.PENDING)
            ready_tasks = []
            
            for task in pending_tasks:
                if self._is_ready(task):
                    task.status = TaskExecutionStatus.READY
                    ready_tasks.append(task.task_id)
            
            # Si aucune tache prete, verifier les bloquees
            if not ready_tasks:
                blocked_tasks = self.get_tasks_by_status(TaskExecutionStatus.BLOCKED)
                if blocked_tasks:
                    # Verifier si les dependances sont resolues
                    for task in blocked_tasks:
                        if self._is_ready(task):
                            task.status = TaskExecutionStatus.READY
                            ready_tasks.append(task.task_id)
                
                # Si toujours aucune tache prete, verifier les echecs
                if not ready_tasks:
                    failed_tasks = self.get_tasks_by_status(TaskExecutionStatus.FAILED)
                    if failed_tasks:
                        # Gestion des echecs
                        for task in failed_tasks:
                            if task.retry_count < task.max_retries:
                                task.status = TaskExecutionStatus.RETRYING
                                ready_tasks.append(task.task_id)
                            else:
                                # Tache en echec definitif
                                pass
                    
                    # Si toujours aucune tache, il y a un blocage
                    if not ready_tasks:
                        logger.error("Pipeline blocked: no tasks ready")
                        break
            
            # Execution des taches pretes
            if ready_tasks:
                tasks_to_execute = ready_tasks[:self.max_parallel]
                await asyncio.gather(*[
                    execute_task_wrapper(task_id)
                    for task_id in tasks_to_execute
                ])
            else:
                # Petit delai pour eviter une boucle vide
                await asyncio.sleep(0.1)
        
        # Verification finale
        failed_tasks = self.get_tasks_by_status(TaskExecutionStatus.FAILED)
        if failed_tasks and not self._stop_requested:
            logger.warning(f"Workflow completed with {len(failed_tasks)} failed tasks")
    
    async def _execute_task(self, task_id: str) -> None:
        """
        Execute une tache individuelle.
        
        Args:
            task_id: ID de la tache
        """
        task = self.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        
        # Verification du circuit breaker
        if self.circuit_breaker and self.circuit_breaker.is_open():
            raise CircuitBreakerOpenError(f"Circuit breaker open for task {task_id}")
        
        # Mise a jour du statut
        task.status = TaskExecutionStatus.RUNNING
        task.start_time = datetime.utcnow()
        self.execution.current_task = task_id
        
        logger.info(f"Executing task: {task_id} (attempt {task.retry_count + 1})")
        
        # Notification de debut de tache
        await self._notify("task_started", {
            "task_id": task_id,
            "attempt": task.retry_count + 1
        })
        
        try:
            # Recuperation de l'agent
            agent_id = task.task_data.get("agent_id")
            agent = self.agents.get(agent_id)
            
            if not agent:
                raise ValueError(f"Agent '{agent_id}' not found")
            
            # Execution de la tache
            result = await agent.execute_task(task.task_data)
            
            # Enregistrement du resultat
            task.result = result
            task.status = TaskExecutionStatus.COMPLETED
            task.end_time = datetime.utcnow()
            self.execution.completed_count += 1
            
            # Sauvegarde si state_manager disponible
            if self.state_manager:
                await self._save_task_result(task)
            
            logger.info(f"Task completed: {task_id}")
            
            # Notification de fin de tache
            await self._notify("task_completed", {
                "task_id": task_id,
                "status": "SUCCESS",
                "duration": (task.end_time - task.start_time).total_seconds()
            })
            
        except Exception as e:
            task.error = str(e)
            task.retry_count += 1
            
            # Enregistrement de la tentative
            task.attempts.append({
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "retry_count": task.retry_count
            })
            
            # Verifier si on peut reessayer
            if task.retry_count < task.max_retries:
                task.status = TaskExecutionStatus.RETRYING
                logger.warning(f"Task {task_id} failed, retrying ({task.retry_count}/{task.max_retries})")
                
                # Notification de retry
                await self._notify("task_retry", {
                    "task_id": task_id,
                    "attempt": task.retry_count,
                    "error": str(e)
                })
                
                # Delai avant retry (backoff exponentiel)
                delay = 2 ** task.retry_count
                await asyncio.sleep(delay)
                
                # Remettre en attente pour reessai
                task.status = TaskExecutionStatus.PENDING
            else:
                task.status = TaskExecutionStatus.FAILED
                logger.error(f"Task {task_id} failed after {task.max_retries} attempts: {str(e)}")
                
                # Notification d'echec
                await self._notify("task_failed", {
                    "task_id": task_id,
                    "error": str(e),
                    "attempts": task.retry_count
                })
                
                # Sauvegarde de l'erreur
                if self.state_manager:
                    await self._save_task_error(task)
    
    def _resolve_order(self) -> List[str]:
        """
        Tri topologique des taches (algorithme de Kahn).
        
        Returns:
            List[str]: IDs des taches dans l'ordre d'execution
            
        Raises:
            ValueError: Si un cycle est detecte
        """
        if not self.execution:
            return []
        
        # Construction du graphe
        graph = {}
        in_degree = {}
        
        for task_id, task in self.execution.tasks.items():
            graph[task_id] = set(task.dependencies)
            in_degree[task_id] = len(task.dependencies)
        
        # File des taches sans dependances
        queue = deque([t for t, deg in in_degree.items() if deg == 0])
        result = []
        
        while queue:
            task_id = queue.popleft()
            result.append(task_id)
            
            # Mise a jour des dependances
            for other_id, deps in graph.items():
                if task_id in deps:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)
        
        # Verification de cycle
        if len(result) != len(self.execution.tasks):
            raise ValueError("Cycle detected in DAG")
        
        return result
    
    def _is_ready(self, task: TaskExecution) -> bool:
        """
        Verifie si les dependances d'une tache sont satisfaites.
        
        Args:
            task: Tache a verifier
            
        Returns:
            bool: True si la tache est prete
        """
        if task.status not in [TaskExecutionStatus.PENDING, TaskExecutionStatus.BLOCKED]:
            return False
        
        # Verifier que toutes les dependances sont terminees
        for dep_id in task.dependencies:
            dep = self.get_task(dep_id)
            if not dep:
                return False
            if dep.status != TaskExecutionStatus.COMPLETED:
                return False
        
        return True
    
    # =========================================================================
    # PERSISTANCE
    # =========================================================================
    
    async def _save_task_result(self, task: TaskExecution) -> None:
        """
        Sauvegarde le resultat d'une tache.
        
        Args:
            task: Tache terminee
        """
        if not self.state_manager:
            return
        
        try:
            from src.core.models import TaskResultModel
            
            result = TaskResultModel(
                task_id=task.task_id,
                sprint_id=self.execution.workflow_id,
                agent_id=task.task_data.get("agent_id"),
                status="SUCCESS",
                output=task.result,
                duration=(task.end_time - task.start_time).total_seconds() if task.end_time and task.start_time else None
            )
            
            await self.state_manager.save_task_result(result)
            
        except Exception as e:
            logger.error(f"Failed to save task result: {str(e)}")
    
    async def _save_task_error(self, task: TaskExecution) -> None:
        """
        Sauvegarde l'erreur d'une tache.
        
        Args:
            task: Tache en echec
        """
        if not self.state_manager:
            return
        
        try:
            from src.core.models import TaskResultModel
            
            result = TaskResultModel(
                task_id=task.task_id,
                sprint_id=self.execution.workflow_id,
                agent_id=task.task_data.get("agent_id"),
                status="FAILED",
                error=task.error,
                duration=(task.end_time - task.start_time).total_seconds() if task.end_time and task.start_time else None
            )
            
            await self.state_manager.save_task_result(result)
            
        except Exception as e:
            logger.error(f"Failed to save task error: {str(e)}")
    
    # =========================================================================
    # EVENEMENTS ET NOTIFICATIONS
    # =========================================================================
    
    def add_listener(self, listener: Callable[[str, Dict], Awaitable[None]]) -> None:
        """
        Ajoute un listener d'evenements.
        
        Args:
            listener: Fonction de callback
        """
        self._listeners.append(listener)
    
    def remove_listener(self, listener: Callable[[str, Dict], Awaitable[None]]) -> None:
        """
        Supprime un listener d'evenements.
        
        Args:
            listener: Fonction de callback
        """
        if listener in self._listeners:
            self._listeners.remove(listener)
    
    async def _notify(self, event_type: str, data: Dict) -> None:
        """
        Notifie les listeners et le bus de messages.
        
        Args:
            event_type: Type d'evenement
            data: Donnees de l'evenement
        """
        # Notification des listeners
        for listener in self._listeners:
            try:
                await listener(event_type, data)
            except Exception as e:
                logger.error(f"Listener error: {str(e)}")
        
        # Notification via le bus
        if self.bus:
            try:
                from src.communication.message_models import EventMessage
                
                event_msg = EventMessage(
                    sender="workflow_engine",
                    recipient=None,
                    payload={
                        "event_type": event_type,
                        "data": data,
                        "workflow_id": self.execution.workflow_id if self.execution else None
                    }
                )
                await self.bus.publish(f"workflow.events", event_msg)
            except Exception as e:
                logger.error(f"Failed to send event via bus: {str(e)}")
    
    # =========================================================================
    # STATISTIQUES
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """
        Retourne le statut du workflow.
        
        Returns:
            Dict: Statut detaille
        """
        if not self.execution:
            return {"status": "idle"}
        
        return {
            "workflow_id": self.execution.workflow_id,
            "status": self.execution.status.value,
            "running": self._running,
            "completed_tasks": self.execution.completed_count,
            "total_tasks": self.execution.total_count,
            "progress": self.execution.completed_count / self.execution.total_count if self.execution.total_count > 0 else 0,
            "current_task": self.execution.current_task,
            "start_time": self.execution.start_time.isoformat() if self.execution.start_time else None,
            "end_time": self.execution.end_time.isoformat() if self.execution.end_time else None,
            "error": self.execution.error
        }
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """
        Retourne le statut d'une tache.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            Optional[Dict]: Statut de la tache
        """
        task = self.get_task(task_id)
        if not task:
            return None
        
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "start_time": task.start_time.isoformat() if task.start_time else None,
            "end_time": task.end_time.isoformat() if task.end_time else None,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "has_result": task.result is not None,
            "has_error": task.error is not None
        }
    
    def get_execution_history(self, limit: int = 10) -> List[Dict]:
        """
        Recupere l'historique des executions.
        
        Args:
            limit: Nombre maximum d'executions
            
        Returns:
            List[Dict]: Historique des executions
        """
        return [e.to_dict() for e in self._execution_history[-limit:]]
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        if self.execution:
            return f"<WorkflowEngine(status={self.execution.status.value}, tasks={self.execution.completed_count}/{self.execution.total_count})>"
        return "<WorkflowEngine(idle)>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le moteur en dictionnaire.
        
        Returns:
            Dict: Representation
        """
        return {
            "running": self._running,
            "max_parallel": self.max_parallel,
            "default_max_retries": self.default_max_retries,
            "agents_available": len(self.agents),
            "status": self.get_status()
        }