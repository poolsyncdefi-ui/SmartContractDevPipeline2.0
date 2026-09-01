# src/core/models.py
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional, Any
from datetime import datetime

class Skill(BaseModel):
    """Compétence exécutable par un agent."""
    id: str = Field(..., min_length=1, description="Identifiant unique de la compétence")
    name: str = Field(..., min_length=1)
    description: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    examples: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    execution_timeout: int = Field(default=300, gt=0)
    required_tools: List[str] = Field(default_factory=list)
    parameters_schema: Optional[Dict[str, Any]] = None  # JSON Schema
    output_schema: Optional[Dict[str, Any]] = None      # JSON Schema

    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError('confidence must be between 0 and 1')
        return v

class BestPractice(BaseModel):
    """Bonne pratique de validation."""
    id: str = Field(..., min_length=1)
    domain: str = Field(..., description="solidity, react, security, devops, general")
    rule: str
    rationale: str
    severity: str = Field(..., pattern="^(critical|high|medium|low)$")
    applicable_to: List[str] = Field(default_factory=list)  # IDs de compétences, vide = toutes
    references: List[str] = Field(default_factory=list)
    validation_fn: Optional[str] = None  # nom de la méthode de validation

class Task(BaseModel):
    """Tâche à exécuter par un agent."""
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    agent_id: str          # ID de l'agent cible
    action: str            # nom de la compétence à exécuter
    parameters: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)  # IDs des tâches précédentes
    requires_human_validation: bool = True
    retry_count: int = Field(3, ge=0)
    timeout_seconds: int = Field(600, gt=0)

class TaskResult(BaseModel):
    """Résultat de l'exécution d'une tâche."""
    task_id: str
    sprint_id: Optional[str] = None
    agent_id: Optional[str] = None
    status: str = Field(..., pattern="^(pending|running|success|failed|rejected)$")
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    validation_results: Optional[List[Dict]] = None
    duration_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class Sprint(BaseModel):
    """Sprint de développement."""
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    project_id: str
    tasks: List[Task] = Field(default_factory=list)
    status: str = Field("planned", pattern="^(planned|running|completed|failed)$")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ProjectConfig(BaseModel):
    """Configuration du projet."""
    name: str
    description: str = ""
    chain: str = "ethereum"
    frontend: bool = False
    tests: Dict[str, Any] = Field(default_factory=dict)
    security: Dict[str, Any] = Field(default_factory=dict)
    deployment: Dict[str, Any] = Field(default_factory=dict)
    upgrades: Dict[str, Any] = Field(default_factory=dict)
    monitoring: Dict[str, Any] = Field(default_factory=dict)
    team_requirements: List[Dict] = Field(default_factory=list)  # {skill, count, priority}