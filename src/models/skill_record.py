# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Modèle SkillRecord
# ==============================================================================
# Fichier: src/models/skill_record.py
# Description: Modèle ORM SQLAlchemy pour la table skill_records.
#              Mémorise les compétences techniques réutilisables.
# ==============================================================================

from sqlalchemy import Column, String, Text, JSON, Integer, DateTime, Boolean, Index
from sqlalchemy.orm import relationship, validates
from src.db.database import Base
from datetime import datetime, timezone
import json
import logging
from typing import Dict, Any, List, Optional, Set
from enum import Enum
import re

logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """
    Statuts possibles pour une compétence.
    """
    DRAFT = "draft"          # Brouillon - en cours de développement
    ACTIVE = "active"        # Active - prête à l'emploi
    DEPRECATED = "deprecated" # Dépréciée - ne plus utiliser
    ARCHIVED = "archived"    # Archivée - conservée pour historique


class SkillScope(str, Enum):
    """
    Portée d'une compétence.
    """
    GLOBAL = "global"        # Disponible pour tous les projets
    PROJECT = "project"      # Spécifique à un projet
    SESSION = "session"      # Temporaire - durée de la session


class SkillRecordModel(Base):
    """
    Modèle ORM pour la table 'skill_records'.

    Cette table stocke les compétences expertes sous une forme sérialisée,
    permettant de les recharger dynamiquement via le SkillRegistry.
    """
    __tablename__ = "skill_records"

    # Identifiants
    skill_id = Column(String(100), primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Version et statut
    version = Column(String(50), nullable=False, default="1.0.0")
    status = Column(String(50), nullable=False, default=SkillStatus.ACTIVE.value)
    scope = Column(String(50), nullable=False, default=SkillScope.GLOBAL.value)
    project_id = Column(String(100), nullable=True, index=True)
    
    # Contenu (champs obligatoires)
    prompt_rules = Column(Text, nullable=False)
    input_schema_json = Column(JSON, nullable=False)
    output_schema_json = Column(JSON, nullable=True)  # Validation de sortie
    python_code = Column(Text, nullable=True)
    
    # Dépendances et tags
    dependencies = Column(JSON, nullable=True, default=list)  # List[str]
    tags = Column(JSON, nullable=True, default=list)          # List[str]
    
    # Métadonnées (renommé en extra_metadata pour éviter le conflit avec Base.metadata de SQLAlchemy)
    extra_metadata = Column(
        "metadata",
        JSON,
        nullable=True,
        default=dict,
        doc="Métadonnées supplémentaires au format JSON"
    )
    
    # Statistiques d'utilisation
    usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    
    # Horodatage (UTC time-aware avec lambda)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Date de création (UTC)"
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Date de dernière mise à jour (UTC)"
    )
    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)
    
    # Métadonnées de sécurité
    is_verified = Column(Boolean, nullable=False, default=False)

    # Index pour les requêtes fréquentes
    __table_args__ = (
        Index('idx_skill_records_status', 'status'),
        Index('idx_skill_records_scope', 'scope'),
        Index('idx_skill_records_project_id', 'project_id'),
        Index('idx_skill_records_name', 'name'),
        Index('idx_skill_records_created_at', 'created_at'),
        Index('idx_skill_records_usage_count', 'usage_count'),
        Index('idx_skill_records_status_scope', 'status', 'scope'),
    )

    # Validateurs
    @validates('skill_id')
    def validate_skill_id(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("skill_id cannot be empty")
        return value.strip()

    @validates('name')
    def validate_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("name cannot be empty")
        return value.strip()

    @validates('prompt_rules')
    def validate_prompt_rules(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("prompt_rules cannot be empty")
        return value

    @validates('version')
    def validate_version(self, key: str, value: str) -> str:
        if not value or not value.strip():
            return "1.0.0"
        cleaned_value = value.strip()
        if not re.match(r'^\d+\.\d+\.\d+$', cleaned_value):
            raise ValueError(f"Invalid version format: '{cleaned_value}'. Use semver (X.Y.Z)")
        return cleaned_value

    def __repr__(self) -> str:
        """Représentation lisible de l'objet pour le débogage."""
        return f"<SkillRecordModel(skill_id='{self.skill_id}', name='{self.name}', version='{self.version}', status='{self.status}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'objet en dictionnaire pour la sérialisation."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status,
            "scope": self.scope,
            "project_id": self.project_id,
            "prompt_rules": self.prompt_rules,
            "input_schema_json": self.input_schema_json,
            "output_schema_json": self.output_schema_json,
            "python_code": self.python_code,
            "dependencies": self.get_dependencies(),
            "tags": self.get_tags(),
            "metadata": self.get_metadata(),
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "is_verified": self.is_verified
        }

    def to_short_dict(self) -> Dict[str, Any]:
        """Convertit l'objet en dictionnaire court pour les listes."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "scope": self.scope,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_verified": self.is_verified
        }

    def get_dependencies(self) -> List[str]:
        """Récupère les dépendances sous forme de liste."""
        if self.dependencies is None:
            return []
        if isinstance(self.dependencies, list):
            return self.dependencies
        try:
            if isinstance(self.dependencies, str):
                parsed = json.loads(self.dependencies)
                return parsed if isinstance(parsed, list) else []
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse dependencies JSON for skill {self.skill_id}: {e}")
            return []

    def set_dependencies(self, dependencies: List[str]) -> None:
        """Définit les dépendances à partir d'une liste."""
        self.dependencies = dependencies if dependencies is not None else []

    def add_dependency(self, skill_id: str) -> None:
        """Ajoute une dépendance."""
        deps = self.get_dependencies()
        if skill_id not in deps:
            deps.append(skill_id)
            self.set_dependencies(deps)

    def remove_dependency(self, skill_id: str) -> None:
        """Supprime une dépendance."""
        deps = self.get_dependencies()
        if skill_id in deps:
            deps.remove(skill_id)
            self.set_dependencies(deps)

    def get_tags(self) -> List[str]:
        """Récupère les tags sous forme de liste."""
        if self.tags is None:
            return []
        if isinstance(self.tags, list):
            return self.tags
        try:
            if isinstance(self.tags, str):
                parsed = json.loads(self.tags)
                return parsed if isinstance(parsed, list) else []
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tags JSON for skill {self.skill_id}: {e}")
            return []

    def set_tags(self, tags: List[str]) -> None:
        """Définit les tags à partir d'une liste."""
        self.tags = tags if tags is not None else []

    def add_tag(self, tag: str) -> None:
        """Ajoute un tag."""
        current_tags = self.get_tags()
        if tag not in current_tags:
            current_tags.append(tag)
            self.set_tags(current_tags)

    def remove_tag(self, tag: str) -> None:
        """Supprime un tag."""
        current_tags = self.get_tags()
        if tag in current_tags:
            current_tags.remove(tag)
            self.set_tags(current_tags)

    def has_tag(self, tag: str) -> bool:
        """Vérifie si un tag est présent."""
        return tag in self.get_tags()

    def get_metadata(self) -> Dict[str, Any]:
        """Récupère les métadonnées sous forme de dictionnaire."""
        if self.extra_metadata is None:
            return {}
        if isinstance(self.extra_metadata, dict):
            return self.extra_metadata
        try:
            if isinstance(self.extra_metadata, str):
                parsed = json.loads(self.extra_metadata)
                return parsed if isinstance(parsed, dict) else {}
            return {}
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse metadata JSON for skill {self.skill_id}: {e}")
            return {"_raw": self.extra_metadata}

    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        """Définit les métadonnées à partir d'un dictionnaire."""
        self.extra_metadata = metadata if metadata is not None else {}

    def get_metadata_value(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur spécifique des métadonnées."""
        return self.get_metadata().get(key, default)

    def set_metadata_value(self, key: str, value: Any) -> None:
        """Définit une valeur spécifique des métadonnées."""
        metadata = self.get_metadata()
        metadata[key] = value
        self.set_metadata(metadata)

    def increment_usage(self) -> None:
        """Incrémente le compteur d'utilisation et met à jour la date de dernière utilisation."""
        self.usage_count += 1
        self.last_used_at = datetime.now(timezone.utc)

    def is_active(self) -> bool:
        """Vérifie si la compétence est active."""
        return self.status == SkillStatus.ACTIVE.value

    def is_deprecated(self) -> bool:
        """Vérifie si la compétence est dépréciée."""
        return self.status == SkillStatus.DEPRECATED.value

    def is_archived(self) -> bool:
        """Vérifie si la compétence est archivée."""
        return self.status == SkillStatus.ARCHIVED.value

    @classmethod
    def create_skill(
        cls,
        skill_id: str,
        name: str,
        prompt_rules: str,
        input_schema_json: Dict[str, Any],
        description: Optional[str] = None,
        version: str = "1.0.0",
        status: str = SkillStatus.ACTIVE.value,
        scope: str = SkillScope.GLOBAL.value,
        project_id: Optional[str] = None,
        output_schema_json: Optional[Dict[str, Any]] = None,
        python_code: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
        is_verified: bool = False
    ) -> "SkillRecordModel":
        """Factory method pour créer une nouvelle compétence."""
        if not skill_id or not skill_id.strip():
            raise ValueError("skill_id is required")
        if not name or not name.strip():
            raise ValueError("name is required")
        if not prompt_rules or not prompt_rules.strip():
            raise ValueError("prompt_rules is required")
        if not input_schema_json:
            raise ValueError("input_schema_json is required")

        skill = cls(
            skill_id=skill_id.strip(),
            name=name.strip(),
            description=description,
            version=version,
            status=status,
            scope=scope,
            project_id=project_id,
            prompt_rules=prompt_rules,
            input_schema_json=input_schema_json,
            output_schema_json=output_schema_json,
            python_code=python_code,
            created_by=created_by,
            is_verified=is_verified
        )
        if dependencies:
            skill.set_dependencies(dependencies)
        if tags:
            skill.set_tags(tags)
        if metadata:
            skill.set_metadata(metadata)
        return skill

    @classmethod
    def create_from_skill_config(
        cls,
        skill_config,
        python_code: Optional[str] = None,
        **kwargs
    ) -> "SkillRecordModel":
        """Factory method pour créer une compétence à partir d'une configuration SkillConfig."""
        if not skill_config:
            raise ValueError("skill_config is required")
        
        return cls.create_skill(
            skill_id=skill_config.skill_id,
            name=skill_config.name,
            description=getattr(skill_config, 'description', None),
            prompt_rules=getattr(skill_config, 'prompt_rules', ''),
            input_schema_json=getattr(skill_config, 'input_schema', {}),
            python_code=python_code,
            **kwargs
        )


# =============================================================================
# MIXIN POUR L'UTILISATION DE COMPETENCES
# =============================================================================

class SkillUsableMixin:
    """
    Mixin pour ajouter des fonctionnalités d'utilisation de compétences.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._skill_usage_callback = None
    
    def set_skill_usage_callback(self, callback):
        """Définit la fonction de callback pour l'utilisation des compétences."""
        self._skill_usage_callback = callback
    
    async def use_skill(self, skill_id: str, success: bool = True) -> None:
        """Enregistre l'utilisation d'une compétence."""
        if self._skill_usage_callback:
            await self._skill_usage_callback(skill_id, success)
    
    async def validate_skill_dependencies(
        self,
        skill_ids: List[str],
        skill_registry
    ) -> List[str]:
        """Valide les dépendances d'une liste de compétences."""
        missing = []
        for skill_id in skill_ids:
            if not skill_registry.has_skill(skill_id):
                missing.append(skill_id)
        return missing
    
    async def get_skill_dependencies(
        self,
        skill_id: str,
        skill_registry,
        visited: Optional[Set[str]] = None
    ) -> List[str]:
        """Récupère toutes les dépendances d'une compétence (récursif)."""
        if visited is None:
            visited = set()
        
        if skill_id in visited:
            return []
        
        visited.add(skill_id)
        dependencies = []
        
        skill_record = await skill_registry.get_record(skill_id)
        if skill_record:
            direct_deps = skill_record.get_dependencies()
            for dep_id in direct_deps:
                dependencies.append(dep_id)
                sub_deps = await self.get_skill_dependencies(dep_id, skill_registry, visited)
                dependencies.extend(sub_deps)
        
        return list(set(dependencies))