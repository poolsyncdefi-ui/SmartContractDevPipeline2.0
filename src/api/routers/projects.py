# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Projects Router
# ==============================================================================
# Fichier: src/api/routers/projects.py
# Description: Routes API pour la gestion des projets.
#              CRUD complet avec pagination, filtrage, tri et relations.
#              Support des événements, WebSockets et recherche avancée.
# ==============================================================================

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import uuid

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
from src.core.exceptions import StorageError, ValidationError
from src.core.events import event_bus

# ==============================================================================
# CONFIGURATION
# ==============================================================================

logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])


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
            filters.append(ProjectModel.status.in_(status))
        
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
        
        # Exécution
        result = await session.execute(query)
        projects = result.scalars().all()
        
        count_result = await session.execute(count_query)
        total = count_result.scalar()
        
        # Conversion
        items = []
        for p in projects:
            summary = ProjectSummaryResponse(
                id=p.id,
                name=p.name,
                status=p.status.value if p.status else "UNKNOWN",
                priority=p.priority.value if p.priority else "medium",
                category=p.category.value if p.category else "other",
                chain=p.chain.value if p.chain else "ethereum",
                task_count=p.task_count,
                completed_task_count=p.completed_task_count,
                failed_task_count=p.failed_task_count,
                completion_rate=p.get_completion_rate(),
                security_score=p.security_score,
                quality_score=p.quality_score,
                created_at=p.created_at.isoformat() if p.created_at else "",
                tags=p.get_tags(),
                is_active=p.is_active
            )
            items.append(summary)
        
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
            has_next=page < ((total + page_size - 1) // page_size),
            has_previous=page > 1
        )
        
    except Exception as e:
        logger.error(f"Error listing projects: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list projects: {str(e)}"
        )


