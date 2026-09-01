# src/api/routers/projects.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.database import get_async_db
from src.models.project import ProjectModel, ProjectStatus
from src.api.schemas.requests import ProjectCreateRequest
from src.api.schemas.responses import ProjectResponse
from src.orchestration.workflow_engine import WorkflowEngine
from uuid import uuid4

router = APIRouter(prefix="/projects", tags=["projects"])

@router.post("/", response_model=ProjectResponse)
async def create_project(
    payload: ProjectCreateRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """Crée un projet et initialise l'ArchitectAgent."""
    project = ProjectModel(
        id=str(uuid4()),
        name=payload.name,
        spec_yaml=payload.spec_yaml,
        status=ProjectStatus.CREATED
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    # À implémenter : déclencher l'ArchitectAgent
    # engine = WorkflowEngine()
    # await engine.run_pipeline()
    
    return ProjectResponse(
        id=project.id,
        name=project.name,
        status=project.status.value,
        created_at=project.created_at
    )

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_async_db)
):
    """Récupère un projet par son ID."""
    project = await db.get(ProjectModel, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(
        id=project.id,
        name=project.name,
        status=project.status.value,
        created_at=project.created_at
    )