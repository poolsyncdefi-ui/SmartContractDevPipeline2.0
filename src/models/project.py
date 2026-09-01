# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Modèle Projet
# ==============================================================================
# Fichier: src/models/project.py
# Description: Modèle SQLAlchemy pour la table projects.
#              Représente un projet de smart contract avec son état et sa configuration.
# ==============================================================================

from sqlalchemy import Column, String, DateTime, Enum, Text, JSON, Integer
from sqlalchemy.orm import relationship, validates
from src.db.database import Base
import datetime
import enum
import uuid
import json
from typing import Optional, Dict, Any, List


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


# ==============================================================================
# MODÈLE PROJECT
# ==============================================================================

class ProjectModel(Base):
    """
    Modèle ORM pour la table projects.
    Représente un projet de smart contract.
    """
    __tablename__ = "projects"
    
    # ==========================================================================
    # COLONNES
    # ==========================================================================
    
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identifiant unique du projet (UUID)"
    )
    
    name = Column(
        String(100),
        nullable=False,
        doc="Nom du projet"
    )
    
    description = Column(
        Text,
        default="",
        doc="Description détaillée du projet"
    )
    
    status = Column(
        Enum(ProjectStatus),
        default=ProjectStatus.CREATED,
        doc="Statut actuel du projet"
    )
    
    chain = Column(
        Enum(ProjectChain),
        default=ProjectChain.ETHEREUM,
        doc="Blockchain cible"
    )
    
    # Configuration complète du projet (stockée en JSON)
    config = Column(
        JSON,
        default={},
        doc="Configuration complète du projet (ProjectConfig)"
    )
    
    # Spécification YAML du projet
    spec_yaml = Column(
        Text,
        nullable=False,
        doc="Spécification YAML du projet"
    )
    
    # Version du projet
    version = Column(
        String(20),
        default="1.0.0",
        doc="Version du projet (semver)"
    )
    
    # Métadonnées additionnelles
    metadata = Column(
        JSON,
        default={},
        doc="Métadonnées additionnelles (tags, labels, etc.)"
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
        doc="Date de début du projet"
    )
    
    completed_at = Column(
        DateTime,
        nullable=True,
        doc="Date de fin du projet"
    )
    
    # ==========================================================================
    # RELATIONS
    # ==========================================================================
    
    tasks = relationship(
        "TaskModel",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="select",
        doc="Tâches du projet"
    )
    
    artifacts = relationship(
        "Artifact",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="select",
        doc="Artefacts du projet"
    )
    
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
        return value.strip()
    
    @validates('version')
    def validate_version(self, key: str, value: str) -> str:
        """Valide le format de la version (semver)."""
        import re
        if not re.match(r'^\d+\.\d+\.\d+$', value):
            raise ValueError(f"Invalid version format: '{value}'. Use semver (X.Y.Z)")
        return value
    
    @validates('spec_yaml')
    def validate_spec_yaml(self, key: str, value: str) -> str:
        """Valide que la spécification YAML n'est pas vide."""
        if not value or len(value.strip()) < 1:
            raise ValueError("Project specification cannot be empty")
        return value
    
    # ==========================================================================
    # MÉTHODES PUBLIQUES
    # ==========================================================================
    
    def to_dict(self, include_config: bool = False) -> Dict[str, Any]:
        """
        Convertit le modèle en dictionnaire.
        
        Args:
            include_config: Si True, inclut la configuration complète
            
        Returns:
            Dict[str, Any]: Dictionnaire du projet
        """
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value if self.status else None,
            "chain": self.chain.value if self.chain else None,
            "version": self.version,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        
        if include_config:
            result["config"] = self.config
            result["metadata"] = self.metadata
        
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
            "chain": self.chain.value if self.chain else None,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "completion_rate": self.get_completion_rate(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    def update_status(self, new_status: ProjectStatus) -> None:
        """
        Met à jour le statut du projet.
        
        Args:
            new_status: Nouveau statut
        """
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.datetime.utcnow()
        
        # Mise à jour des dates spécifiques
        if new_status == ProjectStatus.IN_PROGRESS and not self.started_at:
            self.started_at = datetime.datetime.utcnow()
        elif new_status == ProjectStatus.COMPLETED:
            self.completed_at = datetime.datetime.utcnow()
    
    def increment_task_count(self) -> None:
        """Incrémente le compteur de tâches."""
        self.task_count += 1
        self.updated_at = datetime.datetime.utcnow()
    
    def increment_completed_tasks(self) -> None:
        """Incrémente le compteur de tâches terminées."""
        self.completed_task_count += 1
        self.updated_at = datetime.datetime.utcnow()
    
    def get_completion_rate(self) -> float:
        """
        Calcule le taux de complétion du projet.
        
        Returns:
            float: Taux de complétion en pourcentage (0-100)
        """
        if self.task_count == 0:
            return 0.0
        return round((self.completed_task_count / self.task_count) * 100, 2)
    
    def is_active(self) -> bool:
        """Vérifie si le projet est actif."""
        return self.status in [ProjectStatus.CREATED, ProjectStatus.IN_PROGRESS]
    
    def is_completed(self) -> bool:
        """Vérifie si le projet est terminé."""
        return self.status == ProjectStatus.COMPLETED
    
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
    
    def add_metadata(self, key: str, value: Any) -> None:
        """
        Ajoute une métadonnée.
        
        Args:
            key: Clé de la métadonnée
            value: Valeur de la métadonnée
        """
        if not self.metadata:
            self.metadata = {}
        self.metadata[key] = value
        self.updated_at = datetime.datetime.utcnow()
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        Récupère une métadonnée.
        
        Args:
            key: Clé de la métadonnée
            default: Valeur par défaut
            
        Returns:
            Any: Valeur de la métadonnée
        """
        if not self.metadata:
            return default
        return self.metadata.get(key, default)
    
    # ==========================================================================
    # MÉTHODES STATIQUES
    # ==========================================================================
    
    @staticmethod
    def create_from_config(name: str, spec_yaml: str, config: Optional[Dict[str, Any]] = None) -> "ProjectModel":
        """
        Crée un projet à partir d'une configuration.
        
        Args:
            name: Nom du projet
            spec_yaml: Spécification YAML
            config: Configuration optionnelle
            
        Returns:
            ProjectModel: Instance du projet
        """
        import yaml
        
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
            chain=ProjectChain(spec_data.get("chain", "ethereum")),
            version=spec_data.get("version", "1.0.0"),
            description=spec_data.get("description", ""),
        )
        
        # Extraire les métadonnées du YAML
        if "metadata" in spec_data:
            project.metadata = spec_data["metadata"]
        
        return project
    
    # ==========================================================================
    # REPRÉSENTATION
    # ==========================================================================
    
    def __repr__(self) -> str:
        return f"<ProjectModel(id={self.id}, name={self.name}, status={self.status})>"
    
    def __str__(self) -> str:
        return f"Project: {self.name} ({self.id}) - Status: {self.status.value if self.status else 'N/A'}"


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
""",
        config={"deployment": {"safe_address": "0x123..."}},
        metadata={"team": "Dev Squad", "priority": "high"}
    )
    
    print(f"\n📋 Projet créé:")
    print(f"  ID: {project.id}")
    print(f"  Nom: {project.name}")
    print(f"  Description: {project.description}")
    print(f"  Status: {project.status.value if project.status else 'N/A'}")
    print(f"  Chain: {project.chain.value if project.chain else 'N/A'}")
    print(f"  Version: {project.version}")
    
    # Test des méthodes
    print(f"\n📊 Taux de complétion: {project.get_completion_rate()}%")
    
    # Test update status
    project.update_status(ProjectStatus.IN_PROGRESS)
    print(f"\n🔄 Statut après démarrage: {project.status.value}")
    
    # Test incrémentation
    project.increment_task_count()
    project.increment_completed_tasks()
    print(f"📊 Tâches: {project.task_count} (terminées: {project.completed_task_count})")
    print(f"📊 Taux de complétion: {project.get_completion_rate()}%")
    
    # Test to_dict
    print(f"\n📋 Dictionnaire:")
    project_dict = project.to_dict(include_config=True)
    for key, value in project_dict.items():
        if key in ["config", "metadata"]:
            print(f"  {key}: {value}")
        else:
            print(f"  {key}: {value}")
    
    print("\n✅ Tests terminés.")