# src/orchestration/workflow_engine.py

"""
Workflow engine for the Smart Contract Dev Pipeline.
F28 – src/orchestration/workflow_engine.py

Role Fonctionnel : Moteur d'execution asynchrone des taches (DAG).
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
Version refactorisée avec intégration des nouveaux modules système.
"""
from typing import List, Dict, Set, Any, Optional, Tuple, Callable, Awaitable
from collections import deque
from datetime import datetime, timezone
import logging
import asyncio
import json
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import TaskExecutionError, CircuitBreakerOpenError
from src.core.models import TaskResult
from src.core.status_manager import normalize_status, status_manager, StatusManager
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.intelligent_cache import IntelligentCache, CacheStrategy
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy, RetryCancelledError
from src.core.contract_validator import ContractValidator, validate_contract
from src.persistence.project_state import ProjectState
from src.communication.message_bus import MessageBus
from src.orchestration.circuit_breaker import CircuitBreaker, CircuitBreakerState

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
        _logger (StructuredLogger): Logger structure
        _cache (IntelligentCache): Cache intelligent
        _retry_handler (AdaptiveRetry): Systeme de retry
    """

    def __init__(
        self,
        bus: Optional[MessageBus] = None,
        agents: Optional[Dict[str, Any]] = None,
        state_manager: Optional[ProjectState] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_parallel: int = 4,
        default_max_retries: int = 3,
        cache_enabled: bool = True,
        cache_ttl: int = 300
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
            cache_enabled: Activer le cache des executions
            cache_ttl: Duree de vie du cache en secondes
        """
        self.bus = bus
        self.agents = agents or {}
        self.state_manager = state_manager
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            max_retries=default_max_retries,
            name="workflow_engine"
        )
        self.max_parallel = max_parallel
        self.default_max_retries = default_max_retries

        self.execution: Optional[WorkflowExecution] = None
        self._execution_history: List[WorkflowExecution] = []
        self._listeners: List[Callable[[str, Dict], Awaitable[None]]] = []
        self._running = False
        self._stop_requested = False

        # Verrous et files
        self._task_lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()
        self._ready_queue: Optional[asyncio.Queue] = None

        # Logger structuré
        self._logger = StructuredLogger(
            component_name="WorkflowEngine",
            log_level=LogLevel.INFO
        )

        # Cache intelligent
        self._cache = IntelligentCache(
            default_ttl=cache_ttl,
            max_entries=500,
            strategy=CacheStrategy.ADAPTIVE,
            enable_metrics=True
        )
        if cache_enabled:
            self._cache.start()

        # Système de retry adaptatif
        self._retry_handler = AdaptiveRetry(
            base_delay=1.0,
            max_delay=60.0,
            max_retries=default_max_retries,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=True,
            retryable_exceptions=(TaskExecutionError, CircuitBreakerOpenError)
        )

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
            self.execution = WorkflowExecution(
                workflow_id="default_workflow",
                status=WorkflowStatus.PENDING,
                metadata={}
            )

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

        self._logger.log_debug(
            f"Task added: {task_id}",
            "task_added",
            agent_id=agent_id,
            action=action
        )

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

        # Initialisation de l'execution si non definie
        if not self.execution:
            self.execution = WorkflowExecution(
                workflow_id=workflow_id,
                status=WorkflowStatus.RUNNING,
                metadata=metadata or {}
            )
        else:
            self.execution.workflow_id = workflow_id
            self.execution.status = WorkflowStatus.RUNNING
            if metadata:
                self.execution.metadata.update(metadata)

        self.execution.start_time = datetime.now(timezone.utc)

        self._logger.log_info(
            f"Workflow started: {workflow_id}",
            "workflow_started",
            workflow_id=workflow_id,
            total_tasks=self.execution.total_count
        )

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
                failed_count = len(self.get_tasks_by_status(TaskExecutionStatus.FAILED))
                if failed_count > 0:
                    self.execution.status = WorkflowStatus.FAILED
                else:
                    self.execution.status = WorkflowStatus.COMPLETED

        except Exception as e:
            self.execution.status = WorkflowStatus.FAILED
            self.execution.error = str(e)
            self._logger.log_error(
                f"Workflow failed: {str(e)}",
                e,
                "workflow_failed",
                workflow_id=workflow_id
            )
            raise

        finally:
            self.execution.end_time = datetime.now(timezone.utc)
            self._running = False
            self._execution_history.append(self.execution)

            # Notification de fin
            await self._notify("workflow_completed", {
                "workflow_id": workflow_id,
                "status": self.execution.status.value,
                "completed_tasks": self.execution.completed_count,
                "total_tasks": self.execution.total_count
            })

            self._logger.log_info(
                f"Workflow completed: {workflow_id}",
                "workflow_completed",
                workflow_id=workflow_id,
                status=self.execution.status.value,
                completed=self.execution.completed_count,
                total=self.execution.total_count
            )

        return workflow_id

    async def stop(self) -> None:
        """
        Demande l'arret du workflow.
        """
        self._stop_requested = True
        self._logger.log_info("Stop requested for workflow", "workflow_stop_requested")

    async def _run_pipeline(self) -> None:
        """
        Execute le pipeline complet via un DAG asynchrone avec file d'attente et workers concurrents.
        """
        if not self.execution:
            raise ValueError("No execution context")

        # Resolution de l'ordre topologique (detection de cycles)
        order = self._resolve_order()
        if not order:
            self._logger.log_warning("No tasks to execute", "workflow_no_tasks")
            return

        self._logger.log_info(
            f"Executing {len(order)} tasks in topological order",
            "workflow_execution_start",
            task_count=len(order)
        )

        semaphore = asyncio.Semaphore(self.max_parallel)
        self._ready_queue = asyncio.Queue()

        # Initialisation de la file avec les taches sans dependances
        for task_id, task in self.execution.tasks.items():
            if not task.dependencies:
                task.status = TaskExecutionStatus.READY
                await self._ready_queue.put(task_id)

        active_tasks: Set[str] = set()

        async def worker():
            while not self._stop_requested:
                try:
                    try:
                        task_id = await asyncio.wait_for(self._ready_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        if self.execution.completed_count >= self.execution.total_count:
                            break
                        failed_tasks = self.get_tasks_by_status(TaskExecutionStatus.FAILED)
                        completed_count = len(self.get_tasks_by_status(TaskExecutionStatus.COMPLETED))
                        if completed_count + len(failed_tasks) >= self.execution.total_count and not active_tasks:
                            break
                        continue

                    async with semaphore:
                        if self._stop_requested:
                            self._ready_queue.task_done()
                            break

                        active_tasks.add(task_id)
                        try:
                            await self._execute_task(task_id)
                        finally:
                            active_tasks.remove(task_id)
                            self._ready_queue.task_done()

                        # Verifier et ajouter les taches pretes suite a cette execution
                        async with self._task_lock:
                            for tid, t in self.execution.tasks.items():
                                if t.status in [TaskExecutionStatus.PENDING, TaskExecutionStatus.BLOCKED]:
                                    if self._is_ready(t):
                                        t.status = TaskExecutionStatus.READY
                                        await self._ready_queue.put(tid)

                except Exception as e:
                    self._logger.log_error(
                        f"Worker error: {str(e)}",
                        e,
                        "worker_error"
                    )
                    break

        # Lancer les workers concurrents
        num_workers = min(self.max_parallel, len(self.execution.tasks))
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]

        # Attendre la fin de l'execution de toutes les taches ou un blocage
        while self.execution.completed_count < self.execution.total_count and not self._stop_requested:
            failed_tasks = self.get_tasks_by_status(TaskExecutionStatus.FAILED)
            completed_count = len(self.get_tasks_by_status(TaskExecutionStatus.COMPLETED))

            if not active_tasks and self._ready_queue.empty():
                pending_or_blocked = self.get_tasks_by_status(TaskExecutionStatus.PENDING) + self.get_tasks_by_status(TaskExecutionStatus.BLOCKED)
                if pending_or_blocked:
                    progress_possible = False
                    async with self._task_lock:
                        for t in pending_or_blocked:
                            if all(self.get_task(d) and self.get_task(d).status == TaskExecutionStatus.COMPLETED for d in t.dependencies):
                                progress_possible = True
                                t.status = TaskExecutionStatus.READY
                                await self._ready_queue.put(t.task_id)
                    if not progress_possible:
                        self._logger.log_error(
                            "Pipeline deadlocked: pending/blocked tasks have unsatisfied or failed dependencies",
                            None,
                            "pipeline_deadlock"
                        )
                        break
                else:
                    break
            await asyncio.sleep(0.1)

        # Nettoyage des workers
        for w in workers:
            w.cancel()

        await asyncio.gather(*workers, return_exceptions=True)

    async def _execute_task(self, task_id: str) -> None:
        """
        Execute une tache individuelle.

        Args:
            task_id: ID de la tache
        """
        task = self.get_task(task_id)
        if not task:
            self._logger.log_error(f"Task {task_id} not found", None, "task_not_found")
            return

        # Verification du circuit breaker
        if self.circuit_breaker:
            is_open = await self.circuit_breaker.is_open(task_id)
            if is_open:
                raise CircuitBreakerOpenError(f"Circuit breaker open for task {task_id}")

        # Mise a jour du statut
        async with self._task_lock:
            task.status = TaskExecutionStatus.RUNNING
            task.start_time = datetime.now(timezone.utc)
            self.execution.current_task = task_id

        self._logger.log_info(
            f"Executing task: {task_id}",
            "task_execution_start",
            task_id=task_id,
            attempt=task.retry_count + 1
        )

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
            async with self._task_lock:
                task.result = result
                task.status = TaskExecutionStatus.COMPLETED
                task.end_time = datetime.now(timezone.utc)
                self.execution.completed_count += 1

            # Sauvegarde si state_manager disponible
            if self.state_manager:
                await self._save_task_result(task)

            # Enregistrement du succes dans le circuit breaker
            if self.circuit_breaker:
                await self.circuit_breaker.record_success(task_id)

            self._logger.log_info(
                f"Task completed: {task_id}",
                "task_completed",
                task_id=task_id,
                duration=(task.end_time - task.start_time).total_seconds() if task.end_time and task.start_time else 0.0
            )

            # Notification de fin de tache
            await self._notify("task_completed", {
                "task_id": task_id,
                "status": "success",
                "duration": (task.end_time - task.start_time).total_seconds() if task.end_time and task.start_time else 0.0
            })

        except Exception as e:
            async with self._task_lock:
                task.error = str(e)
                task.retry_count += 1
                task.end_time = datetime.now(timezone.utc)

                # Enregistrement de la tentative
                task.attempts.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                    "retry_count": task.retry_count
                })

            # Enregistrement de l'echec dans le circuit breaker
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure(task_id, str(e))

            # Verifier si on peut reessayer
            if task.retry_count < task.max_retries:
                task.status = TaskExecutionStatus.RETRYING
                self._logger.log_warning(
                    f"Task {task_id} failed, retrying",
                    "task_retry",
                    task_id=task_id,
                    retry_count=task.retry_count,
                    max_retries=task.max_retries,
                    error=str(e)
                )

                # Notification de retry
                await self._notify("task_retry", {
                    "task_id": task_id,
                    "attempt": task.retry_count,
                    "error": str(e)
                })

                # Delai avant retry (backoff exponentiel)
                delay = 2 ** task.retry_count
                await asyncio.sleep(delay)

                async with self._task_lock:
                    task.status = TaskExecutionStatus.READY

                if self._ready_queue:
                    await self._ready_queue.put(task_id)
            else:
                async with self._task_lock:
                    task.status = TaskExecutionStatus.FAILED

                self._logger.log_error(
                    f"Task {task_id} failed after {task.max_retries} attempts",
                    e,
                    "task_failed",
                    task_id=task_id,
                    max_retries=task.max_retries
                )

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
        if task.status not in [TaskExecutionStatus.PENDING, TaskExecutionStatus.BLOCKED, TaskExecutionStatus.RETRYING]:
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
            result_data = TaskResult(
                task_id=task.task_id,
                agent_id=task.task_data.get("agent_id"),
                status=normalize_status("success"),
                output=task.result,
                error=None,
                duration=(task.end_time - task.start_time).total_seconds() if task.end_time and task.start_time else None,
                timestamp=datetime.now(timezone.utc)
            )

            await self.state_manager.save_task_result(result_data)

        except Exception as e:
            self._logger.log_error(
                f"Failed to save task result: {str(e)}",
                e,
                "save_task_result_failed"
            )

    async def _save_task_error(self, task: TaskExecution) -> None:
        """
        Sauvegarde l'erreur d'une tache.

        Args:
            task: Tache en echec
        """
        if not self.state_manager:
            return

        try:
            result_data = TaskResult(
                task_id=task.task_id,
                agent_id=task.task_data.get("agent_id"),
                status=normalize_status("failed"),
                output=None,
                error=task.error,
                duration=(task.end_time - task.start_time).total_seconds() if task.end_time and task.start_time else None,
                timestamp=datetime.now(timezone.utc)
            )

            await self.state_manager.save_task_result(result_data)

        except Exception as e:
            self._logger.log_error(
                f"Failed to save task error: {str(e)}",
                e,
                "save_task_error_failed"
            )

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
        for listener in self._listeners:
            try:
                await listener(event_type, data)
            except Exception as e:
                self._logger.log_error(
                    f"Listener error: {str(e)}",
                    e,
                    "listener_error"
                )

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
                await self.bus.publish("workflow.events", event_msg)
            except Exception as e:
                self._logger.log_error(
                    f"Failed to send event via bus: {str(e)}",
                    e,
                    "bus_event_failed"
                )

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

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du moteur.

        Returns:
            Dict: Statistiques détaillées
        """
        total_executions = len(self._execution_history)
        successful = sum(1 for e in self._execution_history if e.status == WorkflowStatus.COMPLETED)
        
        cache_metrics = self._cache.get_metrics()
        circuit_metrics = self.circuit_breaker.to_dict() if self.circuit_breaker else {}

        return {
            "total_executions": total_executions,
            "successful_executions": successful,
            "failed_executions": total_executions - successful,
            "success_rate": successful / total_executions if total_executions > 0 else 0,
            "max_parallel": self.max_parallel,
            "default_max_retries": self.default_max_retries,
            "agents_available": len(self.agents),
            "cache_metrics": cache_metrics,
            "circuit_breaker_metrics": circuit_metrics
        }

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
            "status": self.get_status(),
            "statistics": self.get_statistics()
        }