# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Tasks Router
# ==============================================================================
# Fichier: src/api/routers/tasks.py
# Description: Routes API pour la gestion des tâches.
#              CRUD complet avec transitions d'état, validation humaine,
#              événements, WebSockets et opérations batch.
#              Version refactorisée avec logger structuré et horodatages timezone-aware.
# ==============================================================================

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import logging
import uuid

from src.db.database import get_async_db
from src.models.task import TaskModel, TaskState, TaskPriority, TaskType
from src.models.project import ProjectModel
from src.api.schemas.requests import (
    CreateTaskRequest,
    UpdateTaskRequest,
    ListTasksRequest,
    HumanValidationRequest,
    RetryTaskRequest,
    BatchTaskRequest
)
from src.api.schemas.responses import (
    TaskSummaryResponse,
    TaskDetailResponse,
    PaginatedResponse,
    SuccessResponse,
    CreatedResponse
)
from src.api.websockets.notifier import manager
from src.core.exceptions import PipelineError
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.status_manager import normalize_status, status_manager, StatusManager
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy

# ==============================================================================
# CONFIGURATION
# ==============================================================================

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tasks"])

# Logger structuré pour le router
_router_logger = StructuredLogger(
    component_name="TasksRouter",
    log_level=LogLevel.INFO
)

# Système de retry pour les opérations BDD
_db_retry = AdaptiveRetry(
    base_delay=0.5,
    max_delay=5.0,
    max_retries=3,
    strategy=RetryStrategy.EXPONENTIAL,
    jitter=True
)


# ==============================================================================
# UTILITAIRES
# ==============================================================================

def _get_safe_logs_preview(task) -> Optional[str]:
    """Helper sécurisé pour extraire un aperçu des logs sans risque de TypeError."""
    logs = getattr(task, 'logs', None)
    if not logs:
        return None
    if isinstance(logs, list):
        logs_content = "\n".join(str(l) for l in logs)
    else:
        logs_content = str(logs)
    return logs_content[:500] + "..." if len(logs_content) > 500 else logs_content


def _build_task_summary(t) -> TaskSummaryResponse:
    """
    Construit un résumé de tâche à partir d'un modèle ORM.
    
    Args:
        t: Modèle ORM TaskModel
        
    Returns:
        TaskSummaryResponse: Résumé de la tâche
    """
    state_val = t.state.value if t.state else "PENDING"
    priority_val = t.priority.value if t.priority else "normal"
    task_type_val = t.task_type.value if t.task_type else "custom"
    
    return TaskSummaryResponse(
        id=t.id,
        name=t.name,
        state=state_val,
        priority=priority_val,
        task_type=task_type_val,
        skill_id=t.skill_id,
        retry_count=t.retry_count or 0,
        duration_seconds=getattr(t, 'duration_seconds', 0.0) or 0.0,
        created_at=t.created_at.isoformat() if t.created_at else "",
        is_terminal=getattr(t, 'is_terminal', False),
        is_success=getattr(t, 'is_success', False)
    )


