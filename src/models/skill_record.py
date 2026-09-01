# src/models/skill_record.py

"""
Model for skill records.
F12 – src/models/skill_record.py

Rôle Fonctionnel : Mémorise les compétences techniques réutilisables dans la base de données.
Ce modèle est essentiel au moteur d'acquisition dynamique de compétences (Skill Engine).
Il permet de stocker et de retrouver des compétences expertes (BaseSkill) qui ont ete
creees dynamiquement par l'Agent Architecte ou importees d'un catalogue.
La persistance des competences permet leur reutilisation a travers differents projets
et evite d'avoir a les regenerer a chaque fois.

Le modèle SkillRecord stocke:
- Les règles de prompt (expertise métier)
- Le schéma de validation (Pydantic)
- Le code Python de la compétence (optionnel)
- Les métadonnées de version et d'utilisation
- Les dépendances avec d'autres compétences

Cette table est utilisée par le SkillRegistry pour charger et instancier
les compétences dynamiquement.
"""
from sqlalchemy import Column, String, Text, JSON, Integer, DateTime, Boolean, Index
from sqlalchemy.orm import relationship
from src.db.database import Base
import datetime
import json
from typing import Dict, Any, List, Optional, Set
from enum import Enum


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

    Attributes:
        skill_id (str): Identifiant unique de la compétence (clé primaire).
                         Exemple: "chainlink_ccip_skill_v1"
        name (str): Nom lisible de la compétence.
        description (str): Description textuelle de ce que fait la compétence.
        version (str): Version de la compétence (semver).
        status (SkillStatus): Statut de la compétence (active, deprecated, etc.).
        scope (SkillScope): Portée de la compétence (global, project, session).
        project_id (str): ID du projet (si scope = PROJECT).
        prompt_rules (str): Les règles de prompt et directives d'expertise.
        input_schema_json (JSON): Le schéma Pydantic au format JSON.
        output_schema_json (JSON): Le schéma de sortie au format JSON (optionnel).
        python_code (str): Le code Python de la classe BaseSkill (optionnel).
        dependencies (JSON): Liste des IDs de compétences dépendantes.
        tags (JSON): Tags pour la catégorisation et la recherche.
        metadata (JSON): Métadonnées supplémentaires.
        usage_count (int): Nombre d'utilisations de la compétence.
        last_used_at (DateTime): Date de dernière utilisation.
        created_at (DateTime): Date de création.
        updated_at (DateTime): Date de dernière mise à jour.
        created_by (str): Créateur de la compétence.
        updated_by (str): Dernier modificateur.
        is_verified (bool): Compétence vérifiée (sécurisée).
    """
    __tablename__ = "skill_records"

    # Identifiants
    skill_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    
    # Version et statut
    version = Column(String, nullable=False, default="1.0.0")
    status = Column(String, nullable=False, default=SkillStatus.ACTIVE.value)
    scope = Column(String, nullable=False, default=SkillScope.GLOBAL.value)
    project_id = Column(String, nullable=True, index=True)
    
    # Contenu (champs obligatoires)
    prompt_rules = Column(Text, nullable=False)
    input_schema_json = Column(JSON, nullable=False)
    output_schema_json = Column(JSON, nullable=True)  # Validation de sortie
    python_code = Column(Text, nullable=True)
    
    # Dépendances et tags
    dependencies = Column(JSON, nullable=True, default=list)  # List[str]
    tags = Column(JSON, nullable=True, default=list)          # List[str]
    metadata = Column(JSON, nullable=True, default=dict)      # Dict[str, Any]
    
    # Statistiques d'utilisation
    usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    
    # Horodatage
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    
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

    def __repr__(self) -> str:
        """
        Représentation lisible de l'objet pour le débogage.
        """
        return f"<SkillRecordModel(skill_id='{self.skill_id}', name='{self.name}', version='{self.version}', status='{self.status}')>"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit l'objet en dictionnaire pour une utilisation facile,
        par exemple pour l'échange avec des APIs ou la sérialisation.
        """
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
        """
        Convertit l'objet en dictionnaire court pour les listes.
        """
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
        """
        Récupère les dépendances sous forme de liste.
        
        Returns:
            List[str]: Liste des IDs de compétences dépendantes
        """
        if not self.dependencies:
            return []
        if isinstance(self.dependencies, list):
            return self.dependencies
        try:
            return json.loads(self.dependencies) if isinstance(self.dependencies, str) else []
        except json.JSONDecodeError:
            return []

    def set_dependencies(self, dependencies: List[str]) -> None:
        """
        Définit les dépendances à partir d'une liste.
        
        Args:
            dependencies (List[str]): IDs des compétences dépendantes
        """
        self.dependencies = dependencies if dependencies else []

    def add_dependency(self, skill_id: str) -> None:
        """
        Ajoute une dépendance.
        
        Args:
            skill_id (str): ID de la compétence dépendante
        """
        deps = self.get_dependencies()
        if skill_id not in deps:
            deps.append(skill_id)
            self.set_dependencies(deps)

    def remove_dependency(self, skill_id: str) -> None:
        """
        Supprime une dépendance.
        
        Args:
            skill_id (str): ID de la compétence dépendante à supprimer
        """
        deps = self.get_dependencies()
        if skill_id in deps:
            deps.remove(skill_id)
            self.set_dependencies(deps)

    def get_tags(self) -> List[str]:
        """
        Récupère les tags sous forme de liste.
        
        Returns:
            List[str]: Liste des tags
        """
        if not self.tags:
            return []
        if isinstance(self.tags, list):
            return self.tags
        try:
            return json.loads(self.tags) if isinstance(self.tags, str) else []
        except json.JSONDecodeError:
            return []

    def set_tags(self, tags: List[str]) -> None:
        """
        Définit les tags à partir d'une liste.
        
        Args:
            tags (List[str]): Tags à stocker
        """
        self.tags = tags if tags else []

    def add_tag(self, tag: str) -> None:
        """
        Ajoute un tag.
        
        Args:
            tag (str): Tag à ajouter
        """
        current_tags = self.get_tags()
        if tag not in current_tags:
            current_tags.append(tag)
            self.set_tags(current_tags)

    def remove_tag(self, tag: str) -> None:
        """
        Supprime un tag.
        
        Args:
            tag (str): Tag à supprimer
        """
        current_tags = self.get_tags()
        if tag in current_tags:
            current_tags.remove(tag)
            self.set_tags(current_tags)

    def has_tag(self, tag: str) -> bool:
        """
        Vérifie si un tag est présent.
        
        Args:
            tag (str): Tag à vérifier
            
        Returns:
            bool: True si le tag est présent
        """
        return tag in self.get_tags()

    def get_metadata(self) -> Dict[str, Any]:
        """
        Récupère les métadonnées sous forme de dictionnaire.
        
        Returns:
            Dict[str, Any]: Métadonnées
        """
        if not self.metadata:
            return {}
        if isinstance(self.metadata, dict):
            return self.metadata
        try:
            return json.loads(self.metadata) if isinstance(self.metadata, str) else {}
        except json.JSONDecodeError:
            return {"_raw": self.metadata}

    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        """
        Définit les métadonnées à partir d'un dictionnaire.
        
        Args:
            metadata (Dict[str, Any]): Métadonnées à stocker
        """
        self.metadata = metadata if metadata else {}

    def get_metadata_value(self, key: str, default: Any = None) -> Any:
        """
        Récupère une valeur spécifique des métadonnées.
        
        Args:
            key (str): Clé de la métadonnée
            default (Any): Valeur par défaut si la clé n'existe pas
            
        Returns:
            Any: Valeur de la métadonnée
        """
        return self.get_metadata().get(key, default)

    def set_metadata_value(self, key: str, value: Any) -> None:
        """
        Définit une valeur spécifique des métadonnées.
        
        Args:
            key (str): Clé de la métadonnée
            value (Any): Valeur à stocker
        """
        metadata = self.get_metadata()
        metadata[key] = value
        self.set_metadata(metadata)

    def increment_usage(self) -> None:
        """
        Incrémente le compteur d'utilisation et met à jour la date de dernière utilisation.
        """
        self.usage_count += 1
        self.last_used_at = datetime.datetime.utcnow()

    def is_active(self) -> bool:
        """
        Vérifie si la compétence est active.
        
        Returns:
            bool: True si active
        """
        return self.status == SkillStatus.ACTIVE.value

    def is_deprecated(self) -> bool:
        """
        Vérifie si la compétence est dépréciée.
        
        Returns:
            bool: True si dépréciée
        """
        return self.status == SkillStatus.DEPRECATED.value

    def is_archived(self) -> bool:
        """
        Vérifie si la compétence est archivée.
        
        Returns:
            bool: True si archivée
        """
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
        """
        Factory method pour créer une nouvelle compétence.
        
        Args:
            skill_id: Identifiant unique de la compétence
            name: Nom de la compétence
            prompt_rules: Règles de prompt
            input_schema_json: Schéma d'entrée JSON
            description: Description (optionnel)
            version: Version (défaut: "1.0.0")
            status: Statut (défaut: "active")
            scope: Portée (défaut: "global")
            project_id: ID du projet (si scope = "project")
            output_schema_json: Schéma de sortie (optionnel)
            python_code: Code Python (optionnel)
            dependencies: Dépendances (optionnel)
            tags: Tags (optionnel)
            metadata: Métadonnées (optionnel)
            created_by: Créateur (optionnel)
            is_verified: Vérifiée (défaut: False)
            
        Returns:
            SkillRecordModel: Instance de la compétence
        """
        skill = cls(
            skill_id=skill_id,
            name=name,
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
        skill_config: "SkillConfig",
        python_code: Optional[str] = None,
        **kwargs
    ) -> "SkillRecordModel":
        """
        Factory method pour créer une compétence à partir d'une configuration SkillConfig.
        
        Args:
            skill_config: Configuration de la compétence
            python_code: Code Python (optionnel)
            **kwargs: Arguments supplémentaires
            
        Returns:
            SkillRecordModel: Instance de la compétence
        """
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
        """
        Définit la fonction de callback pour l'utilisation des compétences.
        
        Args:
            callback: Fonction async appelée avec (skill_id, success)
        """
        self._skill_usage_callback = callback
    
    async def use_skill(self, skill_id: str, success: bool = True) -> None:
        """
        Enregistre l'utilisation d'une compétence.
        
        Args:
            skill_id (str): ID de la compétence utilisée
            success (bool): Succès de l'utilisation
        """
        if self._skill_usage_callback:
            await self._skill_usage_callback(skill_id, success)
    
    async def validate_skill_dependencies(
        self,
        skill_ids: List[str],
        skill_registry
    ) -> List[str]:
        """
        Valide les dépendances d'une liste de compétences.
        
        Args:
            skill_ids: Liste des IDs de compétences
            skill_registry: Registre des compétences
            
        Returns:
            List[str]: IDs des compétences manquantes
        """
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
        """
        Récupère toutes les dépendances d'une compétence (récursif).
        
        Args:
            skill_id: ID de la compétence
            skill_registry: Registre des compétences
            visited: Ensemble des IDs visités (pour éviter les cycles)
            
        Returns:
            List[str]: Liste de toutes les dépendances
        """
        if visited is None:
            visited = set()
        
        if skill_id in visited:
            return []
        
        visited.add(skill_id)
        dependencies = []
        
        # Récupérer les dépendances directes
        skill_record = await skill_registry.get_record(skill_id)
        if skill_record:
            direct_deps = skill_record.get_dependencies()
            for dep_id in direct_deps:
                dependencies.append(dep_id)
                # Récursivité pour les dépendances imbriquées
                sub_deps = await self.get_skill_dependencies(dep_id, skill_registry, visited)
                dependencies.extend(sub_deps)
        
        return list(set(dependencies))  # Déduplication