# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Modèle Tâche
# ==============================================================================
# Fichier: src/models/task.py
# Description: Modèle SQLAlchemy pour la table tasks.
#              Représente une tâche unitaire dans le pipeline.
#              Supporte les dépendances, les retries, les timeouts et les événements.
# ==============================================================================

from sqlalchemy import Column, String, ForeignKey, Integer, JSON, Enum, DateTime, Text, Float, Boolean, Index
from sqlalchemy.orm import relationship, validates, backref
from sqlalchemy.ext.hybrid import hybrid_property
from src.db.database import Base
import datetime
import enum
import uuid
import json
import re
from typing import List, Dict, Any, Optional, Set, Union
from dataclasses import dataclass, field


# ==============================================================================
# ENUMS
# ==============================================================================

class TaskState(str, enum.Enum):
    """États possibles d'une tâche."""
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    AUTO_TESTING = "AUTO_TESTING"
    WAITING_HUMAN_VALIDATION = "WAITING_HUMAN_VALIDATION"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CIRCUIT_BROKEN = "CIRCUIT_BROKEN"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class TaskPriority(str, enum.Enum):
    """Priorités d'une tâche."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskType(str, enum.Enum):
    """Types de tâches."""
    CONTRACT_GENERATION = "contract_generation"
    TEST_GENERATION = "test_generation"
    SECURITY_AUDIT = "security_audit"
    FORMAL_VERIFICATION = "formal_verification"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    REVIEW = "review"
    ANALYSIS = "analysis"
    OPTIMIZATION = "optimization"
    CUSTOM = "custom"


# ==============================================================================
# MODÈLE TASK
# ==============================================================================

class TaskModel(Base):
    """
    Modèle ORM pour la table tasks.
    Représente une tâche unitaire dans le pipeline.
    
    Relations:
        - project: Projet parent
        - logs: Logs d'exécution associés
    """
    __tablename__ = "tasks"
    
    # ==========================================================================
    # COLONNES
    # ==========================================================================
    
    # Identifiants
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identifiant unique de la tâche (UUID)"
    )
    
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID du projet parent"
    )
    
    # Informations de base
    name = Column(
        String(100),
        nullable=False,
        doc="Nom de la tâche"
    )
    
    description = Column(
        Text,
        default="",
        doc="Description de la tâche"
    )
    
    # Classification
    state = Column(
        Enum(TaskState),
        default=TaskState.PENDING,
        index=True,
        doc="État actuel de la tâche"
    )
    
    priority = Column(
        Enum(TaskPriority),
        default=TaskPriority.NORMAL,
        index=True,
        doc="Priorité de la tâche"
    )
    
    task_type = Column(
        Enum(TaskType),
        default=TaskType.CUSTOM,
        index=True,
        doc="Type de la tâche"
    )
    
    # Compétence
    skill_id = Column(
        String(100),
        nullable=False,
        index=True,
        doc="ID de la compétence à exécuter"
    )
    
    # Paramètres
    parameters = Column(
        JSON,
        default={},
        doc="Paramètres d'exécution"
    )
    
    # Dépendances
    dependencies = Column(
        JSON,
        default=list,
        doc="IDs des tâches précédentes"
    )
    
    # Résultats
    result = Column(
        JSON,
        nullable=True,
        doc="Résultat de l'exécution"
    )
    
    error_message = Column(
        Text,
        nullable=True,
        doc="Message d'erreur si échec"
    )
    
    # Logs
    logs = Column(
        Text,
        default="",
        doc="Logs d'exécution"
    )
    
    # Compteurs
    retry_count = Column(
        Integer,
        default=0,
        doc="Nombre de tentatives"
    )
    
    max_retries = Column(
        Integer,
        default=3,
        doc="Nombre maximum de tentatives"
    )
    
    # Timeout
    timeout_seconds = Column(
        Integer,
        default=600,
        doc="Timeout en secondes"
    )
    
    # Validation humaine
    requires_human_validation = Column(
        Boolean,
        default=True,
        doc="Nécessite une validation humaine"
    )
    
    human_validated = Column(
        Boolean,
        default=False,
        doc="Validé par un humain"
    )
    
    human_validation_comments = Column(
        Text,
        nullable=True,
        doc="Commentaires de validation humaine"
    )
    
    # Métriques
    duration_seconds = Column(
        Float,
        default=0.0,
        doc="Durée d'exécution en secondes"
    )
    
    memory_usage_mb = Column(
        Float,
        nullable=True,
        doc="Mémoire utilisée en MB"
    )
    
    cpu_usage_percent = Column(
        Float,
        nullable=True,
        doc="CPU utilisé en %"
    )
    
    # Indicateurs
    is_retry = Column(
        Boolean,
        default=False,
        doc="Indique si c'est une tentative de retry"
    )
    
    is_manual = Column(
        Boolean,
        default=False,
        doc="Indique si la tâche a été créée manuellement"
    )
    
    # Dates
    created_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        index=True,
        doc="Date de création"
    )
    
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        doc="Date de dernière mise à jour"
    )
    
    started_at = Column(
        DateTime,
        nullable=True,
        doc="Date de début d'exécution"
    )
    
    completed_at = Column(
        DateTime,
        nullable=True,
        doc="Date de fin d'exécution"
    )
    
    # Métadonnées
    metadata = Column(
        JSON,
        default={},
        doc="Métadonnées additionnelles"
    )
    
    # ==========================================================================
    # INDEX
    # ==========================================================================
    
    __table_args__ = (
        Index('idx_tasks_project_state', 'project_id', 'state'),
        Index('idx_tasks_state_priority', 'state', 'priority'),
        Index('idx_tasks_skill_id', 'skill_id'),
        Index('idx_tasks_created_at', 'created_at'),
    )
    
    # ==========================================================================
    # RELATIONS
    # ==========================================================================
    
    project = relationship(
        "ProjectModel",
        back_populates="tasks",
        lazy="selectin",
        doc="Projet parent"
    )
    
    logs = relationship(
        "ExecutionLogModel",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        doc="Logs d'exécution"
    )
    
    artifacts = relationship(
        "Artifact",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        doc="Artefacts produits"
    )
    
    # ==========================================================================
    # HYBRID PROPERTIES
    # ==========================================================================
    
    @hybrid_property
    def is_terminal(self) -> bool:
        """Vérifie si la tâche est dans un état terminal."""
        return self.state in [
            TaskState.SUCCESS,
            TaskState.FAILED,
            TaskState.CIRCUIT_BROKEN,
            TaskState.CANCELLED,
            TaskState.SKIPPED
        ]
    
    @hybrid_property
    def is_running(self) -> bool:
        """Vérifie si la tâche est en cours d'exécution."""
        return self.state in [
            TaskState.RUNNING,
            TaskState.AUTO_TESTING,
            TaskState.WAITING_HUMAN_VALIDATION
        ]
    
    @hybrid_property
    def is_pending(self) -> bool:
        """Vérifie si la tâche est en attente."""
        return self.state == TaskState.PENDING
    
    @hybrid_property
    def is_success(self) -> bool:
        """Vérifie si la tâche a réussi."""
        return self.state == TaskState.SUCCESS
    
    @hybrid_property
    def is_failed(self) -> bool:
        """Vérifie si la tâche a échoué."""
        return self.state in [TaskState.FAILED, TaskState.CIRCUIT_BROKEN]
    
    @hybrid_property
    def is_blocked(self) -> bool:
        """Vérifie si la tâche est bloquée."""
        return self.state == TaskState.BLOCKED
    
    @hybrid_property
    def is_ready(self) -> bool:
        """Vérifie si la tâche est prête à être exécutée."""
        return self.state == TaskState.READY
    
    @hybrid_property
    def elapsed_time(self) -> float:
        """Temps écoulé depuis le début de la tâche."""
        if self.started_at:
            now = datetime.datetime.utcnow()
            return (now - self.started_at).total_seconds()
        return 0.0
    
    @hybrid_property
    def remaining_time(self) -> float:
        """Temps restant avant le timeout."""
        if self.started_at:
            elapsed = self.elapsed_time
            return max(0, self.timeout_seconds - elapsed)
        return self.timeout_seconds
    
    @hybrid_property
    def is_timeout(self) -> bool:
        """Vérifie si la tâche a dépassé son timeout."""
        if self.started_at and self.is_running:
            return self.elapsed_time > self.timeout_seconds
        return False
    
    @hybrid_property
    def completion_rate(self) -> float:
        """Taux de complétion de la tâche (0-100)."""
        if self.is_terminal:
            return 100.0 if self.is_success else 0.0
        return 50.0  # En cours d'exécution
    
    # ==========================================================================
    # VALIDATEURS
    # ==========================================================================
    
    @validates('name')
    def validate_name(self, key: str, value: str) -> str:
        """Valide le nom de la tâche."""
        if not value or len(value.strip()) < 1:
            raise ValueError("Task name cannot be empty")
        if len(value) > 100:
            raise ValueError("Task name cannot exceed 100 characters")
        if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', value):
            raise ValueError("Task name contains invalid characters")
        return value.strip()
    
    @validates('skill_id')
    def validate_skill_id(self, key: str, value: str) -> str:
        """Valide l'ID de la compétence."""
        if not value or len(value.strip()) < 1:
            raise ValueError("Skill ID cannot be empty")
        if not re.match(r'^[a-zA-Z0-9_\-]+$', value):
            raise ValueError("Skill ID contains invalid characters")
        return value.strip()
    
    @validates('dependencies')
    def validate_dependencies(self, key: str, value: List[str]) -> List[str]:
        """Valide que les dépendances sont une liste."""
        if not isinstance(value, list):
            raise ValueError("Dependencies must be a list")
        # Vérifier qu'il n'y a pas de doublons
        if len(value) != len(set(value)):
            raise ValueError("Dependencies contain duplicates")
        return value
    
    @validates('retry_count', 'max_retries')
    def validate_retry_counts(self, key: str, value: int) -> int:
        """Valide les compteurs de retry."""
        if value < 0:
            raise ValueError(f"{key} cannot be negative")
        if key == 'max_retries' and value > 10:
            raise ValueError("Max retries cannot exceed 10")
        return value
    
    @validates('timeout_seconds')
    def validate_timeout(self, key: str, value: int) -> int:
        """Valide le timeout."""
        if value <= 0:
            raise ValueError("Timeout must be greater than 0")
        if value > 3600:
            raise ValueError("Timeout cannot exceed 3600 seconds (1 hour)")
        return value
    
    # ==========================================================================
    # MÉTHODES DE TRANSITION D'ÉTAT
    # ==========================================================================
    
    def mark_ready(self) -> None:
        """Marque la tâche comme prête (dépendances satisfaites)."""
        if self.state == TaskState.PENDING:
            self.state = TaskState.READY
            self.updated_at = datetime.datetime.utcnow()
            self._add_audit_log("ready", {"previous_state": TaskState.PENDING.value})
    
    def mark_started(self) -> None:
        """Marque la tâche comme démarrée."""
        old_state = self.state
        self.state = TaskState.RUNNING
        self.started_at = datetime.datetime.utcnow()
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("started", {"previous_state": old_state.value if old_state else None})
    
    def mark_auto_testing(self) -> None:
        """Marque la tâche comme en phase de test automatique."""
        old_state = self.state
        self.state = TaskState.AUTO_TESTING
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("auto_testing", {"previous_state": old_state.value if old_state else None})
    
    def mark_success(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Marque la tâche comme réussie."""
        old_state = self.state
        self.state = TaskState.SUCCESS
        self.completed_at = datetime.datetime.utcnow()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds() if self.started_at else 0.0
        if result:
            self.result = result
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("success", {"previous_state": old_state.value if old_state else None})
    
    def mark_failed(self, error_message: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Marque la tâche comme échouée."""
        old_state = self.state
        self.state = TaskState.FAILED
        self.completed_at = datetime.datetime.utcnow()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds() if self.started_at else 0.0
        self.error_message = error_message
        if result:
            self.result = result
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("failed", {
            "previous_state": old_state.value if old_state else None,
            "error": error_message
        })
    
    def mark_circuit_broken(self, error_message: str) -> None:
        """Marque la tâche comme circuit broken (trop de tentatives)."""
        old_state = self.state
        self.state = TaskState.CIRCUIT_BROKEN
        self.completed_at = datetime.datetime.utcnow()
        self.error_message = f"Circuit breaker: {error_message}"
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("circuit_broken", {
            "previous_state": old_state.value if old_state else None,
            "error": error_message
        })
    
    def mark_waiting_human(self) -> None:
        """Marque la tâche comme en attente de validation humaine."""
        old_state = self.state
        self.state = TaskState.WAITING_HUMAN_VALIDATION
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("waiting_human", {"previous_state": old_state.value if old_state else None})
    
    def mark_human_validated(self, approved: bool, comments: Optional[str] = None) -> None:
        """
        Marque la tâche comme validée par un humain.
        
        Args:
            approved: True si approuvé
            comments: Commentaires optionnels
        """
        self.human_validated = approved
        if comments:
            self.human_validation_comments = comments
        self.updated_at = datetime.datetime.utcnow()
        
        self._add_audit_log("human_validated", {
            "approved": approved,
            "comments": comments
        })
        
        # Si approuvé et déjà en attente, passer en succès
        if approved and self.state == TaskState.WAITING_HUMAN_VALIDATION:
            self.mark_success()
        elif not approved and self.state == TaskState.WAITING_HUMAN_VALIDATION:
            self.mark_failed("Rejected by human validation")
    
    def mark_cancelled(self, reason: Optional[str] = None) -> None:
        """Marque la tâche comme annulée."""
        old_state = self.state
        self.state = TaskState.CANCELLED
        self.completed_at = datetime.datetime.utcnow()
        if reason:
            self.error_message = f"Cancelled: {reason}"
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("cancelled", {
            "previous_state": old_state.value if old_state else None,
            "reason": reason
        })
    
    def mark_blocked(self, reason: Optional[str] = None) -> None:
        """Marque la tâche comme bloquée."""
        old_state = self.state
        self.state = TaskState.BLOCKED
        if reason:
            self.error_message = f"Blocked: {reason}"
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("blocked", {
            "previous_state": old_state.value if old_state else None,
            "reason": reason
        })
    
    def mark_skipped(self, reason: Optional[str] = None) -> None:
        """Marque la tâche comme ignorée."""
        old_state = self.state
        self.state = TaskState.SKIPPED
        self.completed_at = datetime.datetime.utcnow()
        if reason:
            self.error_message = f"Skipped: {reason}"
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("skipped", {
            "previous_state": old_state.value if old_state else None,
            "reason": reason
        })
    
    # ==========================================================================
    # MÉTHODES PUBLIQUES
    # ==========================================================================
    
    def to_dict(self, include_result: bool = False, include_logs: bool = False) -> Dict[str, Any]:
        """
        Convertit le modèle en dictionnaire.
        
        Args:
            include_result: Si True, inclut le résultat
            include_logs: Si True, inclut les logs
            
        Returns:
            Dict[str, Any]: Dictionnaire de la tâche
        """
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "state": self.state.value if self.state else None,
            "priority": self.priority.value if self.priority else None,
            "task_type": self.task_type.value if self.task_type else None,
            "project_id": self.project_id,
            "skill_id": self.skill_id,
            "dependencies": self.dependencies,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "requires_human_validation": self.requires_human_validation,
            "human_validated": self.human_validated,
            "duration_seconds": self.duration_seconds,
            "is_terminal": self.is_terminal,
            "is_running": self.is_running,
            "is_timeout": self.is_timeout,
            "completion_rate": self.completion_rate,
            "elapsed_time": self.elapsed_time,
            "remaining_time": self.remaining_time,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        
        if include_result:
            result["result"] = self.result
            result["error_message"] = self.error_message
        
        if include_logs:
            result["logs"] = self.logs
        
        return result
    
    def to_summary(self) -> Dict[str, Any]:
        """
        Retourne un résumé de la tâche.
        
        Returns:
            Dict[str, Any]: Résumé de la tâche
        """
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state.value if self.state else None,
            "priority": self.priority.value if self.priority else None,
            "task_type": self.task_type.value if self.task_type else None,
            "skill_id": self.skill_id,
            "retry_count": self.retry_count,
            "duration_seconds": self.duration_seconds,
            "is_terminal": self.is_terminal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    def is_executable(self, completed_task_ids: Set[str]) -> bool:
        """
        Vérifie si la tâche peut être exécutée.
        Toutes les dépendances doivent être dans completed_task_ids.
        
        Args:
            completed_task_ids: Ensemble des IDs de tâches terminées
            
        Returns:
            bool: True si exécutable
        """
        if self.state not in [TaskState.PENDING, TaskState.BLOCKED]:
            return False
        return set(self.dependencies).issubset(completed_task_ids)
    
    def can_retry(self) -> bool:
        """Vérifie si la tâche peut être réessayée."""
        return self.retry_count < self.max_retries and self.is_failed
    
    def increment_retry(self) -> int:
        """Incrémente le compteur de tentatives."""
        self.retry_count += 1
        self.is_retry = True
        self.updated_at = datetime.datetime.utcnow()
        self._add_audit_log("retry", {"retry_count": self.retry_count})
        return self.retry_count
    
    def get_remaining_retries(self) -> int:
        """Retourne le nombre de tentatives restantes."""
        return max(0, self.max_retries - self.retry_count)
    
    def get_dependency_depth(self) -> int:
        """
        Retourne la profondeur des dépendances.
        Utile pour l'ordonnancement DAG.
        
        Returns:
            int: Profondeur des dépendances
        """
        return len(self.dependencies)
    
    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Retourne le graphe des dépendances pour cette tâche.
        Utile pour l'analyse DAG.
        
        Returns:
            Dict[str, List[str]]: Graphe des dépendances
        """
        return {self.id: self.dependencies}
    
    # ==========================================================================
    # GESTION DES LOGS
    # ==========================================================================
    
    def add_log(self, log_entry: str) -> None:
        """
        Ajoute une entrée de log.
        
        Args:
            log_entry: Entrée de log
        """
        timestamp = datetime.datetime.utcnow().isoformat()
        self.logs += f"[{timestamp}] {log_entry}\n"
        self.updated_at = datetime.datetime.utcnow()
    
    def get_logs(self, limit: Optional[int] = None) -> List[str]:
        """
        Récupère les logs de la tâche.
        
        Args:
            limit: Nombre maximum de lignes
            
        Returns:
            List[str]: Liste des logs
        """
        logs = self.logs.split('\n')
        logs = [log for log in logs if log.strip()]
        if limit:
            return logs[-limit:]
        return logs
    
    # ==========================================================================
    # MÉTADONNÉES
    # ==========================================================================
    
    def add_metadata(self, key: str, value: Any) -> None:
        """Ajoute une métadonnée."""
        if not self.metadata:
            self.metadata = {}
        self.metadata[key] = value
        self.updated_at = datetime.datetime.utcnow()
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Récupère une métadonnée."""
        if not self.metadata:
            return default
        return self.metadata.get(key, default)
    
    def remove_metadata(self, key: str) -> None:
        """Supprime une métadonnée."""
        if self.metadata and key in self.metadata:
            del self.metadata[key]
            self.updated_at = datetime.datetime.utcnow()
    
    # ==========================================================================
    # AUDIT LOG
    # ==========================================================================
    
    def _add_audit_log(self, action: str, data: Dict[str, Any]) -> None:
        """Ajoute une entrée d'audit log."""
        if not self.metadata:
            self.metadata = {}
        if "audit_logs" not in self.metadata:
            self.metadata["audit_logs"] = []
        self.metadata["audit_logs"].append({
            "action": action,
            "data": data,
            "timestamp": datetime.datetime.utcnow().isoformat()
        })
    
    def get_audit_logs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Récupère les logs d'audit."""
        logs = self.metadata.get("audit_logs", []) if self.metadata else []
        if limit:
            return logs[-limit:]
        return logs
    
    # ==========================================================================
    # STATISTIQUES
    # ==========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de la tâche.
        
        Returns:
            Dict[str, Any]: Statistiques de la tâche
        """
        return {
            "id": self.id,
            "state": self.state.value if self.state else None,
            "duration_seconds": self.duration_seconds,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "is_terminal": self.is_terminal,
            "is_success": self.is_success,
            "is_failed": self.is_failed,
            "elapsed_time": self.elapsed_time,
            "remaining_time": self.remaining_time,
            "timeout_percentage": (self.elapsed_time / self.timeout_seconds * 100) if self.started_at else 0,
            "memory_usage_mb": self.memory_usage_mb,
            "cpu_usage_percent": self.cpu_usage_percent,
            "completion_rate": self.completion_rate,
        }
    
    # ==========================================================================
    # MÉTHODES STATIQUES
    # ==========================================================================
    
    @staticmethod
    def create_from_spec(
        task_spec: Dict[str, Any],
        project_id: str,
        skill_id: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> "TaskModel":
        """
        Crée une tâche à partir d'une spécification.
        
        Args:
            task_spec: Spécification de la tâche
            project_id: ID du projet
            skill_id: ID de la compétence
            parameters: Paramètres optionnels
            
        Returns:
            TaskModel: Instance de la tâche
        """
        # Déterminer le type de tâche
        task_type_str = task_spec.get("type", "custom")
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.CUSTOM
        
        return TaskModel(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=task_spec.get("name", "Unnamed Task"),
            description=task_spec.get("description", ""),
            task_type=task_type,
            skill_id=skill_id,
            parameters=parameters or task_spec.get("parameters", {}),
            dependencies=task_spec.get("depends_on", []),
            requires_human_validation=task_spec.get("requires_human_validation", True),
            timeout_seconds=task_spec.get("timeout_seconds", 600),
            max_retries=task_spec.get("retry_count", 3),
            priority=TaskPriority(task_spec.get("priority", "normal")),
            metadata=task_spec.get("metadata", {}),
        )
    
    @staticmethod
    def create_from_dict(data: Dict[str, Any]) -> "TaskModel":
        """
        Crée une tâche à partir d'un dictionnaire.
        
        Args:
            data: Dictionnaire des données
            
        Returns:
            TaskModel: Instance de la tâche
        """
        # Déterminer le type de tâche
        task_type_str = data.get("task_type", "custom")
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.CUSTOM
        
        return TaskModel(
            id=data.get("id", str(uuid.uuid4())),
            project_id=data.get("project_id", ""),
            name=data.get("name", "Unnamed Task"),
            description=data.get("description", ""),
            task_type=task_type,
            skill_id=data.get("skill_id", ""),
            parameters=data.get("parameters", {}),
            dependencies=data.get("dependencies", []),
            requires_human_validation=data.get("requires_human_validation", True),
            timeout_seconds=data.get("timeout_seconds", 600),
            max_retries=data.get("max_retries", 3),
            priority=TaskPriority(data.get("priority", "normal")),
            metadata=data.get("metadata", {}),
            is_manual=data.get("is_manual", True),
        )
    
    # ==========================================================================
    # MÉTHODES MAGIQUES
    # ==========================================================================
    
    def __repr__(self) -> str:
        return f"<TaskModel(id={self.id}, name={self.name}, state={self.state})>"
    
    def __str__(self) -> str:
        return f"Task: {self.name} ({self.id}) - State: {self.state.value if self.state else 'N/A'}"
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TaskModel):
            return False
        return self.id == other.id
    
    def __hash__(self) -> int:
        return hash(self.id)


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Modèle Tâche")
    print("=" * 60)
    
    # Création d'une tâche
    task = TaskModel(
        id=str(uuid.uuid4()),
        project_id="proj_123",
        name="Générer le contrat ERC20",
        description="Génère un contrat ERC20 avec mint et burn",
        task_type=TaskType.CONTRACT_GENERATION,
        skill_id="erc20_generator",
        parameters={
            "name": "MyToken",
            "symbol": "MTK",
            "initial_supply": 1000000
        },
        dependencies=["task_001", "task_002"],
        max_retries=3,
        timeout_seconds=600,
        priority=TaskPriority.HIGH
    )
    
    print(f"\n📋 Tâche créée:")
    print(f"  ID: {task.id}")
    print(f"  Nom: {task.name}")
    print(f"  Description: {task.description}")
    print(f"  Type: {task.task_type.value if task.task_type else 'N/A'}")
    print(f"  Skill: {task.skill_id}")
    print(f"  Dépendances: {task.dependencies}")
    print(f"  Timeout: {task.timeout_seconds}s")
    print(f"  Priorité: {task.priority.value if task.priority else 'N/A'}")
    
    # Test des méthodes
    print(f"\n🔄 Test des méthodes:")
    
    # Vérifier l'exécutabilité
    completed = {"task_001", "task_002"}
    print(f"  Exécutable (dépendances satisfaites): {task.is_executable(completed)}")
    
    # Marquer le démarrage
    task.mark_ready()
    print(f"  Ready: {task.state.value}")
    
    task.mark_started()
    print(f"  Démarrage: {task.started_at}")
    print(f"  State: {task.state.value}")
    
    # Ajouter un log
    task.add_log("Début de l'exécution de la compétence")
    task.add_log("Compilation réussie")
    
    # Simuler un succès
    task.mark_success({
        "contract_code": "contract MyToken { ... }",
        "abi": ["function transfer", "function approve"]
    })
    
    print(f"  Succès: {task.state.value}")
    print(f"  Durée: {task.duration_seconds}s")
    print(f"  Résultat: {task.result}")
    
    # Test des hybrid properties
    print(f"\n📊 Hybrid Properties:")
    print(f"  Terminal: {task.is_terminal}")
    print(f"  Success: {task.is_success}")
    print(f"  Completion rate: {task.completion_rate}%")
    
    # Test des logs
    print(f"\n📋 Logs:")
    for log in task.get_logs():
        print(f"  {log}")
    
    # Test des statistiques
    stats = task.get_statistics()
    print(f"\n📊 Statistiques:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n✅ Tests terminés.")