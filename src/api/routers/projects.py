# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Projects Router
# ==============================================================================
# Fichier: src/api/routers/projects.py
# Description: Routes API pour la gestion des projets.
#              CRUD complet avec pagination, filtrage, tri et relations.
#              Support des événements, WebSockets et recherche avancée.
#              Version refactorisée avec logger structuré et horodatages timezone-aware.
# ==============================================================================

from fastapi import APIRouter, Depends, HTTPException, Query, status as fastapi_status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import logging
import uuid
import yaml

from src.db.database import get_async_db
from src.models.project import ProjectModel, ProjectStatus, ProjectChain, ProjectPriority, ProjectCategory
from src.api.schemas.requests import (
    CreateProjectRequest,
    UpdateProjectRequest,
    ListProjectsRequest,
    PaginationParams,
    FilterParams,
    SortParams
)
from src.api.schemas.responses import (
    ProjectSummaryResponse,
    ProjectDetailResponse,
    PaginatedResponse,
    SuccessResponse,
    ErrorResponse,
    StatusResponse
)
from src.api.websockets.notifier import manager
from src.core.exceptions import PipelineError, ValidationError
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.status_manager import normalize_status, status_manager
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy

# ==============================================================================
# CONFIGURATION
# ==============================================================================

logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])

# Logger structuré pour le router
_router_logger = StructuredLogger(
    component_name="ProjectsRouter",
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

def _build_project_summary(p) -> ProjectSummaryResponse:
    """
    Construit un résumé de projet à partir d'un modèle ORM.
    
    Args:
        p: Modèle ORM ProjectModel
        
    Returns:
        ProjectSummaryResponse: Résumé du projet
    """
    return ProjectSummaryResponse(
        id=p.id,
        name=p.name,
        status=p.status.value if p.status else "CREATED",
        priority=p.priority.value if p.priority else "medium",
        category=p.category.value if p.category else "other",
        chain=p.chain.value if p.chain else "ethereum",
        task_count=p.task_count or 0,
        completed_task_count=p.completed_task_count or 0,
        failed_task_count=p.failed_task_count or 0,
        completion_rate=p.completion_rate if hasattr(p, 'completion_rate') else 0.0,
        security_score=p.security_score or 0,
        quality_score=p.quality_score or 0,
        created_at=p.created_at.isoformat() if p.created_at else "",
        tags=p.get_tags() if hasattr(p, 'get_tags') else [],
        is_active=p.is_active if hasattr(p, 'is_active') else True
    )


def _build_project_detail(p) -> ProjectDetailResponse:
    """
    Construit un détail de projet à partir d'un modèle ORM.
    
    Args:
        p: Modèle ORM ProjectModel
        
    Returns:
        ProjectDetailResponse: Détail du projet
    """
    return ProjectDetailResponse(
        id=p.id,
        name=p.name,
        status=p.status.value if p.status else "CREATED",
        priority=p.priority.value if p.priority else "medium",
        category=p.category.value if p.category else "other",
        chain=p.chain.value if p.chain else "ethereum",
        task_count=p.task_count or 0,
        completed_task_count=p.completed_task_count or 0,
        failed_task_count=p.failed_task_count or 0,
        completion_rate=p.completion_rate if hasattr(p, 'completion_rate') else 0.0,
        security_score=p.security_score or 0,
        quality_score=p.quality_score or 0,
        created_at=p.created_at.isoformat() if p.created_at else "",
        tags=p.get_tags() if hasattr(p, 'get_tags') else [],
        is_active=p.is_active if hasattr(p, 'is_active') else True,
        description=p.description or "",
        version=p.version or "1.0.0",
        config=p.config or {},
        metadata=p.metadata or {},
        sprint_count=len(p.sprints) if p.sprints else 0,
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
        started_at=p.started_at.isoformat() if p.started_at else None,
        completed_at=p.completed_at.isoformat() if p.completed_at else None,
        duration_days=p.duration_days if hasattr(p, 'duration_days') else None,
        is_template=p.is_template or False,
        is_public=p.is_public or False
    )


# ==============================================================================
# ROUTES
# ==============================================================================

@router.get("/", response_model=PaginatedResponse[ProjectSummaryResponse])
async def list_projects(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(20, ge=1, le=100, description="Taille de page"),
    search: Optional[str] = Query(None, description="Recherche textuelle"),
    status: Optional[List[str]] = Query(None, description="Filtre par statut"),
    chain: Optional[str] = Query(None, description="Filtre par blockchain"),
    priority: Optional[str] = Query(None, description="Filtre par priorité"),
    category: Optional[str] = Query(None, description="Filtre par catégorie"),
    tags: Optional[List[str]] = Query(None, description="Filtre par tags"),
    is_template: Optional[bool] = Query(None, description="Filtre les templates"),
    is_public: Optional[bool] = Query(None, description="Filtre les projets publics"),
    sort_by: str = Query("created_at", description="Champ de tri"),
    sort_order: str = Query("desc", description="Ordre de tri"),
    include_sprints: bool = Query(False, description="Inclure les sprints"),
    include_tasks: bool = Query(False, description="Inclure les tâches"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Liste tous les projets avec pagination et filtres avancés.
    """
    _router_logger.log_info(
        "Listing projects",
        "list_projects_start",
        page=page,
        page_size=page_size,
        search=search
    )
    
    try:
        # Construction de la requête avec chargement des relations
        query = select(ProjectModel)
        count_query = select(func.count()).select_from(ProjectModel)
        
        # Chargement des relations si demandé
        if include_sprints:
            query = query.options(selectinload(ProjectModel.sprints))
        if include_tasks:
            query = query.options(selectinload(ProjectModel.tasks))
        
        # Filtres
        filters = []
        
        if search:
            search_filter = or_(
                ProjectModel.name.ilike(f"%{search}%"),
                ProjectModel.description.ilike(f"%{search}%")
            )
            filters.append(search_filter)
        
        if status:
            # Normalisation des statuts pour la comparaison
            normalized_statuses = [normalize_status(s).upper() for s in status]
            filters.append(ProjectModel.status.in_(normalized_statuses))
        
        if chain:
            filters.append(ProjectModel.chain == chain)
        
        if priority:
            filters.append(ProjectModel.priority == priority)
        
        if category:
            filters.append(ProjectModel.category == category)
        
        if tags:
            # Recherche par tags dans le champ JSON
            tag_filters = []
            for tag in tags:
                tag_filters.append(ProjectModel.tags.contains([tag]))
            if tag_filters:
                filters.append(or_(*tag_filters))
        
        if is_template is not None:
            filters.append(ProjectModel.is_template == is_template)
        
        if is_public is not None:
            filters.append(ProjectModel.is_public == is_public)
        
        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))
        
        # Tri
        sort_field = getattr(ProjectModel, sort_by, ProjectModel.created_at)
        if sort_order.lower() == "desc":
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))
        
        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        # Exécution avec retry
        async def _execute_queries():
            result = await session.execute(query)
            projects = result.scalars().all()
            
            count_result = await session.execute(count_query)
            total = count_result.scalar() or 0
            
            return projects, total
        
        projects, total = await _db_retry.execute_with_retry(_execute_queries)
        
        # Conversion
        items = [_build_project_summary(p) for p in projects]
        
        _router_logger.log_info(
            f"Listed {len(items)} projects",
            "list_projects_completed",
            total=total,
            returned=len(items)
        )
        
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if page_size > 0 else 0,
            has_next=page < ((total + page_size - 1) // page_size) if page_size > 0 else False,
            has_previous=page > 1
        )
        
    except Exception as e:
        _router_logger.log_error(
            f"Error listing projects: {str(e)}",
            e,
            "list_projects_failed"
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list projects: {str(e)}"
        )


@router.post("/", response_model=ProjectDetailResponse, status_code=fastapi_status.HTTP_201_CREATED)
async def create_project(
    request: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Crée un nouveau projet.
    """
    _router_logger.log_info(
        f"Creating project: {request.name}",
        "create_project_start",
        project_name=request.name
    )
    
    try:
        # Création du projet
        project = ProjectModel(
            id=str(uuid.uuid4()),
            name=request.name,
            description=request.description,
            spec_yaml=request.spec_yaml,
            config=request.config or {},
            tags=request.tags or []
        )
        
        # Extraction des informations du YAML
        try:
            spec_data = yaml.safe_load(request.spec_yaml)
            if spec_data:
                if "chain" in spec_data:
                    project.chain = ProjectChain(spec_data["chain"])
                if "version" in spec_data:
                    project.version = spec_data["version"]
                if "description" in spec_data and not request.description:
                    project.description = spec_data["description"]
                if "priority" in spec_data:
                    project.priority = ProjectPriority(spec_data["priority"])
                if "category" in spec_data:
                    project.category = ProjectCategory(spec_data["category"])
        except yaml.YAMLError as e:
            _router_logger.log_warning(
                f"Failed to parse YAML spec: {str(e)}",
                "yaml_parse_warning"
            )
        
        session.add(project)
        await session.commit()
        await session.refresh(project)
        
        _router_logger.log_info(
            f"Project created: {project.id}",
            "create_project_completed",
            project_id=project.id,
            project_name=project.name
        )
        
        # Notification WebSocket
        background_tasks.add_task(
            manager.send_project_update,
            project.id,
            project.status.value if project.status else "CREATED",
            {"name": project.name, "action": "created"}
        )
        
        return _build_project_detail(project)
        
    except ValidationError as e:
        await session.rollback()
        _router_logger.log_error(
            f"Validation error creating project: {str(e)}",
            e,
            "create_project_validation_failed"
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error creating project: {str(e)}",
            e,
            "create_project_failed"
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create project: {str(e)}"
        )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: str,
    include_sprints: bool = Query(False, description="Inclure les sprints"),
    include_tasks: bool = Query(False, description="Inclure les tâches"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Récupère un projet par son ID.
    """
    _router_logger.log_debug(
        f"Getting project: {project_id}",
        "get_project_start",
        project_id=project_id
    )
    
    try:
        query = select(ProjectModel).where(ProjectModel.id == project_id)
        query = query.options(selectinload(ProjectModel.sprints))
        if include_tasks:
            query = query.options(selectinload(ProjectModel.tasks))
        
        result = await session.execute(query)
        project = result.scalar_one_or_none()
        
        if not project:
            _router_logger.log_warning(
                f"Project not found: {project_id}",
                "get_project_not_found",
                project_id=project_id
            )
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        return _build_project_detail(project)
        
    except HTTPException:
        raise
    except Exception as e:
        _router_logger.log_error(
            f"Error getting project {project_id}: {str(e)}",
            e,
            "get_project_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get project: {str(e)}"
        )


@router.put("/{project_id}", response_model=ProjectDetailResponse)
async def update_project(
    project_id: str,
    request: UpdateProjectRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Met à jour un projet existant.
    """
    _router_logger.log_info(
        f"Updating project: {project_id}",
        "update_project_start",
        project_id=project_id
    )
    
    try:
        result = await session.execute(
            select(ProjectModel)
            .where(ProjectModel.id == project_id)
            .options(selectinload(ProjectModel.sprints))
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        old_status = project.status
        changes = {}
        
        if request.name is not None:
            project.name = request.name
            changes["name"] = request.name
        if request.description is not None:
            project.description = request.description
            changes["description"] = request.description
        if request.status is not None:
            project.update_status(ProjectStatus(request.status))
            changes["status"] = request.status
        if request.config is not None:
            project.config = request.config
            changes["config"] = request.config
        if request.tags is not None:
            project.set_tags(request.tags)
            changes["tags"] = request.tags
        if request.priority is not None:
            project.priority = ProjectPriority(request.priority)
            changes["priority"] = request.priority
        if request.category is not None:
            project.category = ProjectCategory(request.category)
            changes["category"] = request.category
        if request.chain is not None:
            project.chain = ProjectChain(request.chain)
            changes["chain"] = request.chain
        if request.spec_yaml is not None:
            project.spec_yaml = request.spec_yaml
            changes["spec_yaml"] = request.spec_yaml
        
        project.updated_at = datetime.now(timezone.utc)
        
        await session.commit()
        await session.refresh(project)
        
        _router_logger.log_info(
            f"Project updated: {project.id}",
            "update_project_completed",
            project_id=project.id,
            changes=list(changes.keys())
        )
        
        if old_status != project.status:
            background_tasks.add_task(
                manager.send_project_update,
                project.id,
                project.status.value if project.status else "UNKNOWN",
                {"old_status": old_status.value if old_status else None, "changes": changes}
            )
        
        return _build_project_detail(project)
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error updating project {project_id}: {str(e)}",
            e,
            "update_project_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update project: {str(e)}"
        )


@router.patch("/{project_id}/status", response_model=ProjectDetailResponse)
async def update_project_status(
    project_id: str,
    new_status: ProjectStatus = Query(..., description="Nouveau statut du projet"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Met à jour le statut d'un projet.
    """
    _router_logger.log_info(
        f"Updating project status: {project_id}",
        "update_project_status_start",
        project_id=project_id,
        new_status=new_status.value
    )
    
    try:
        result = await session.execute(
            select(ProjectModel)
            .where(ProjectModel.id == project_id)
            .options(selectinload(ProjectModel.sprints))
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        old_status = project.status
        project.update_status(new_status)
        
        await session.commit()
        await session.refresh(project)
        
        _router_logger.log_info(
            f"Project status updated: {project.id}",
            "update_project_status_completed",
            project_id=project.id,
            old_status=old_status.value if old_status else None,
            new_status=new_status.value
        )
        
        background_tasks.add_task(
            manager.send_project_update,
            project.id,
            new_status.value,
            {"old_status": old_status.value if old_status else None}
        )
        
        return _build_project_detail(project)
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error updating project status {project_id}: {str(e)}",
            e,
            "update_project_status_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update project status: {str(e)}"
        )


@router.delete("/{project_id}", response_model=SuccessResponse)
async def delete_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Supprime un projet.
    """
    _router_logger.log_info(
        f"Deleting project: {project_id}",
        "delete_project_start",
        project_id=project_id
    )
    
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        project_name = project.name
        
        await session.delete(project)
        await session.commit()
        
        _router_logger.log_info(
            f"Project deleted: {project_id}",
            "delete_project_completed",
            project_id=project_id,
            project_name=project_name
        )
        
        background_tasks.add_task(
            manager.send_notification,
            "Project Deleted",
            f"Project '{project_name}' has been deleted",
            "warning"
        )
        
        return SuccessResponse(
            success=True,
            message=f"Project {project_id} deleted successfully",
            data={"project_id": project_id, "name": project_name}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error deleting project {project_id}: {str(e)}",
            e,
            "delete_project_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete project: {str(e)}"
        )


@router.get("/{project_id}/stats", response_model=Dict[str, Any])
async def get_project_stats(
    project_id: str,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Récupère les statistiques d'un projet.
    """
    _router_logger.log_debug(
        f"Getting project stats: {project_id}",
        "get_project_stats_start",
        project_id=project_id
    )
    
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        if hasattr(project, 'get_statistics'):
            return project.get_statistics()
        else:
            return {
                "project_id": project.id,
                "name": project.name,
                "task_count": project.task_count or 0,
                "completed_task_count": project.completed_task_count or 0,
                "failed_task_count": project.failed_task_count or 0,
                "completion_rate": project.completion_rate if hasattr(project, 'completion_rate') else 0.0,
                "security_score": project.security_score or 0,
                "quality_score": project.quality_score or 0,
            }
        
    except HTTPException:
        raise
    except Exception as e:
        _router_logger.log_error(
            f"Error getting project stats {project_id}: {str(e)}",
            e,
            "get_project_stats_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get project stats: {str(e)}"
        )


@router.get("/search", response_model=PaginatedResponse[ProjectSummaryResponse])
async def search_projects(
    query: str = Query(..., min_length=1, description="Terme de recherche"),
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(10, ge=1, le=50, description="Taille de page"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    Recherche avancée de projets par nom, description, tags et contenu YAML.
    """
    _router_logger.log_info(
        f"Searching projects: {query}",
        "search_projects_start",
        search_query=query
    )
    
    try:
        search_pattern = f"%{query}%"
        
        query_stmt = select(ProjectModel).where(
            or_(
                ProjectModel.name.ilike(search_pattern),
                ProjectModel.description.ilike(search_pattern),
                ProjectModel.spec_yaml.ilike(search_pattern),
                ProjectModel.tags.contains([query])
            )
        )
        
        count_query = select(func.count()).select_from(ProjectModel).where(
            or_(
                ProjectModel.name.ilike(search_pattern),
                ProjectModel.description.ilike(search_pattern),
                ProjectModel.spec_yaml.ilike(search_pattern),
                ProjectModel.tags.contains([query])
            )
        )
        
        offset = (page - 1) * page_size
        query_stmt = query_stmt.offset(offset).limit(page_size)
        
        result = await session.execute(query_stmt)
        projects = result.scalars().all()
        
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0
        
        items = [_build_project_summary(p) for p in projects]
        
        _router_logger.log_info(
            f"Search returned {len(items)} projects",
            "search_projects_completed",
            total=total,
            returned=len(items)
        )
        
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if page_size > 0 else 0,
            has_next=page < ((total + page_size - 1) // page_size) if page_size > 0 else False,
            has_previous=page > 1
        )
        
    except Exception as e:
        _router_logger.log_error(
            f"Error searching projects: {str(e)}",
            e,
            "search_projects_failed"
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search projects: {str(e)}"
        )


@router.post("/{project_id}/archive", response_model=SuccessResponse)
async def archive_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Archive un projet.
    """
    _router_logger.log_info(
        f"Archiving project: {project_id}",
        "archive_project_start",
        project_id=project_id
    )
    
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        if project.status == ProjectStatus.ARCHIVED:
            raise HTTPException(
                status_code=fastapi_status.HTTP_400_BAD_REQUEST,
                detail="Project is already archived"
            )
        
        project.update_status(ProjectStatus.ARCHIVED)
        project.archived_at = datetime.now(timezone.utc)
        
        await session.commit()
        
        _router_logger.log_info(
            f"Project archived: {project_id}",
            "archive_project_completed",
            project_id=project_id
        )
        
        background_tasks.add_task(
            manager.send_notification,
            "Project Archived",
            f"Project '{project.name}' has been archived",
            "info"
        )
        
        return SuccessResponse(
            success=True,
            message=f"Project {project_id} archived successfully",
            data={"project_id": project_id, "name": project.name}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error archiving project {project_id}: {str(e)}",
            e,
            "archive_project_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to archive project: {str(e)}"
        )


@router.post("/{project_id}/unarchive", response_model=SuccessResponse)
async def unarchive_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Désarchive un projet.
    """
    _router_logger.log_info(
        f"Unarchiving project: {project_id}",
        "unarchive_project_start",
        project_id=project_id
    )
    
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=fastapi_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        if project.status != ProjectStatus.ARCHIVED:
            raise HTTPException(
                status_code=fastapi_status.HTTP_400_BAD_REQUEST,
                detail="Project is not archived"
            )
        
        project.update_status(ProjectStatus.CREATED)
        project.archived_at = None
        
        await session.commit()
        
        _router_logger.log_info(
            f"Project unarchived: {project_id}",
            "unarchive_project_completed",
            project_id=project_id
        )
        
        background_tasks.add_task(
            manager.send_notification,
            "Project Unarchived",
            f"Project '{project.name}' has been unarchived",
            "info"
        )
        
        return SuccessResponse(
            success=True,
            message=f"Project {project_id} unarchived successfully",
            data={"project_id": project_id, "name": project.name}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        _router_logger.log_error(
            f"Error unarchiving project {project_id}: {str(e)}",
            e,
            "unarchive_project_failed",
            project_id=project_id
        )
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unarchive project: {str(e)}"
        )