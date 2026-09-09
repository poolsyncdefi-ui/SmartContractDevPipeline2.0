# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Tasks Router
# ==============================================================================
# Fichier: src/api/routers/tasks.py
# Description: Routes API pour la gestion des tâches.
#              CRUD complet avec transitions d'état, validation humaine,
#              événements, WebSockets et opérations batch.
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

# ==============================================================================
# CONFIGURATION
# ==============================================================================

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tasks"])


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

        result = await session.execute(query)
        tasks = result.scalars().all()

        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        items = []
        for t in tasks:
            state_val = t.state.value if t.state else "PENDING"
            priority_val = t.priority.value if t.priority else "normal"
            task_type_val = t.task_type.value if t.task_type else "custom"
            summary = TaskSummaryResponse(
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
            items.append(summary)

        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

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
        logger.error(f"Error listing tasks: {str(e)}")
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

        logger.info(f"Task created: {task.id} - {task.name}")

        background_tasks.add_task(
            manager.send_task_update,
            task.id,
            task.state.value if task.state else "PENDING",
            {"name": task.name, "project_id": project_id, "action": "created"}
        )

        return TaskDetailResponse(
            id=task.id,
            name=task.name,
            state=task.state.value if task.state else "PENDING",
            priority=task.priority.value if task.priority else "normal",
            task_type=task.task_type.value if task.task_type else "custom",
            skill_id=task.skill_id,
            retry_count=task.retry_count or 0,
            duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
            created_at=task.created_at.isoformat() if task.created_at else "",
            description=task.description,
            project_id=task.project_id,
            dependencies=task.dependencies,
            parameters=task.parameters,
            result=task.result,
            error_message=task.error_message,
            requires_human_validation=task.requires_human_validation,
            human_validated=task.human_validated,
            human_validation_comments=task.human_validation_comments,
            timeout_seconds=task.timeout_seconds,
            max_retries=task.max_retries,
            is_timeout=getattr(task, 'is_timeout', False),
            elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
            remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
            memory_usage_mb=getattr(task, 'memory_usage_mb', None),
            cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else "",
            logs_preview=_get_safe_logs_preview(task)
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error creating task: {str(e)}")
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

        logger.info(f"Batch created {len(created_tasks)} tasks for project {request.project_id}")

        for task in created_tasks:
            background_tasks.add_task(
                manager.send_task_update,
                task.id,
                task.state.value if task.state else "PENDING",
                {"name": task.name, "action": "created_batch"}
            )

        responses = []
        for task in created_tasks:
            responses.append(TaskDetailResponse(
                id=task.id,
                name=task.name,
                state=task.state.value if task.state else "PENDING",
                priority=task.priority.value if task.priority else "normal",
                task_type=task.task_type.value if task.task_type else "custom",
                skill_id=task.skill_id,
                retry_count=task.retry_count or 0,
                duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
                created_at=task.created_at.isoformat() if task.created_at else "",
                description=task.description,
                project_id=task.project_id,
                dependencies=task.dependencies,
                parameters=task.parameters,
                result=task.result,
                error_message=task.error_message,
                requires_human_validation=task.requires_human_validation,
                human_validated=task.human_validated,
                human_validation_comments=task.human_validation_comments,
                timeout_seconds=task.timeout_seconds,
                max_retries=task.max_retries,
                is_timeout=getattr(task, 'is_timeout', False),
                elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
                remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
                memory_usage_mb=getattr(task, 'memory_usage_mb', None),
                cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
                started_at=task.started_at.isoformat() if task.started_at else None,
                completed_at=task.completed_at.isoformat() if task.completed_at else None,
                updated_at=task.updated_at.isoformat() if task.updated_at else "",
                logs_preview=_get_safe_logs_preview(task)
            ))

        return responses

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error creating batch tasks: {str(e)}")
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

        logs_preview = _get_safe_logs_preview(task) if include_logs else None

        return TaskDetailResponse(
            id=task.id,
            name=task.name,
            state=task.state.value if task.state else "PENDING",
            priority=task.priority.value if task.priority else "normal",
            task_type=task.task_type.value if task.task_type else "custom",
            skill_id=task.skill_id,
            retry_count=task.retry_count or 0,
            duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
            created_at=task.created_at.isoformat() if task.created_at else "",
            description=task.description,
            project_id=task.project_id,
            dependencies=task.dependencies,
            parameters=task.parameters,
            result=task.result if include_result else None,
            error_message=task.error_message,
            requires_human_validation=task.requires_human_validation,
            human_validated=task.human_validated,
            human_validation_comments=task.human_validation_comments,
            timeout_seconds=task.timeout_seconds,
            max_retries=task.max_retries,
            is_timeout=getattr(task, 'is_timeout', False),
            elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
            remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
            memory_usage_mb=getattr(task, 'memory_usage_mb', None),
            cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else "",
            logs_preview=logs_preview
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {str(e)}")
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

        logger.info(f"Task updated: {task.id}")

        if old_state != task.state:
            background_tasks.add_task(
                manager.send_task_update,
                task.id,
                task.state.value if task.state else "UNKNOWN",
                {"old_state": old_state.value if old_state else None, "changes": changes}
            )

        return TaskDetailResponse(
            id=task.id,
            name=task.name,
            state=task.state.value if task.state else "PENDING",
            priority=task.priority.value if task.priority else "normal",
            task_type=task.task_type.value if task.task_type else "custom",
            skill_id=task.skill_id,
            retry_count=task.retry_count or 0,
            duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
            created_at=task.created_at.isoformat() if task.created_at else "",
            description=task.description,
            project_id=task.project_id,
            dependencies=task.dependencies,
            parameters=task.parameters,
            result=task.result,
            error_message=task.error_message,
            requires_human_validation=task.requires_human_validation,
            human_validated=task.human_validated,
            human_validation_comments=task.human_validation_comments,
            timeout_seconds=task.timeout_seconds,
            max_retries=task.max_retries,
            is_timeout=getattr(task, 'is_timeout', False),
            elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
            remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
            memory_usage_mb=getattr(task, 'memory_usage_mb', None),
            cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else "",
            logs_preview=_get_safe_logs_preview(task)
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating task {task_id}: {str(e)}")
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

        logger.info(f"Task deleted: {task_id} - {task_name}")

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
        logger.error(f"Error deleting task {task_id}: {str(e)}")
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

        logger.info(f"Task {task_id} human validated: {request.approved}")

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

        return TaskDetailResponse(
            id=task.id,
            name=task.name,
            state=task.state.value if task.state else "PENDING",
            priority=task.priority.value if task.priority else "normal",
            task_type=task.task_type.value if task.task_type else "custom",
            skill_id=task.skill_id,
            retry_count=task.retry_count or 0,
            duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
            created_at=task.created_at.isoformat() if task.created_at else "",
            description=task.description,
            project_id=task.project_id,
            dependencies=task.dependencies,
            parameters=task.parameters,
            result=task.result,
            error_message=task.error_message,
            requires_human_validation=task.requires_human_validation,
            human_validated=task.human_validated,
            human_validation_comments=task.human_validation_comments,
            timeout_seconds=task.timeout_seconds,
            max_retries=task.max_retries,
            is_timeout=getattr(task, 'is_timeout', False),
            elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
            remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
            memory_usage_mb=getattr(task, 'memory_usage_mb', None),
            cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else "",
            logs_preview=_get_safe_logs_preview(task)
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error validating task {task_id}: {str(e)}")
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

        logger.info(f"Task {task_id} retry scheduled (attempt {task.retry_count})")

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

        return TaskDetailResponse(
            id=task.id,
            name=task.name,
            state=task.state.value if task.state else "PENDING",
            priority=task.priority.value if task.priority else "normal",
            task_type=task.task_type.value if task.task_type else "custom",
            skill_id=task.skill_id,
            retry_count=task.retry_count or 0,
            duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
            created_at=task.created_at.isoformat() if task.created_at else "",
            description=task.description,
            project_id=task.project_id,
            dependencies=task.dependencies,
            parameters=task.parameters,
            result=task.result,
            error_message=task.error_message,
            requires_human_validation=task.requires_human_validation,
            human_validated=task.human_validated,
            human_validation_comments=task.human_validation_comments,
            timeout_seconds=task.timeout_seconds,
            max_retries=task.max_retries,
            is_timeout=getattr(task, 'is_timeout', False),
            elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
            remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
            memory_usage_mb=getattr(task, 'memory_usage_mb', None),
            cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else "",
            logs_preview=_get_safe_logs_preview(task)
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error retrying task {task_id}: {str(e)}")
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

        logger.info(f"Task {task_id} cancelled: {reason or 'No reason provided'}")

        background_tasks.add_task(
            manager.send_task_update,
            task.id,
            task.state.value if task.state else "CANCELLED",
            {
                "old_state": old_state.value if old_state else None,
                "reason": reason
            }
        )

        return TaskDetailResponse(
            id=task.id,
            name=task.name,
            state=task.state.value if task.state else "CANCELLED",
            priority=task.priority.value if task.priority else "normal",
            task_type=task.task_type.value if task.task_type else "custom",
            skill_id=task.skill_id,
            retry_count=task.retry_count or 0,
            duration_seconds=getattr(task, 'duration_seconds', 0.0) or 0.0,
            created_at=task.created_at.isoformat() if task.created_at else "",
            description=task.description,
            project_id=task.project_id,
            dependencies=task.dependencies,
            parameters=task.parameters,
            result=task.result,
            error_message=task.error_message,
            requires_human_validation=task.requires_human_validation,
            human_validated=task.human_validated,
            human_validation_comments=task.human_validation_comments,
            timeout_seconds=task.timeout_seconds,
            max_retries=task.max_retries,
            is_timeout=getattr(task, 'is_timeout', False),
            elapsed_time=getattr(task, 'elapsed_time', 0.0) or 0.0,
            remaining_time=getattr(task, 'remaining_time', 0.0) or 0.0,
            memory_usage_mb=getattr(task, 'memory_usage_mb', None),
            cpu_usage_percent=getattr(task, 'cpu_usage_percent', None),
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            updated_at=task.updated_at.isoformat() if task.updated_at else "",
            logs_preview=_get_safe_logs_preview(task)
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error cancelling task {task_id}: {str(e)}")
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
        logger.error(f"Error getting task stats {task_id}: {str(e)}")
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
        logger.error(f"Error getting project tasks stats {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get project tasks stats: {str(e)}"
        )