@router.post("/", response_model=ProjectDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Crée un nouveau projet.
    """
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
        import yaml
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
        except yaml.YAMLError:
            pass
        
        session.add(project)
        await session.commit()
        await session.refresh(project)
        
        logger.info(f"Project created: {project.id} - {project.name}")
        
        # Émettre un événement
        await event_bus.emit("project_created", {
            "project_id": project.id,
            "name": project.name,
            "status": project.status.value if project.status else "CREATED"
        })
        
        # Notification WebSocket
        background_tasks.add_task(
            manager.send_project_update,
            project.id,
            project.status.value if project.status else "CREATED",
            {"name": project.name, "action": "created"}
        )
        
        # Construire la réponse
        return ProjectDetailResponse(
            id=project.id,
            name=project.name,
            status=project.status.value if project.status else "CREATED",
            priority=project.priority.value if project.priority else "medium",
            category=project.category.value if project.category else "other",
            chain=project.chain.value if project.chain else "ethereum",
            task_count=project.task_count,
            completed_task_count=project.completed_task_count,
            failed_task_count=project.failed_task_count,
            completion_rate=project.get_completion_rate(),
            security_score=project.security_score,
            quality_score=project.quality_score,
            created_at=project.created_at.isoformat() if project.created_at else "",
            tags=project.get_tags(),
            is_active=project.is_active,
            description=project.description,
            version=project.version,
            config=project.config,
            metadata=project.metadata,
            sprint_count=len(project.sprints) if project.sprints else 0,
            updated_at=project.updated_at.isoformat() if project.updated_at else "",
            started_at=project.started_at.isoformat() if project.started_at else None,
            completed_at=project.completed_at.isoformat() if project.completed_at else None,
            duration_days=project.duration_days,
            is_template=project.is_template,
            is_public=project.is_public
        )
        
    except ValidationError as e:
        await session.rollback()
        logger.error(f"Validation error creating project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        # Construction de la requête avec relations
        query = select(ProjectModel).where(ProjectModel.id == project_id)
        
        if include_sprints:
            query = query.options(selectinload(ProjectModel.sprints))
        if include_tasks:
            query = query.options(selectinload(ProjectModel.tasks))
        
        result = await session.execute(query)
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        return ProjectDetailResponse(
            id=project.id,
            name=project.name,
            status=project.status.value if project.status else "CREATED",
            priority=project.priority.value if project.priority else "medium",
            category=project.category.value if project.category else "other",
            chain=project.chain.value if project.chain else "ethereum",
            task_count=project.task_count,
            completed_task_count=project.completed_task_count,
            failed_task_count=project.failed_task_count,
            completion_rate=project.get_completion_rate(),
            security_score=project.security_score,
            quality_score=project.quality_score,
            created_at=project.created_at.isoformat() if project.created_at else "",
            tags=project.get_tags(),
            is_active=project.is_active,
            description=project.description,
            version=project.version,
            config=project.config,
            metadata=project.metadata,
            sprint_count=len(project.sprints) if project.sprints else 0,
            updated_at=project.updated_at.isoformat() if project.updated_at else "",
            started_at=project.started_at.isoformat() if project.started_at else None,
            completed_at=project.completed_at.isoformat() if project.completed_at else None,
            duration_days=project.duration_days,
            is_template=project.is_template,
            is_public=project.is_public
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        old_status = project.status
        changes = {}
        
        # Mise à jour des champs
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
        
        project.updated_at = datetime.utcnow()
        
        await session.commit()
        await session.refresh(project)
        
        logger.info(f"Project updated: {project.id} - {project.name}")
        
        # Émettre un événement si le statut a changé
        if old_status != project.status:
            await event_bus.emit("project_status_changed", {
                "project_id": project.id,
                "old_status": old_status.value if old_status else None,
                "new_status": project.status.value if project.status else None
            })
            
            background_tasks.add_task(
                manager.send_project_update,
                project.id,
                project.status.value if project.status else "UNKNOWN",
                {"old_status": old_status.value if old_status else None, "changes": changes}
            )
        
        return ProjectDetailResponse(
            id=project.id,
            name=project.name,
            status=project.status.value if project.status else "CREATED",
            priority=project.priority.value if project.priority else "medium",
            category=project.category.value if project.category else "other",
            chain=project.chain.value if project.chain else "ethereum",
            task_count=project.task_count,
            completed_task_count=project.completed_task_count,
            failed_task_count=project.failed_task_count,
            completion_rate=project.get_completion_rate(),
            security_score=project.security_score,
            quality_score=project.quality_score,
            created_at=project.created_at.isoformat() if project.created_at else "",
            tags=project.get_tags(),
            is_active=project.is_active,
            description=project.description,
            version=project.version,
            config=project.config,
            metadata=project.metadata,
            sprint_count=len(project.sprints) if project.sprints else 0,
            updated_at=project.updated_at.isoformat() if project.updated_at else "",
            started_at=project.started_at.isoformat() if project.started_at else None,
            completed_at=project.completed_at.isoformat() if project.completed_at else None,
            duration_days=project.duration_days,
            is_template=project.is_template,
            is_public=project.is_public
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating project {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update project: {str(e)}"
        )


@router.patch("/{project_id}/status", response_model=ProjectDetailResponse)
async def update_project_status(
    project_id: str,
    status: ProjectStatus,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_db)
):
    """
    Met à jour le statut d'un projet.
    """
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        old_status = project.status
        project.update_status(status)
        
        await session.commit()
        await session.refresh(project)
        
        logger.info(f"Project status updated: {project.id} - {old_status} -> {status}")
        
        # Émettre un événement
        await event_bus.emit("project_status_changed", {
            "project_id": project.id,
            "old_status": old_status.value if old_status else None,
            "new_status": status.value
        })
        
        background_tasks.add_task(
            manager.send_project_update,
            project.id,
            status.value,
            {"old_status": old_status.value if old_status else None}
        )
        
        return ProjectDetailResponse(
            id=project.id,
            name=project.name,
            status=project.status.value if project.status else "CREATED",
            priority=project.priority.value if project.priority else "medium",
            category=project.category.value if project.category else "other",
            chain=project.chain.value if project.chain else "ethereum",
            task_count=project.task_count,
            completed_task_count=project.completed_task_count,
            failed_task_count=project.failed_task_count,
            completion_rate=project.get_completion_rate(),
            security_score=project.security_score,
            quality_score=project.quality_score,
            created_at=project.created_at.isoformat() if project.created_at else "",
            tags=project.get_tags(),
            is_active=project.is_active,
            description=project.description,
            version=project.version,
            config=project.config,
            metadata=project.metadata,
            sprint_count=len(project.sprints) if project.sprints else 0,
            updated_at=project.updated_at.isoformat() if project.updated_at else "",
            started_at=project.started_at.isoformat() if project.started_at else None,
            completed_at=project.completed_at.isoformat() if project.completed_at else None,
            duration_days=project.duration_days,
            is_template=project.is_template,
            is_public=project.is_public
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating project status {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        project_name = project.name
        
        await session.delete(project)
        await session.commit()
        
        logger.info(f"Project deleted: {project_id} - {project_name}")
        
        # Émettre un événement
        await event_bus.emit("project_deleted", {
            "project_id": project_id,
            "name": project_name
        })
        
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
        logger.error(f"Error deleting project {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        return project.get_statistics()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project stats {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        # Construction de la requête avec recherche plein texte
        search_pattern = f"%{query}%"
        
        query_stmt = select(ProjectModel).where(
            or_(
                ProjectModel.name.ilike(search_pattern),
                ProjectModel.description.ilike(search_pattern),
                ProjectModel.spec_yaml.ilike(search_pattern),
                # Recherche dans les tags JSON
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
        
        # Pagination
        offset = (page - 1) * page_size
        query_stmt = query_stmt.offset(offset).limit(page_size)
        
        result = await session.execute(query_stmt)
        projects = result.scalars().all()
        
        count_result = await session.execute(count_query)
        total = count_result.scalar()
        
        items = []
        for p in projects:
            summary = ProjectSummaryResponse(
                id=p.id,
                name=p.name,
                status=p.status.value if p.status else "UNKNOWN",
                priority=p.priority.value if p.priority else "medium",
                category=p.category.value if p.category else "other",
                chain=p.chain.value if p.chain else "ethereum",
                task_count=p.task_count,
                completed_task_count=p.completed_task_count,
                failed_task_count=p.failed_task_count,
                completion_rate=p.get_completion_rate(),
                security_score=p.security_score,
                quality_score=p.quality_score,
                created_at=p.created_at.isoformat() if p.created_at else "",
                tags=p.get_tags(),
                is_active=p.is_active
            )
            items.append(summary)
        
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
            has_next=page < ((total + page_size - 1) // page_size),
            has_previous=page > 1
        )
        
    except Exception as e:
        logger.error(f"Error searching projects: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        if project.status == ProjectStatus.ARCHIVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project is already archived"
            )
        
        project.update_status(ProjectStatus.ARCHIVED)
        project.archived_at = datetime.utcnow()
        
        await session.commit()
        
        logger.info(f"Project archived: {project_id}")
        
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
        logger.error(f"Error archiving project {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    try:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        if project.status != ProjectStatus.ARCHIVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project is not archived"
            )
        
        project.update_status(ProjectStatus.CREATED)
        project.archived_at = None
        
        await session.commit()
        
        logger.info(f"Project unarchived: {project_id}")
        
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
        logger.error(f"Error unarchiving project {project_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unarchive project: {str(e)}"
        )