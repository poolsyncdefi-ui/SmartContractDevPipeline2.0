# src/persistence/models_orm.py

"""
Aggregation point for all ORM models.
F13 – src/persistence/models_orm.py

Rôle Fonctionnel : Point d'agrégation unique pour tous les modèles ORM SQLAlchemy.
Ce fichier centralise tous les imports de modèles pour les rendre disponibles
via un seul point d'entree. Cela simplifie les imports dans le reste du projet
et aide a eviter les dependances circulaires entre les modules.

Ce fichier inclut egalement des modeles supplementaires (Sprint, TaskResult, Artifact)
qui peuvent etre utilises pour des fonctionnalites avancees de suivi de projet,
tout en restant compatibles avec les modeles principaux du pipeline.

Tout nouveau modele ORM doit etre importe et ajoute a la liste __all__.

Structure des relations:
- ProjectModel <-> Sprint (one-to-many)
- Sprint <-> TaskResult (one-to-many)
- ProjectModel <-> TaskModel (one-to-many)
- TaskModel <-> ExecutionLogModel (one-to-many)
- TaskModel <-> Artifact (one-to-many)
- SkillRecordModel (standalone, referenced by SkillRegistry)
"""
from sqlalchemy import (
    Column, String, JSON, DateTime, Integer, Float, ForeignKey, Text, 
    Enum, Boolean, UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.orm import declarative_base, relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime
import uuid
import enum
import json
from typing import Dict, Any, List, Optional

# Import des modeles principaux du pipeline
from src.db.database import Base as PipelineBase
from src.models.project import ProjectModel, ProjectStatus
from src.models.task import TaskModel, TaskState
from src.models.execution_log import ExecutionLogModel, LogLevel, LogCategory
from src.models.skill_record import SkillRecordModel, SkillStatus, SkillScope

# La base declarative principale est deja definie dans src.db.database
# Nous l'utilisons comme base pour tous les modeles
Base = PipelineBase


# =============================================================================
# MODELES SUPPLEMENTAIRES POUR LE SUIVI DE PROJET (EXTENSIONS)
# =============================================================================

class Sprint(Base):
    """
    Modele pour les sprints de developpement.
    Permet de regrouper les taches en cycles de developpement.
    
    Relations:
        - project: ProjectModel parent (many-to-one)
        - task_results: TaskResult enfants (one-to-many)
    """
    __tablename__ = 'sprints'
    
    # Identifiants
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Informations
    name = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    status = Column(String, default='planned', nullable=False, index=True)
    priority = Column(Integer, default=5)  # 1-10
    
    # Dates
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Métadonnées
    metadata = Column(JSON, nullable=True, default=dict)
    tags = Column(JSON, nullable=True, default=list)
    
    # Relations
    project = relationship("ProjectModel", back_populates="sprints", lazy="selectin")
    task_results = relationship("TaskResult", back_populates="sprint", cascade="all, delete-orphan", lazy="selectin")
    
    # Contraintes
    __table_args__ = (
        CheckConstraint('priority >= 1 AND priority <= 10', name='chk_sprint_priority'),
        CheckConstraint("status IN ('planned', 'active', 'completed', 'cancelled', 'blocked')", name='chk_sprint_status'),
        Index('idx_sprints_project_status', 'project_id', 'status'),
        Index('idx_sprints_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<Sprint(id='{self.id}', name='{self.name}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit le sprint en dictionnaire."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
            "tags": self.get_tags(),
            "task_results_count": len(self.task_results) if self.task_results else 0
        }
    
    def get_tags(self) -> List[str]:
        """Récupère les tags sous forme de liste."""
        if not self.tags:
            return []
        if isinstance(self.tags, list):
            return self.tags
        try:
            return json.loads(self.tags)
        except (json.JSONDecodeError, TypeError):
            return []
    
    def set_tags(self, tags: List[str]) -> None:
        """Définit les tags à partir d'une liste."""
        self.tags = tags if tags else []
    
    @hybrid_property
    def is_active(self) -> bool:
        """Vérifie si le sprint est actif."""
        return self.status == 'active'
    
    @hybrid_property
    def is_completed(self) -> bool:
        """Vérifie si le sprint est terminé."""
        return self.status == 'completed'


class TaskResult(Base):
    """
    Modele pour les resultats d'execution des taches.
    Stocke les sorties des agents et les metriques d'execution.
    
    Relations:
        - sprint: Sprint parent (many-to-one)
    """
    __tablename__ = 'task_results'
    
    # Identifiants
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sprint_id = Column(String, ForeignKey('sprints.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Informations
    task_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, index=True)  # SUCCESS, FAILED, PENDING, etc.
    
    # Contenu
    output = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    
    # Métriques
    duration = Column(Float, nullable=True)  # Duree d'execution en secondes
    memory_usage = Column(Integer, nullable=True)  # Mémoire utilisée en MB
    cpu_usage = Column(Float, nullable=True)  # CPU utilisé en %
    
    # Dates
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Métadonnées
    metadata = Column(JSON, nullable=True, default=dict)
    
    # Relations
    sprint = relationship("Sprint", back_populates="task_results", lazy="selectin")
    
    # Contraintes
    __table_args__ = (
        CheckConstraint("status IN ('SUCCESS', 'FAILED', 'PENDING', 'RUNNING', 'CIRCUIT_OPEN')", name='chk_task_result_status'),
        Index('idx_task_results_sprint_status', 'sprint_id', 'status'),
        Index('idx_task_results_task_id', 'task_id'),
        Index('idx_task_results_timestamp', 'timestamp'),
    )
    
    def __repr__(self) -> str:
        return f"<TaskResult(id='{self.id}', task_id='{self.task_id}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit le résultat en dictionnaire."""
        return {
            "id": self.id,
            "sprint_id": self.sprint_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "duration": self.duration,
            "memory_usage": self.memory_usage,
            "cpu_usage": self.cpu_usage,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata
        }
    
    @hybrid_property
    def is_success(self) -> bool:
        """Vérifie si le résultat est un succès."""
        return self.status == 'SUCCESS'
    
    @hybrid_property
    def is_failure(self) -> bool:
        """Vérifie si le résultat est un échec."""
        return self.status == 'FAILED'


class Artifact(Base):
    """
    Modele pour les artefacts produits par le pipeline.
    Permet de stocker le code Solidity, les tests, la documentation, etc.
    
    Relations:
        - task: TaskModel parent (many-to-one, optionnel)
    """
    __tablename__ = 'artifacts'
    
    # Identifiants
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True, index=True)
    
    # Informations
    type = Column(String, nullable=False, index=True)  # solidity, test, doc, abi, bytecode, etc.
    name = Column(String, nullable=True, index=True)
    content = Column(Text, nullable=True)
    
    # Métadonnées
    metadata = Column(JSON, nullable=True, default=dict)
    vector = Column(Text, nullable=True)  # Pour le stockage de vecteurs (RAG)
    
    # Version
    version = Column(String, nullable=True, default="1.0.0")
    
    # Dates
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relation
    task = relationship("TaskModel", back_populates="artifacts", lazy="selectin")
    
    # Contraintes
    __table_args__ = (
        CheckConstraint("type IN ('solidity', 'test', 'doc', 'abi', 'bytecode', 'config', 'report', 'other')", name='chk_artifact_type'),
        Index('idx_artifacts_task_type', 'task_id', 'type'),
        Index('idx_artifacts_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        name_display = self.name if self.name else 'N/A'
        return f"<Artifact(id='{self.id}', type='{self.type}', name='{name_display}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'artefact en dictionnaire."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "type": self.type,
            "name": self.name,
            "content": self.content,
            "metadata": self.metadata,
            "vector": self.vector,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
    
    @hybrid_property
    def is_code(self) -> bool:
        """Vérifie si l'artefact est du code source."""
        return self.type in ['solidity', 'javascript', 'typescript', 'python']


# =============================================================================
# ENUMS SUPPLEMENTAIRES
# =============================================================================

class SprintStatus(str, enum.Enum):
    """
    Statuts possibles pour un sprint.
    """
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ArtifactType(str, enum.Enum):
    """
    Types d'artefacts possibles.
    """
    SOLIDITY = "solidity"
    TEST = "test"
    DOCUMENTATION = "doc"
    ABI = "abi"
    BYTECODE = "bytecode"
    CONFIG = "config"
    REPORT = "report"
    OTHER = "other"


# =============================================================================
# EXTENSION DES MODELES PRINCIPAUX AVEC LES RELATIONS
# =============================================================================

# Ajout de la relation 'sprints' sur ProjectModel
if not hasattr(ProjectModel, 'sprints'):
    ProjectModel.sprints = relationship(
        "Sprint", 
        back_populates="project", 
        cascade="all, delete-orphan",
        lazy="selectin"
    )

# Ajout de la relation 'artifacts' sur TaskModel
if not hasattr(TaskModel, 'artifacts'):
    TaskModel.artifacts = relationship(
        "Artifact", 
        back_populates="task", 
        cascade="all, delete-orphan",
        lazy="selectin"
    )

# Ajout de la relation 'logs' sur TaskModel
if not hasattr(TaskModel, 'logs'):
    TaskModel.logs = relationship(
        "ExecutionLogModel",
        backref="task",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def get_model_by_name(name: str):
    """
    Récupère un modèle par son nom.
    
    Args:
        name (str): Nom du modèle
        
    Returns:
        type: Classe du modèle ou None
    """
    models = {
        'ProjectModel': ProjectModel,
        'TaskModel': TaskModel,
        'ExecutionLogModel': ExecutionLogModel,
        'SkillRecordModel': SkillRecordModel,
        'Sprint': Sprint,
        'TaskResult': TaskResult,
        'Artifact': Artifact
    }
    return models.get(name)


def get_all_models() -> List[type]:
    """
    Récupère tous les modèles ORM.
    
    Returns:
        List[type]: Liste des classes de modèles
    """
    return [
        ProjectModel,
        TaskModel,
        ExecutionLogModel,
        SkillRecordModel,
        Sprint,
        TaskResult,
        Artifact
    ]


def get_model_tablenames() -> List[str]:
    """
    Récupère les noms de toutes les tables.
    
    Returns:
        List[str]: Liste des noms de tables
    """
    return [
        ProjectModel.__tablename__,
        TaskModel.__tablename__,
        ExecutionLogModel.__tablename__,
        SkillRecordModel.__tablename__,
        Sprint.__tablename__,
        TaskResult.__tablename__,
        Artifact.__tablename__
    ]


def get_models_with_relations() -> Dict[str, List[str]]:
    """
    Récupère les relations entre les modèles.
    
    Returns:
        Dict[str, List[str]]: Dictionnaire des relations
    """
    return {
        'ProjectModel': ['Sprint', 'TaskModel'],
        'Sprint': ['ProjectModel', 'TaskResult'],
        'TaskModel': ['ProjectModel', 'ExecutionLogModel', 'Artifact'],
        'TaskResult': ['Sprint'],
        'ExecutionLogModel': ['TaskModel'],
        'Artifact': ['TaskModel'],
        'SkillRecordModel': []  # Standalone
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Base declarative (essentielle pour les migrations)
    "Base",
    
    # Modeles principaux du pipeline (Sprint 1)
    "ProjectModel",
    "ProjectStatus",
    "TaskModel",
    "TaskState",
    "ExecutionLogModel",
    "LogLevel",
    "LogCategory",
    "SkillRecordModel",
    "SkillStatus",
    "SkillScope",
    
    # Modeles supplementaires
    "Sprint",
    "SprintStatus",
    "TaskResult",
    "Artifact",
    "ArtifactType",
    
    # Fonctions utilitaires
    "get_model_by_name",
    "get_all_models",
    "get_model_tablenames",
    "get_models_with_relations"
]