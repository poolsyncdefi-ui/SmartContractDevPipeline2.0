# src/api/schemas/requests.py
from pydantic import BaseModel, Field
from typing import Optional

class ProjectCreateRequest(BaseModel):
    """Requête de création de projet."""
    name: str = Field(..., min_length=1, description="Nom du projet")
    spec_yaml: str = Field(..., description="Spécification YAML du projet")

class TaskApproveRequest(BaseModel):
    """Requête d'approbation de tâche."""
    approved: bool = Field(..., description="Approbation de la tâche")
    comments: Optional[str] = Field(None, description="Commentaires de refactoring")

class FeedbackRequest(BaseModel):
    """Requête de retour humain."""
    task_id: str = Field(..., description="ID de la tâche")
    feedback: str = Field(..., description="Retour textuel")