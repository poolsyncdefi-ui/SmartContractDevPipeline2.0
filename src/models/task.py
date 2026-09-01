# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Modèle Tâche
# ==============================================================================
# Fichier: src/models/task.py
# Description: Modèle SQLAlchemy pour la table tasks.
#              Représente une tâche unitaire dans le pipeline.
# ==============================================================================

from sqlalchemy import Column, String, ForeignKey, Integer, JSON, Enum, DateTime, Text, Float
from sqlalchemy.orm import relationship, validates
from src.db.database import Base
import datetime
import enum
import uuid
from typing import List, Dict, Any, Optional, Set


# ==============================================================================
# ENUMS
# ==============================================================================

class TaskState(str, enum.Enum):
    """États possibles d'une tâche."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AUTO_TESTING = "AUTO_TESTING"
    WAITING_HUMAN_VALIDATION = "WAITING_HUMAN_VALIDATION"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CIRCUIT_BROKEN = "CIRCUIT_BROKEN"
    CANCELLED = "CANCELLED"


class TaskPriority(str, enum.Enum):
    """Priorités d'une tâche."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ==============================================================================
# MODÈLE TASK
# ==============================================================================

class TaskModel(Base):
    """
    Modèle ORM pour la table tasks.
    Représente une tâche unitaire dans le pipeline.
    """
    __tablename__ = "tasks"
    
    # ==========================================================================
    # COLONNES
    # ==========================================================================
    
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
        doc="ID du projet parent"
    )
    
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
    
    state = Column(
        Enum(TaskState),
        default=TaskState.PENDING,
        doc="État actuel de la tâche"
    )
    
    priority = Column(
        Enum(TaskPriority),
        default=TaskPriority.NORMAL,
        doc="Priorité de la tâche"
    )
    
    # Compétence à exécuter
    skill_id = Column(
        String(100),
        nullable=False,
        doc="ID de la compétence à exécuter"
    )
    
    # Paramètres de la tâche
    parameters = Column(
        JSON,
        default={},
        doc="Paramètres d'exécution"
    )
    
    # Dépendances
    dependencies = Column(
        JSON,
        default=[],
        doc="IDs des tâches précédentes"
    )
    
    # Résultat
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
    
    # Timeouts
    timeout_seconds = Column(
        Integer,
        default=600,
        doc="Timeout en secondes"
    )
    
    # Validation humaine
    requires_human_validation = Column(
        Integer,
        default=1,  # 1 = true, 0 = false
        doc="Nécessite une validation humaine"
    )
    
    human_validated = Column(
        Integer,
        default=0,
        doc="Validé par un humain"
    )
    
    # Métriques
    duration_seconds = Column(
        Float,
        default=0.0,
        doc="Durée d'exécution en secondes"
    )
    
    # Dates
    created_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
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
    # RELATIONS
    # ==========================================================================
    
    project = relationship(
        "ProjectModel",
        back_populates="tasks",
        doc="Projet parent"
    )
    
    logs_relation = relationship(
        "ExecutionLogModel",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="select",
        doc="Logs d'exécution"
    )
    
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
        return value.strip()
    
    @validates('skill_id')
    def validate_skill_id(self, key: str, value: str) -> str:
        """Valide l'ID de la compétence."""
        if not value or len(value.strip()) < 1:
            raise ValueError("Skill ID cannot be empty")
        return value.strip()
    
    @validates('dependencies')
    def validate_dependencies(self, key: str, value: List[str]) -> List[str]:
        """Valide que les dépendances sont une liste."""
        if not isinstance(value, list):
            raise ValueError("Dependencies must be a list")
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
    # MÉTHODES PUBLIQUES
    # ==========================================================================
    
    def to_dict(self, include_result: bool = False) -> Dict[str, Any]:
        """
        Convertit le modèle en dictionnaire.
        
        Args:
            include_result: Si True, inclut le résultat
            
        Returns:
            Dict[str, Any]: Dictionnaire de la tâche
        """
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "state": self.state.value if self.state else None,
            "priority": self.priority.value if self.priority else None,
            "project_id": self.project_id,
            "skill_id": self.skill_id,
            "dependencies": self.dependencies,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "requires_human_validation": bool(self.requires_human_validation),
            "human_validated": bool(self.human_validated),
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        
        if include_result:
            result["result"] = self.result
            result["error_message"] = self.error_message
            result["logs"] = self.logs[:500] + "..." if len(self.logs) > 500 else self.logs
        
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
            "skill_id": self.skill_id,
            "retry_count": self.retry_count,
            "duration_seconds": self.duration_seconds,
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
        return set(self.dependencies).issubset(completed_task_ids)
    
    def can_retry(self) -> bool:
        """Vérifie si la tâche peut être réessayée."""
        return self.retry_count < self.max_retries
    
    def increment_retry(self) -> int:
        """Incrémente le compteur de tentatives."""
        self.retry_count += 1
        self.updated_at = datetime.datetime.utcnow()
        return self.retry_count
    
    def get_remaining_retries(self) -> int:
        """Retourne le nombre de tentatives restantes."""
        return max(0, self.max_retries - self.retry_count)
    
    def is_terminal(self) -> bool:
        """
        Vérifie si la tâche est dans un état terminal.
        
        Returns:
            bool: True si terminée
        """
        return self.state in [
            TaskState.SUCCESS,
            TaskState.FAILED,
            TaskState.CIRCUIT_BROKEN,
            TaskState.CANCELLED
        ]
    
    def is_running(self) -> bool:
        """Vérifie si la tâche est en cours d'exécution."""
        return self.state in [
            TaskState.RUNNING,
            TaskState.AUTO_TESTING,
            TaskState.WAITING_HUMAN_VALIDATION
        ]
    
    def is_pending(self) -> bool:
        """Vérifie si la tâche est en attente."""
        return self.state == TaskState.PENDING
    
    def is_success(self) -> bool:
        """Vérifie si la tâche a réussi."""
        return self.state == TaskState.SUCCESS
    
    def is_failed(self) -> bool:
        """Vérifie si la tâche a échoué."""
        return self.state in [TaskState.FAILED, TaskState.CIRCUIT_BROKEN]
    
    def mark_started(self) -> None:
        """Marque la tâche comme démarrée."""
        self.state = TaskState.RUNNING
        self.started_at = datetime.datetime.utcnow()
        self.updated_at = datetime.datetime.utcnow()
    
    def mark_success(self, result: Optional[Dict[str, Any]] = None) -> None:
        """
        Marque la tâche comme réussie.
        
        Args:
            result: Résultat de l'exécution (optionnel)
        """
        self.state = TaskState.SUCCESS
        self.completed_at = datetime.datetime.utcnow()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds() if self.started_at else 0.0
        if result:
            self.result = result
        self.updated_at = datetime.datetime.utcnow()
    
    def mark_failed(self, error_message: str, result: Optional[Dict[str, Any]] = None) -> None:
        """
        Marque la tâche comme échouée.
        
        Args:
            error_message: Message d'erreur
            result: Résultat partiel (optionnel)
        """
        self.state = TaskState.FAILED
        self.completed_at = datetime.datetime.utcnow()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds() if self.started_at else 0.0
        self.error_message = error_message
        if result:
            self.result = result
        self.updated_at = datetime.datetime.utcnow()
    
    def mark_circuit_broken(self, error_message: str) -> None:
        """
        Marque la tâche comme circuit broken (trop de tentatives).
        
        Args:
            error_message: Message d'erreur
        """
        self.state = TaskState.CIRCUIT_BROKEN
        self.completed_at = datetime.datetime.utcnow()
        self.error_message = f"Circuit breaker: {error_message}"
        self.updated_at = datetime.datetime.utcnow()
    
    def mark_waiting_human(self) -> None:
        """Marque la tâche comme en attente de validation humaine."""
        self.state = TaskState.WAITING_HUMAN_VALIDATION
        self.updated_at = datetime.datetime.utcnow()
    
    def mark_human_validated(self, approved: bool, comments: Optional[str] = None) -> None:
        """
        Marque la tâche comme validée par un humain.
        
        Args:
            approved: True si approuvé
            comments: Commentaires optionnels
        """
        self.human_validated = 1 if approved else 0
        if comments:
            self.metadata["human_comments"] = comments
        self.updated_at = datetime.datetime.utcnow()
        
        # Si approuvé et déjà en attente, passer en succès
        if approved and self.state == TaskState.WAITING_HUMAN_VALIDATION:
            self.mark_success()
        elif not approved:
            self.state = TaskState.FAILED
            self.completed_at = datetime.datetime.utcnow()
            self.updated_at = datetime.datetime.utcnow()
    
    def add_log(self, log_entry: str) -> None:
        """
        Ajoute une entrée de log.
        
        Args:
            log_entry: Entrée de log
        """
        timestamp = datetime.datetime.utcnow().isoformat()
        self.logs += f"[{timestamp}] {log_entry}\n"
        self.updated_at = datetime.datetime.utcnow()
    
    def get_dependency_depth(self) -> int:
        """
        Retourne la profondeur des dépendances.
        Utile pour l'ordonnancement DAG.
        
        Returns:
            int: Profondeur des dépendances
        """
        return len(self.dependencies)
    
    def get_elapsed_time(self) -> float:
        """
        Retourne le temps écoulé depuis le début de la tâche.
        
        Returns:
            float: Temps écoulé en secondes
        """
        if self.started_at:
            now = datetime.datetime.utcnow()
            return (now - self.started_at).total_seconds()
        return 0.0
    
    def is_timeout(self) -> bool:
        """
        Vérifie si la tâche a dépassé son timeout.
        
        Returns:
            bool: True si timeout
        """
        if self.started_at and self.state in [TaskState.RUNNING, TaskState.AUTO_TESTING]:
            elapsed = self.get_elapsed_time()
            return elapsed > self.timeout_seconds
        return False
    
    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Retourne le graphe des dépendances pour cette tâche.
        Utile pour l'analyse DAG.
        
        Returns:
            Dict[str, List[str]]: Graphe des dépendances
        """
        return {
            self.id: self.dependencies
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
        return TaskModel(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=task_spec.get("name", "Unnamed Task"),
            description=task_spec.get("description", ""),
            skill_id=skill_id,
            parameters=parameters or task_spec.get("parameters", {}),
            dependencies=task_spec.get("depends_on", []),
            requires_human_validation=1 if task_spec.get("requires_human_validation", True) else 0,
            timeout_seconds=task_spec.get("timeout_seconds", 600),
            max_retries=task_spec.get("retry_count", 3),
            priority=TaskPriority(task_spec.get("priority", "normal")),
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
        return TaskModel(
            id=data.get("id", str(uuid.uuid4())),
            project_id=data.get("project_id", ""),
            name=data.get("name", "Unnamed Task"),
            description=data.get("description", ""),
            skill_id=data.get("skill_id", ""),
            parameters=data.get("parameters", {}),
            dependencies=data.get("dependencies", []),
            requires_human_validation=1 if data.get("requires_human_validation", True) else 0,
            timeout_seconds=data.get("timeout_seconds", 600),
            max_retries=data.get("max_retries", 3),
            priority=TaskPriority(data.get("priority", "normal")),
            metadata=data.get("metadata", {}),
        )
    
    # ==========================================================================
    # REPRÉSENTATION
    # ==========================================================================
    
    def __repr__(self) -> str:
        return f"<TaskModel(id={self.id}, name={self.name}, state={self.state})>"
    
    def __str__(self) -> str:
        return f"Task: {self.name} ({self.id}) - State: {self.state.value if self.state else 'N/A'}"


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
        skill_id="erc20_generator",
        parameters={
            "name": "MyToken",
            "symbol": "MTK",
            "initial_supply": 1000000
        },
        dependencies=["task_001", "task_002"],
        max_retries=3,
        timeout_seconds=600
    )
    
    print(f"\n📋 Tâche créée:")
    print(f"  ID: {task.id}")
    print(f"  Nom: {task.name}")
    print(f"  Description: {task.description}")
    print(f"  Skill: {task.skill_id}")
    print(f"  Dépendances: {task.dependencies}")
    print(f"  Timeout: {task.timeout_seconds}s")
    
    # Test des méthodes
    print(f"\n🔄 Test des méthodes:")
    
    # Vérifier l'exécutabilité
    completed = {"task_001", "task_002"}
    print(f"  Exécutable (dépendances satisfaites): {task.is_executable(completed)}")
    
    # Marquer le démarrage
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
    
    # Test des logs
    print(f"\n📋 Logs:")
    print(task.logs)
    
    print("\n✅ Tests terminés.")