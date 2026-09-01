# src/api/schemas/responses.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProjectResponse(BaseModel):
    """Réponse pour un projet."""
    id: str
    name: str
    status: str
    created_at: datetime

class TaskStatusResponse(BaseModel):
    """Réponse pour le statut d'une tâche."""
    task_id: str
    status: str
    gist_url: Optional[str] = None
    error: Optional[str] = None

class AuditReportResponse(BaseModel):
    """Réponse pour un rapport d'audit."""
    secure: bool
    slither: dict
    foundry: dict
    halmos: dict
    vulnerabilities: list = []