def _build_task_detail(t, include_logs: bool = False) -> TaskDetailResponse:
    """
    Construit un détail de tâche à partir d'un modèle ORM.
    
    Args:
        t: Modèle ORM TaskModel
        include_logs: Inclure l'aperçu des logs
        
    Returns:
        TaskDetailResponse: Détail de la tâche
    """
    state_val = t.state.value if t.state else "PENDING"
    priority_val = t.priority.value if t.priority else "normal"
    task_type_val = t.task_type.value if t.task_type else "custom"
    
    return TaskDetailResponse(
        id=t.id,
        name=t.name,
        state=state_val,
        priority=priority_val,
        task_type=task_type_val,
        skill_id=t.skill_id,
        retry_count=t.retry_count or 0,
        duration_seconds=getattr(t, 'duration_seconds', 0.0) or 0.0,
        created_at=t.created_at.isoformat() if t.created_at else "",
        description=t.description,
        project_id=t.project_id,
        dependencies=t.dependencies,
        parameters=t.parameters,
        result=t.result,
        error_message=t.error_message,
        requires_human_validation=t.requires_human_validation,
        human_validated=t.human_validated,
        human_validation_comments=t.human_validation_comments,
        timeout_seconds=t.timeout_seconds,
        max_retries=t.max_retries,
        is_timeout=getattr(t, 'is_timeout', False),
        elapsed_time=getattr(t, 'elapsed_time', 0.0) or 0.0,
        remaining_time=getattr(t, 'remaining_time', 0.0) or 0.0,
        memory_usage_mb=getattr(t, 'memory_usage_mb', None),
        cpu_usage_percent=getattr(t, 'cpu_usage_percent', None),
        started_at=t.started_at.isoformat() if t.started_at else None,
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
        updated_at=t.updated_at.isoformat() if t.updated_at else "",
        logs_preview=_get_safe_logs_preview(t) if include_logs else None
    )


# ==============================================================================
# ROUTES
# ==============================================================================

