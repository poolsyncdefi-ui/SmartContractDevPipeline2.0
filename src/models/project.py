# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Modèle Projet
# ==============================================================================
# Fichier: src/models/project.py
# Description: Modèle SQLAlchemy pour la table projects.
#              Représente un projet de smart contract avec son état et sa configuration.
#              Supporte les relations, les tags, les métriques et les événements.
# ==============================================================================

from sqlalchemy import Column, String, DateTime, Enum, Text, JSON, Integer, Boolean, Index
from sqlalchemy.orm import relationship, validates, backref
from sqlalchemy.ext.hybrid import hybrid_property
from src.db.database import Base
import datetime
import enum
import uuid
import json
import yaml
import re
from typing import Optional, Dict, Any, List, Set, Union
from dataclasses import dataclass, field


# ==============================================================================
# ENUMS
# ==============================================================================

class ProjectStatus(str, enum.Enum):
    """Statuts possibles d'un projet."""
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"
    ON_HOLD = "ON_HOLD"


class ProjectChain(str, enum.Enum):
    """Chaînes blockchain supportées."""
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    SOLANA = "solana"
    BSC = "bsc"
    AVALANCHE = "avalanche"
    FANTOM = "fantom"
    CELO = "celo"
    NEAR = "near"


class ProjectPriority(str, enum.Enum):
    """Priorités d'un projet."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectCategory(str, enum.Enum):
    """Catégories de projets."""
    DEFI = "defi"
    NFT = "nft"
    GAMING = "gaming"
    DAO = "dao"
    INFRASTRUCTURE = "infrastructure"
    TOOLING = "tooling"
    BRIDGE = "bridge"
    OTHER = "other"


# ==============================================================================
# MODÈLE PROJECT
# ==============================================================================

class ProjectModel(Base):
    """
    Modèle ORM pour la table projects.
    Représente un projet de smart contract avec son état et sa configuration.
    
    Relations:
        - sprints: Sprints associés au projet
        - tasks: Tâches du projet
        - artifacts: Artefacts du projet
    """
    __tablename__ = "projects"
    
    # ==========================================================================
    # COLONNES
    # ==========================================================================
    
    # Identifiants
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identifiant unique du projet (UUID)"
    )
    
    # Informations de base
    name = Column(
        String(100),
        nullable=False,
        index=True,
        doc="Nom du projet"
    )
    
    description = Column(
        Text,
        default="",
        doc="Description détaillée du projet"
    )
    
    # Statut et classification
    status = Column(
        Enum(ProjectStatus),
        default=ProjectStatus.CREATED,
        index=True,
        doc="Statut actuel du projet"
    )
    
    priority = Column(
        Enum(ProjectPriority),
        default=ProjectPriority.MEDIUM,
        doc="Priorité du projet"
    )
    
    category = Column(
        Enum(ProjectCategory),
        default=ProjectCategory.OTHER,
        index=True,
        doc="Catégorie du projet"
    )
    
    # Blockchain
    chain = Column(
        Enum(ProjectChain),
        default=ProjectChain.ETHEREUM,
        index=True,
        doc="Blockchain cible"
    )
    
    # Configuration et spécification
    config = Column(
        JSON,
        default={},
        doc="Configuration complète du projet (ProjectConfig)"
    )
    
    spec_yaml = Column(
        Text,
        nullable=False,
        doc="Spécification YAML du projet"
    )
    
    version = Column(
        String(20),
        default="1.0.0",
        doc="Version du projet (semver)"
    )
    
    # Métadonnées
    metadata = Column(
        JSON,
        default={},
        doc="Métadonnées additionnelles (tags, labels, etc.)"
    )
    
    tags = Column(
        JSON,
        default=list,
        doc="Tags du projet pour la recherche"
    )
    
    # Compteurs
    task_count = Column(
        Integer,
        default=0,
        doc="Nombre total de tâches"
    )
    
    completed_task_count = Column(
        Integer,
        default=0,
        doc="Nombre de tâches terminées"
    )
    
    failed_task_count = Column(
        Integer,
        default=0,
        doc="Nombre de tâches échouées"
    )
    
    # Indicateurs
    is_template = Column(
        Boolean,
        default=False,
        doc="Projet est un template"
    )
    
    is_public = Column(
        Boolean,
        default=False,
        doc="Projet est public"
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
        doc="Date de début du projet"
    )
    
    completed_at = Column(
        DateTime,
        nullable=True,
        doc="Date de fin du projet"
    )
    
    archived_at = Column(
        DateTime,
        nullable=True,
        doc="Date d'archivage"
    )
    
    # Métriques de sécurité
    security_score = Column(
        Integer,
        default=0,
        doc="Score de sécurité (0-100)"
    )
    
    quality_score = Column(
        Integer,
        default=0,
        doc="Score de qualité (0-100)"
    )
    
    # ==========================================================================
    # INDEX
    # ==========================================================================
    
    __table_args__ = (
        Index('idx_projects_status_chain', 'status', 'chain'),
        Index('idx_projects_category_priority', 'category', 'priority'),
        Index('idx_projects_created_at', 'created_at'),
        Index('idx_projects_name', 'name'),
    )
    
    # ==========================================================================
    # RELATIONS
    # ==========================================================================
    
    sprints = relationship(
        "Sprint",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        doc="Sprints du projet"
    )
    
    tasks = relationship(
        "TaskModel",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        doc="Tâches du projet"
    )
    
    artifacts = relationship(
        "Artifact",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        doc="Artefacts du projet"
    )
    
    # ==========================================================================
    # HYBRID PROPERTIES
    # ==========================================================================
    
    @hybrid_property
    def completion_rate(self) -> float:
        """Taux de complétion du projet."""
        if self.task_count == 0:
            return 0.0
        return round((self.completed_task_count / self.task_count) * 100, 2)
    
    @hybrid_property
    def failure_rate(self) -> float:
        """Taux d'échec du projet."""
        if self.task_count == 0:
            return 0.0
        return round((self.failed_task_count / self.task_count) * 100, 2)
    
    @hybrid_property
    def is_active(self) -> bool:
        """Vérifie si le projet est actif."""
        return self.status in [ProjectStatus.CREATED, ProjectStatus.IN_PROGRESS]
    
    @hybrid_property
    def is_completed(self) -> bool:
        """Vérifie si le projet est terminé."""
        return self.status == ProjectStatus.COMPLETED
    
    @hybrid_property
    def is_archived(self) -> bool:
        """Vérifie si le projet est archivé."""
        return self.status == ProjectStatus.ARCHIVED
    
    @hybrid_property
    def age_days(self) -> float:
        """Âge du projet en jours."""
        if not self.created_at:
            return 0.0
        return (datetime.datetime.utcnow() - self.created_at).total_seconds() / (24 * 3600)
    
    @hybrid_property
    def duration_days(self) -> Optional[float]:
        """Durée du projet en jours."""
        if not self.started_at or not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds() / (24 * 3600)
    
    # ==========================================================================
    # VALIDATEURS
    # ==========================================================================
    
    @validates('name')
    def validate_name(self, key: str, value: str) -> str:
        """Valide le nom du projet."""
        if not value or len(value.strip()) < 1:
            raise ValueError("Project name cannot be empty")
        if len(value) > 100:
            raise ValueError("Project name cannot exceed 100 characters")
        if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', value):
            raise ValueError("Project name contains invalid characters")
        return value.strip()
    
    @validates('version')
    def validate_version(self, key: str, value: str) -> str:
        """Valide le format de la version (semver)."""
        if not re.match(r'^\d+\.\d+\.\d+$', value):
            raise ValueError(f"Invalid version format: '{value}'. Use semver (X.Y.Z)")
        return value
    
    @validates('spec_yaml')
    def validate_spec_yaml(self, key: str, value: str) -> str:
        """Valide que la spécification YAML est valide."""
        if not value or len(value.strip()) < 1:
            raise ValueError("Project specification cannot be empty")
        
        try:
            yaml.safe_load(value)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML specification: {e}")
        
        return value
    
    @validates('security_score')
    def validate_security_score(self, key: str, value: int) -> int:
        """Valide le score de sécurité."""
        if not 0 <= value <= 100:
            raise ValueError("Security score must be between 0 and 100")
        return value
    
    @validates('quality_score')
    def validate_quality_score(self, key: str, value: int) -> int:
        """Valide le score de qualité."""
        if not 0 <= value <= 100:
            raise ValueError("Quality score must be between 0 and 100")
        return value
    
    # ==========================================================================
    # MÉTHODES PUBLIQUES
    # ==========================================================================
    
    def to_dict(self, include_config: bool = False, include_relations: bool = False) -> Dict[str, Any]:
        """
        Convertit le modèle en dictionnaire.
        
        Args:
            include_config: Si True, inclut la configuration complète
            include_relations: Si True, inclut les relations
            
        Returns:
            Dict[str, Any]: Dictionnaire du projet
        """
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value if self.status else None,
            "priority": self.priority.value if self.priority else None,
            "category": self.category.value if self.category else None,
            "chain": self.chain.value if self.chain else None,
            "version": self.version,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "failed_task_count": self.failed_task_count,
            "completion_rate": self.completion_rate,
            "failure_rate": self.failure_rate,
            "security_score": self.security_score,
            "quality_score": self.quality_score,
            "is_template": self.is_template,
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "age_days": self.age_days,
            "duration_days": self.duration_days,
            "tags": self.get_tags(),
        }
        
        if include_config:
            result["config"] = self.config
            result["metadata"] = self.metadata
            result["spec_yaml"] = self.spec_yaml
        
        if include_relations:
            result["sprints"] = [s.to_dict() for s in self.sprints] if self.sprints else []
            result["tasks"] = [t.to_dict() for t in self.tasks] if self.tasks else []
        
        return result
    
    def to_summary(self) -> Dict[str, Any]:
        """
        Retourne un résumé du projet.
        
        Returns:
            Dict[str, Any]: Résumé du projet
        """
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value if self.status else None,
            "priority": self.priority.value if self.priority else None,
            "category": self.category.value if self.category else None,
            "chain": self.chain.value if self.chain else None,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "completion_rate": self.completion_rate,
            "security_score": self.security_score,
            "quality_score": self.quality_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "tags": self.get_tags()[:5],  # Limité à 5 tags
        }
    
    def update_status(self, new_status: ProjectStatus, reason: Optional[str] = None) -> None:
        """
        Met à jour le statut du projet.
        
        Args:
            new_status: Nouveau statut
            reason: Raison du changement (optionnel)
        """
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.datetime.utcnow()
        
        # Mise à jour des dates spécifiques
        if new_status == ProjectStatus.IN_PROGRESS and not self.started_at:
            self.started_at = datetime.datetime.utcnow()
        elif new_status == ProjectStatus.COMPLETED:
            self.completed_at = datetime.datetime.utcnow()
        elif new_status == ProjectStatus.ARCHIVED:
            self.archived_at = datetime.datetime.utcnow()
        
        # Log du changement
        if reason:
            self._add_audit_log("status_change", {
                "old_status": old_status.value if old_status else None,
                "new_status": new_status.value if new_status else None,
                "reason": reason,
                "timestamp": datetime.datetime.utcnow().isoformat()
            })
    
    def increment_task_count(self) -> None:
        """Incrémente le compteur de tâches."""
        self.task_count += 1
        self.updated_at = datetime.datetime.utcnow()
    
    def increment_completed_tasks(self) -> None:
        """Incrémente le compteur de tâches terminées."""
        self.completed_task_count += 1
        self.updated_at = datetime.datetime.utcnow()
        self._check_completion()
    
    def increment_failed_tasks(self) -> None:
        """Incrémente le compteur de tâches échouées."""
        self.failed_task_count += 1
        self.updated_at = datetime.datetime.utcnow()
    
    def _check_completion(self) -> None:
        """Vérifie si le projet est terminé."""
        if self.task_count > 0 and self.completed_task_count >= self.task_count:
            if self.status not in [ProjectStatus.COMPLETED, ProjectStatus.ARCHIVED]:
                self.update_status(ProjectStatus.COMPLETED, "All tasks completed")
    
    def get_completion_rate(self) -> float:
        """
        Calcule le taux de complétion du projet.
        
        Returns:
            float: Taux de complétion en pourcentage (0-100)
        """
        return self.completion_rate
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Récupère une valeur de la configuration.
        
        Args:
            key: Clé de la configuration (peut être dotée, ex: "deployment.safe_address")
            default: Valeur par défaut
            
        Returns:
            Any: Valeur de la configuration
        """
        if not self.config:
            return default
        
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set_config_value(self, key: str, value: Any) -> None:
        """
        Définit une valeur dans la configuration.
        
        Args:
            key: Clé de la configuration (peut être dotée)
            value: Valeur à définir
        """
        if not self.config:
            self.config = {}
        
        keys = key.split(".")
        target = self.config
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self.updated_at = datetime.datetime.utcnow()
    
    # ==========================================================================
    # GESTION DES TAGS
    # ==========================================================================
    
    def get_tags(self) -> List[str]:
        """Récupère les tags du projet."""
        if not self.tags:
            return []
        if isinstance(self.tags, list):
            return self.tags
        try:
            return json.loads(self.tags) if isinstance(self.tags, str) else []
        except json.JSONDecodeError:
            return []
    
    def set_tags(self, tags: List[str]) -> None:
        """Définit les tags du projet."""
        self.tags = tags if tags else []
        self.updated_at = datetime.datetime.utcnow()
    
    def add_tag(self, tag: str) -> None:
        """Ajoute un tag au projet."""
        current_tags = self.get_tags()
        if tag not in current_tags:
            current_tags.append(tag)
            self.set_tags(current_tags)
    
    def remove_tag(self, tag: str) -> None:
        """Supprime un tag du projet."""
        current_tags = self.get_tags()
        if tag in current_tags:
            current_tags.remove(tag)
            self.set_tags(current_tags)
    
    def has_tag(self, tag: str) -> bool:
        """Vérifie si un tag est présent."""
        return tag in self.get_tags()
    
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
        Retourne les statistiques du projet.
        
        Returns:
            Dict[str, Any]: Statistiques du projet
        """
        return {
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "failed_task_count": self.failed_task_count,
            "completion_rate": self.completion_rate,
            "failure_rate": self.failure_rate,
            "security_score": self.security_score,
            "quality_score": self.quality_score,
            "age_days": self.age_days,
            "duration_days": self.duration_days,
            "sprint_count": len(self.sprints) if self.sprints else 0,
            "artifact_count": len(self.artifacts) if self.artifacts else 0,
            "is_active": self.is_active,
            "is_completed": self.is_completed,
        }
    
    # ==========================================================================
    # MÉTHODES STATIQUES
    # ==========================================================================
    
    @staticmethod
    def create_from_config(
        name: str,
        spec_yaml: str,
        config: Optional[Dict[str, Any]] = None,
        priority: Optional[ProjectPriority] = None,
        category: Optional[ProjectCategory] = None,
        chain: Optional[ProjectChain] = None,
        tags: Optional[List[str]] = None
    ) -> "ProjectModel":
        """
        Crée un projet à partir d'une configuration.
        
        Args:
            name: Nom du projet
            spec_yaml: Spécification YAML
            config: Configuration optionnelle
            priority: Priorité du projet
            category: Catégorie du projet
            chain: Blockchain cible
            tags: Tags du projet
            
        Returns:
            ProjectModel: Instance du projet
        """
        # Parser le YAML pour extraire les informations
        try:
            spec_data = yaml.safe_load(spec_yaml)
        except:
            spec_data = {}
        
        project = ProjectModel(
            id=str(uuid.uuid4()),
            name=name,
            spec_yaml=spec_yaml,
            config=config or {},
            chain=chain or ProjectChain(spec_data.get("chain", "ethereum")),
            version=spec_data.get("version", "1.0.0"),
            description=spec_data.get("description", ""),
            priority=priority or ProjectPriority.MEDIUM,
            category=category or ProjectCategory(spec_data.get("category", "other")),
            tags=tags or [],
        )
        
        # Extraire les métadonnées du YAML
        if "metadata" in spec_data:
            project.metadata = spec_data["metadata"]
        
        # Extraire les tags du YAML
        if "tags" in spec_data:
            project.set_tags(spec_data["tags"])
        
        return project
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ProjectModel":
        """
        Crée un projet à partir d'un dictionnaire.
        
        Args:
            data: Dictionnaire des données
            
        Returns:
            ProjectModel: Instance du projet
        """
        return ProjectModel(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "Unnamed Project"),
            description=data.get("description", ""),
            status=ProjectStatus(data.get("status", "CREATED")),
            priority=ProjectPriority(data.get("priority", "medium")),
            category=ProjectCategory(data.get("category", "other")),
            chain=ProjectChain(data.get("chain", "ethereum")),
            config=data.get("config", {}),
            spec_yaml=data.get("spec_yaml", ""),
            version=data.get("version", "1.0.0"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            is_template=data.get("is_template", False),
            is_public=data.get("is_public", False),
        )
    
    # ==========================================================================
    # MÉTHODES MAGIQUES
    # ==========================================================================
    
    def __repr__(self) -> str:
        return f"<ProjectModel(id={self.id}, name={self.name}, status={self.status})>"
    
    def __str__(self) -> str:
        return f"Project: {self.name} ({self.id}) - Status: {self.status.value if self.status else 'N/A'}"
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectModel):
            return False
        return self.id == other.id
    
    def __hash__(self) -> int:
        return hash(self.id)


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Modèle Projet")
    print("=" * 60)
    
    # Création d'un projet
    project = ProjectModel(
        id=str(uuid.uuid4()),
        name="Mon Super Projet",
        description="Un projet de smart contract DeFi",
        spec_yaml="""project:
  name: Mon Super Projet
  chain: ethereum
  version: 1.0.0
  category: defi
  tags:
    - defi
    - lending
""",
        config={"deployment": {"safe_address": "0x123..."}},
        metadata={"team": "Dev Squad", "priority": "high"},
        priority=ProjectPriority.HIGH,
        category=ProjectCategory.DEFI,
        tags=["defi", "lending", "security"]
    )
    
    print(f"\n📋 Projet créé:")
    print(f"  ID: {project.id}")
    print(f"  Nom: {project.name}")
    print(f"  Description: {project.description}")
    print(f"  Status: {project.status.value if project.status else 'N/A'}")
    print(f"  Priority: {project.priority.value if project.priority else 'N/A'}")
    print(f"  Category: {project.category.value if project.category else 'N/A'}")
    print(f"  Chain: {project.chain.value if project.chain else 'N/A'}")
    print(f"  Version: {project.version}")
    print(f"  Tags: {project.get_tags()}")
    
    # Test des méthodes
    print(f"\n📊 Taux de complétion: {project.get_completion_rate()}%")
    
    # Test update status
    project.update_status(ProjectStatus.IN_PROGRESS)
    print(f"\n🔄 Statut après démarrage: {project.status.value}")
    
    # Test incrémentation
    project.increment_task_count()
    project.increment_task_count()
    project.increment_completed_tasks()
    project.increment_failed_tasks()
    print(f"📊 Tâches: {project.task_count} (terminées: {project.completed_task_count}, échouées: {project.failed_task_count})")
    print(f"📊 Taux de complétion: {project.get_completion_rate()}%")
    print(f"📊 Taux d'échec: {project.failure_rate}%")
    
    # Test des tags
    project.add_tag("audited")
    print(f"📋 Tags après ajout: {project.get_tags()}")
    project.remove_tag("lending")
    print(f"📋 Tags après suppression: {project.get_tags()}")
    print(f"✅ Tag 'defi' présent: {project.has_tag('defi')}")
    
    # Test des métadonnées
    project.add_metadata("test_key", "test_value")
    print(f"📋 Métadonnée: {project.get_metadata('test_key')}")
    
    # Test to_dict
    print(f"\n📋 Dictionnaire:")
    project_dict = project.to_dict(include_config=True)
    for key, value in project_dict.items():
        if key in ["config", "metadata"]:
            print(f"  {key}: {value}")
        else:
            print(f"  {key}: {value}")
    
    # Test des statistiques
    stats = project.get_statistics()
    print(f"\n📊 Statistiques:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n✅ Tests terminés.")