@router.get("/", response_model=PaginatedResponse[TaskSummaryResponse])
async def list_tasks(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(20, ge=1, le=100, description="Taille de page"),
    project_id: Optional[str] = Query(None, description="Filtrer par projet"),
    skill_id: Optional[str] = Query(None, description="Filtrer par compétence"),
    state: Optional[List[str]] = Query(None, description="Filtrer par état"),
    priority: Optional[str] = Query(None, description="Filtrer par priorité"),
    task_type: Optional[str] = Query(None, description="Filtrer par type"),
    requires_human_validation: Optional[bool] = Query(None, description="Filtrer par validation humaine"),
    human_validated: Optional[bool] = Query(None, description="Filtrer par validation effectuée"),
    search: Optional[str] = Query(None, description="Recherche textuelle"),
    sort_by: str = Query("created_at", description="Champ de tri"),
    sort_order: str = Query("desc", description="Ordre de tri"),
    include_result: bool = Query(False, description="Inclure le résultat"),
    include_logs: bool = Query(False, description="Inclure les logs"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Liste toutes les tâches avec pagination et filtres avancés.
    """
    _router_logger.log_info(
        "Listing tasks",
        "list_tasks_start",
        page=page,
        page_size=page_size,
        project_id=project_id
    )
    
    try:
        query = select(TaskModel)
        count_query = select(func.count()).select_from(TaskModel)

        filters = []

        if project_id:
            filters.append(TaskModel.project_id == project_id)

        if skill_id:
            filters.append(TaskModel.skill_id == skill_id)

        if state:
            filters.append(TaskModel.state.in_(state))

        if priority:
            filters.append(TaskModel.priority == priority)

        if task_type:
            filters.append(TaskModel.task_type == task_type)

        if requires_human_validation is not None:
            filters.append(TaskModel.requires_human_validation == requires_human_validation)

        if human_validated is not None:
            filters.append(TaskModel.human_validated == human_validated)

        if search:
            search_filter = or_(
                TaskModel.name.ilike(f"%{search}%"),
                TaskModel.description.ilike(f"%{search}%")
            )
            filters.append(search_filter)

        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        sort_field = getattr(TaskModel, sort_by, TaskModel.created_at)
        if sort_order.lower() == "desc":
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # Exécution avec retry
        async def _execute_queries():
            result = await session.execute(query)
            tasks = result.scalars().all()
            
            count_result = await session.execute(count_query)
            total = count_result.scalar() or 0
            
            return tasks, total
        
        tasks, total = await _db_retry.execute_with_retry(_execute_queries)

        items = [_build_task_summary(t) for t in tasks]

        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        _router_logger.log_info(
            f"Listed {len(items)} tasks",
            "list_tasks_completed",
            total=total,
            returned=len(items)
        )

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages if page_size > 0 else False,
            has_previous=page > 1
        )

    except Exception as e:
        _router_logger.log_error(
            f"Error listing tasks: {str(e)}",
            e,
            "list_tasks_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}"
        )


@router.post("/", response_model=TaskDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: CreateTaskRequest,
    project_id: str = Query(..., description="ID du projet"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Crée une nouvelle tâche.
    """
    _router_logger.log_info(
        f"Creating task: {request.name}",
        "create_task_start",
        project_id=project_id
    )
    
    try:
        project_result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = project_result.scalar_one_or_none()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )

        task = TaskModel(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=request.name,
            description=request.description,
            skill_id=request.skill_id,
            parameters=request.parameters or {},
            dependencies=request.depends_on or [],
            requires_human_validation=request.requires_human_validation,
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
            priority=TaskPriority(request.priority),
            task_type=TaskType(request.task_type) if request.task_type else TaskType.CUSTOM,
            metadata=request.metadata or {}
        )

        session.add(task)
        project.task_count = (project.task_count or 0) + 1
        if hasattr(project, 'increment_task_count'):
            project.increment_task_count()

        await session.commit()
        await session.refresh(task)

        _router_logger.log_info(
            f"Task created: {task.id}",
            "create_task_completed",
            task_id=task.id,
            task_name=task.name
        )

        background_tasks.add_task(
            manager.send_task_update,
            task.id,
            task.state.value if task.state else "PENDING",
            {"name": task.name, "project_id": project_id, "action": "created"}
        )

        return _build_task_detail(task)

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error creating task: {str(e)}",
            e,
            "create_task_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )


@router.post("/batch", response_model=List[TaskDetailResponse], status_code=status.HTTP_201_CREATED)
async def create_tasks_batch(
    request: BatchTaskRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Crée plusieurs tâches en masse.
    """
    _router_logger.log_info(
        f"Creating batch of {len(request.tasks)} tasks",
        "create_tasks_batch_start",
        project_id=request.project_id
    )
    
    try:
        project_result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == request.project_id)
        )
        project = project_result.scalar_one_or_none()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {request.project_id} not found"
            )

        created_tasks = []

        for task_req in request.tasks:
            task = TaskModel(
                id=str(uuid.uuid4()),
                project_id=request.project_id,
                name=task_req.name,
                description=task_req.description,
                skill_id=task_req.skill_id,
                parameters=task_req.parameters or {},
                dependencies=task_req.depends_on or [],
                requires_human_validation=task_req.requires_human_validation,
                timeout_seconds=task_req.timeout_seconds,
                max_retries=task_req.max_retries,
                priority=TaskPriority(task_req.priority),
                task_type=TaskType(task_req.task_type) if task_req.task_type else TaskType.CUSTOM,
                metadata=task_req.metadata or {}
            )

            session.add(task)
            project.task_count = (project.task_count or 0) + 1
            if hasattr(project, 'increment_task_count'):
                project.increment_task_count()
            created_tasks.append(task)

        await session.commit()

        for task in created_tasks:
            await session.refresh(task)

        _router_logger.log_info(
            f"Batch created {len(created_tasks)} tasks",
            "create_tasks_batch_completed",
            project_id=request.project_id,
            count=len(created_tasks)
        )

        for task in created_tasks:
            background_tasks.add_task(
                manager.send_task_update,
                task.id,
                task.state.value if task.state else "PENDING",
                {"name": task.name, "action": "created_batch"}
            )

        return [_build_task_detail(task) for task in created_tasks]

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error creating batch tasks: {str(e)}",
            e,
            "create_tasks_batch_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create batch tasks: {str(e)}"
        )


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: str,
    include_result: bool = Query(False, description="Inclure le résultat"),
    include_logs: bool = Query(False, description="Inclure les logs"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Récupère une tâche par son ID.
    """
    _router_logger.log_debug(
        f"Getting task: {task_id}",
        "get_task_start",
        task_id=task_id
    )
    
    try:
        query = select(TaskModel).where(TaskModel.id == task_id)
        if hasattr(TaskModel, 'logs'):
            query = query.options(selectinload(TaskModel.logs))
        if hasattr(TaskModel, 'artifacts'):
            query = query.options(selectinload(TaskModel.artifacts))

        result = await session.execute(query)
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        return _build_task_detail(task, include_logs=include_logs)

    except HTTPException:
        raise
    except Exception as e:
        _router_logger.log_error(
            f"Error getting task {task_id}: {str(e)}",
            e,
            "get_task_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task: {str(e)}"
        )


@router.put("/{task_id}", response_model=TaskDetailResponse)
async def update_task(
    task_id: str,
    request: UpdateTaskRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Met à jour une tâche existante.
    """
    _router_logger.log_info(
        f"Updating task: {task_id}",
        "update_task_start",
        task_id=task_id
    )
    
    try:
        result = await session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        old_state = task.state
        changes = {}

        if request.name is not None:
            task.name = request.name
            changes["name"] = request.name
        if request.description is not None:
            task.description = request.description
            changes["description"] = request.description
        if request.state is not None:
            new_state = TaskState(request.state)
            if new_state == TaskState.SUCCESS and task.state != TaskState.SUCCESS:
                if hasattr(task, 'mark_success'):
                    task.mark_success()
                else:
                    task.state = new_state
            elif new_state == TaskState.FAILED and task.state != TaskState.FAILED:
                if hasattr(task, 'mark_failed'):
                    task.mark_failed("Updated via API")
                else:
                    task.state = new_state
            elif new_state == TaskState.CANCELLED:
                if hasattr(task, 'mark_cancelled'):
                    task.mark_cancelled("Updated via API")
                else:
                    task.state = new_state
            else:
                task.state = new_state
            changes["state"] = request.state
        if request.parameters is not None:
            task.parameters = request.parameters
            changes["parameters"] = request.parameters
        if request.timeout_seconds is not None:
            task.timeout_seconds = request.timeout_seconds
            changes["timeout_seconds"] = request.timeout_seconds
        if request.priority is not None:
            task.priority = TaskPriority(request.priority)
            changes["priority"] = request.priority
        if request.metadata is not None:
            task.metadata = request.metadata
            changes["metadata"] = request.metadata

        task.updated_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(task)

        _router_logger.log_info(
            f"Task updated: {task.id}",
            "update_task_completed",
            task_id=task.id,
            changes=list(changes.keys())
        )

        if old_state != task.state:
            background_tasks.add_task(
                manager.send_task_update,
                task.id,
                task.state.value if task.state else "UNKNOWN",
                {"old_state": old_state.value if old_state else None, "changes": changes}
            )

        return _build_task_detail(task)

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error updating task {task_id}: {str(e)}",
            e,
            "update_task_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update task: {str(e)}"
        )


@router.delete("/{task_id}", response_model=SuccessResponse)
async def delete_task(
    task_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Supprime une tâche.
    """
    _router_logger.log_info(
        f"Deleting task: {task_id}",
        "delete_task_start",
        task_id=task_id
    )
    
    try:
        result = await session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        task_name = task.name
        project_id = task.project_id

        project_result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        if project:
            project.task_count = max(0, (project.task_count or 0) - 1)
            if hasattr(task, 'is_success') and task.is_success:
                project.completed_task_count = max(0, (project.completed_task_count or 0) - 1)
            if hasattr(task, 'is_failed') and task.is_failed:
                project.failed_task_count = max(0, (project.failed_task_count or 0) - 1)

        await session.delete(task)
        await session.commit()

        _router_logger.log_info(
            f"Task deleted: {task_id}",
            "delete_task_completed",
            task_id=task_id,
            task_name=task_name
        )

        background_tasks.add_task(
            manager.send_notification,
            "Task Deleted",
            f"Task '{task_name}' has been deleted",
            "warning"
        )

        return SuccessResponse(
            success=True,
            message=f"Task {task_id} deleted successfully",
            data={"task_id": task_id, "name": task_name, "project_id": project_id}
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error deleting task {task_id}: {str(e)}",
            e,
            "delete_task_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete task: {str(e)}"
        )


@router.post("/{task_id}/human-validate", response_model=TaskDetailResponse)
async def human_validate_task(
    task_id: str,
    request: HumanValidationRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Valide ou rejette une tâche par un humain.
    """
    _router_logger.log_info(
        f"Human validation for task: {task_id}",
        "human_validate_task_start",
        task_id=task_id,
        approved=request.approved
    )
    
    try:
        result = await session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        if task.state != TaskState.WAITING_HUMAN_VALIDATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task {task_id} is not waiting for human validation (current state: {task.state.value if task.state else 'UNKNOWN'})"
            )

        old_state = task.state
        if hasattr(task, 'mark_human_validated'):
            task.mark_human_validated(request.approved, request.comments)
        else:
            task.human_validated = request.approved
            task.human_validation_comments = request.comments
            if request.approved:
                task.state = TaskState.SUCCESS
            else:
                task.state = TaskState.FAILED

        await session.commit()
        await session.refresh(task)

        _router_logger.log_info(
            f"Task human validated: {task_id}",
            "human_validate_task_completed",
            task_id=task_id,
            approved=request.approved
        )

        background_tasks.add_task(
            manager.send_task_update,
            task.id,
            task.state.value if task.state else "UNKNOWN",
            {
                "human_validated": request.approved,
                "old_state": old_state.value if old_state else None,
                "comments": request.comments
            }
        )

        return _build_task_detail(task)

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error validating task {task_id}: {str(e)}",
            e,
            "human_validate_task_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate task: {str(e)}"
        )


@router.post("/{task_id}/retry", response_model=TaskDetailResponse)
async def retry_task(
    task_id: str,
    request: RetryTaskRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Réessaie une tâche échouée.
    """
    _router_logger.log_info(
        f"Retrying task: {task_id}",
        "retry_task_start",
        task_id=task_id
    )
    
    try:
        result = await session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        is_failed = getattr(task, 'is_failed', task.state == TaskState.FAILED)
        if not is_failed and not request.force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task {task_id} is not failed (current state: {task.state.value if task.state else 'UNKNOWN'})"
            )

        can_retry = getattr(task, 'can_retry', lambda: (task.retry_count or 0) < task.max_retries)()
        if not can_retry and not request.force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task {task_id} has no retries remaining (retries: {task.retry_count}/{task.max_retries})"
            )

        old_state = task.state
        task.state = TaskState.PENDING
        task.completed_at = None
        task.error_message = None
        task.result = None
        if request.reset_retry_count:
            task.retry_count = 0
        else:
            task.retry_count = (task.retry_count or 0) + 1
        task.is_retry = True
        task.updated_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(task)

        _router_logger.log_info(
            f"Task retry scheduled: {task_id}",
            "retry_task_completed",
            task_id=task_id,
            retry_count=task.retry_count
        )

        background_tasks.add_task(
            manager.send_task_update,
            task.id,
            task.state.value if task.state else "PENDING",
            {
                "old_state": old_state.value if old_state else None,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries
            }
        )

        return _build_task_detail(task)

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error retrying task {task_id}: {str(e)}",
            e,
            "retry_task_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retry task: {str(e)}"
        )


@router.post("/{task_id}/cancel", response_model=TaskDetailResponse)
async def cancel_task(
    task_id: str,
    reason: Optional[str] = Query(None, description="Raison de l'annulation"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Annule une tâche en cours.
    """
    _router_logger.log_info(
        f"Cancelling task: {task_id}",
        "cancel_task_start",
        task_id=task_id,
        reason=reason
    )
    
    try:
        result = await session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        is_terminal = getattr(task, 'is_terminal', False)
        if is_terminal:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task {task_id} is already in terminal state: {task.state.value if task.state else 'UNKNOWN'}"
            )

        old_state = task.state
        if hasattr(task, 'mark_cancelled'):
            task.mark_cancelled(reason or "Cancelled by user")
        else:
            task.state = TaskState.CANCELLED
            task.error_message = reason or "Cancelled by user"

        await session.commit()
        await session.refresh(task)

        _router_logger.log_info(
            f"Task cancelled: {task_id}",
            "cancel_task_completed",
            task_id=task_id,
            reason=reason
        )

        background_tasks.add_task(
            manager.send_task_update,
            task.id,
            task.state.value if task.state else "CANCELLED",
            {
                "old_state": old_state.value if old_state else None,
                "reason": reason
            }
        )

        return _build_task_detail(task)

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error cancelling task {task_id}: {str(e)}",
            e,
            "cancel_task_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel task: {str(e)}"
        )


@router.get("/{task_id}/stats", response_model=Dict[str, Any])
async def get_task_stats(
    task_id: str,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Récupère les statistiques d'une tâche.
    """
    _router_logger.log_debug(
        f"Getting task stats: {task_id}",
        "get_task_stats_start",
        task_id=task_id
    )
    
    try:
        result = await session.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        if hasattr(task, 'get_statistics'):
            return task.get_statistics()
        else:
            return {
                "task_id": task.id,
                "name": task.name,
                "state": task.state.value if task.state else "PENDING",
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "retry_count": task.retry_count or 0,
                "max_retries": task.max_retries,
                "duration_seconds": getattr(task, 'duration_seconds', 0.0) or 0.0
            }

    except HTTPException:
        raise
    except Exception as e:
        _router_logger.log_error(
            f"Error getting task stats {task_id}: {str(e)}",
            e,
            "get_task_stats_failed",
            task_id=task_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task stats: {str(e)}"
        )


@router.get("/project/{project_id}/stats", response_model=Dict[str, Any])
async def get_project_tasks_stats(
    project_id: str,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Récupère les statistiques des tâches d'un projet.
    """
    _router_logger.log_debug(
        f"Getting project tasks stats: {project_id}",
        "get_project_tasks_stats_start",
        project_id=project_id
    )
    
    try:
        project_result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = project_result.scalar_one_or_none()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )

        stats_by_state = {}
        for state in TaskState:
            count_result = await session.execute(
                select(func.count()).select_from(TaskModel)
                .where(TaskModel.project_id == project_id)
                .where(TaskModel.state == state)
            )
            count = count_result.scalar() or 0
            stats_by_state[state.value] = count

        stats_by_priority = {}
        for priority in TaskPriority:
            count_result = await session.execute(
                select(func.count()).select_from(TaskModel)
                .where(TaskModel.project_id == project_id)
                .where(TaskModel.priority == priority)
            )
            count = count_result.scalar() or 0
            stats_by_priority[priority.value] = count

        total_result = await session.execute(
            select(func.count()).select_from(TaskModel)
            .where(TaskModel.project_id == project_id)
        )
        total = total_result.scalar() or 0

        success_count = stats_by_state.get("SUCCESS", 0)

        _router_logger.log_info(
            f"Project tasks stats: {project_id}",
            "get_project_tasks_stats_completed",
            project_id=project_id,
            total_tasks=total
        )

        return {
            "project_id": project_id,
            "total_tasks": total,
            "by_state": stats_by_state,
            "by_priority": stats_by_priority,
            "completed_count": success_count,
            "failed_count": stats_by_state.get("FAILED", 0) + stats_by_state.get("CIRCUIT_BROKEN", 0),
            "pending_count": stats_by_state.get("PENDING", 0) + stats_by_state.get("READY", 0),
            "running_count": stats_by_state.get("RUNNING", 0) + stats_by_state.get("AUTO_TESTING", 0),
            "completion_rate": (success_count / total * 100) if total > 0 else 0.0
        }

    except HTTPException:
        raise
    except Exception as e:
        _router_logger.log_error(
            f"Error getting project tasks stats {project_id}: {str(e)}",
            e,
            "get_project_tasks_stats_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get project tasks stats: {str(e)}"
        )