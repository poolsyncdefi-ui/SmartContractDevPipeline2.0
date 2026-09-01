# src/agents/factory/skill_registry.py

"""
Skill registry for the Smart Contract Dev Pipeline.
F17 – src/agents/factory/skill_registry.py

Rôle Fonctionnel : Registre central des competences (Singleton).
Ce module implemente le registre des competences expertes disponibles
dans le pipeline. Il permet de:
- Enregistrer de nouvelles competences
- Recuperer des competences par ID
- Gerer plusieurs versions d'une competence
- Persister les competences en base de donnees
- Integrer avec le RAG pour la recherche contextuelle
- Notifier les changements via le message bus

Le registre est un Singleton garantissant un point d'acces unique
a toutes les competences du systeme.
"""
from typing import Dict, List, Type, Optional, Any, Set, Tuple
from datetime import datetime
import json
import logging
import hashlib
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict

# Import des modules du pipeline
from src.agents.base.skill import BaseSkill
from src.core.exceptions import SkillNotFoundError
from src.core.models import Skill as SkillConfig
from src.persistence.knowledge_base import KnowledgeBase
from src.communication.message_bus import MessageBus
from src.models.skill_record import SkillRecordModel

# Configuration du logging
logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """
    Statuts possibles pour une competence enregistree.
    """
    REGISTERED = "registered"
    INITIALIZED = "initialized"
    VALIDATED = "validated"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class SkillScope(str, Enum):
    """
    Portee d'une competence.
    """
    GLOBAL = "global"      # Disponible pour tous les projets
    PROJECT = "project"    # Specifique a un projet
    SESSION = "session"    # Temporaire (durant la session)


@dataclass
class SkillMetadata:
    """
    Metadonnees d'une competence enregistree.
    
    Attributes:
        skill_id (str): Identifiant de la competence
        name (str): Nom de la competence
        description (str): Description de la competence
        version (str): Version de la competence
        status (SkillStatus): Statut actuel
        scope (SkillScope): Portee de la competence
        registered_at (datetime): Date d'enregistrement
        updated_at (datetime): Date de derniere mise a jour
        registered_by (str): Qui a enregistre la competence
        project_id (Optional[str]): ID du projet (si portee PROJECT)
        tags (Set[str]): Tags pour la recherche
        usage_count (int): Nombre d'utilisations
        last_used (Optional[datetime]): Date de derniere utilisation
        dependencies (Set[str]): IDs des competences dependantes
    """
    skill_id: str
    name: str
    description: str
    version: str = "1.0.0"
    status: SkillStatus = SkillStatus.REGISTERED
    scope: SkillScope = SkillScope.GLOBAL
    registered_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    registered_by: str = "system"
    project_id: Optional[str] = None
    tags: Set[str] = field(default_factory=set)
    usage_count: int = 0
    last_used: Optional[datetime] = None
    dependencies: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict:
        """Convertit en dictionnaire."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status.value,
            "scope": self.scope.value,
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "registered_by": self.registered_by,
            "project_id": self.project_id,
            "tags": list(self.tags),
            "usage_count": self.usage_count,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "dependencies": list(self.dependencies)
        }


class SkillRegistry:
    """
    Registre singleton des competences disponibles.
    
    Ce registre centralise toutes les competences du systeme.
    Il supporte:
    - L'enregistrement et la recuperation de competences
    - Le versioning (plusieurs versions par competence)
    - La persistance en base de donnees
    - L'integration avec le RAG (ChromaDB)
    - La notification via le message bus
    - Les metriques d'utilisation
    
    Attributes:
        _instance (SkillRegistry): Instance unique du registre
        _skills (Dict[str, BaseSkill]): Cache des competences actives
        _skill_classes (Dict[str, Type[BaseSkill]]): Classes de competences
        _metadata (Dict[str, SkillMetadata]): Metadonnees des competences
        _versions (Dict[str, List[str]]): Versions par competence
        _current_versions (Dict[str, str]): Version active par competence
        _knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG
        _message_bus (Optional[MessageBus]): Bus de messages pour les events
        _initialized (bool): Indique si le registre est initialise
    """
    
    _instance: Optional['SkillRegistry'] = None
    _initialized: bool = False
    
    def __new__(cls) -> 'SkillRegistry':
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialise le registre (une seule fois)."""
        if self._initialized:
            return
        
        # Cache des competences actives (instances)
        self._skills: Dict[str, BaseSkill] = {}
        
        # Classes de competences (pour instantiation)
        self._skill_classes: Dict[str, Type[BaseSkill]] = {}
        
        # Metadonnees des competences
        self._metadata: Dict[str, SkillMetadata] = {}
        
        # Gestion des versions
        self._versions: Dict[str, List[str]] = defaultdict(list)  # skill_id -> [versions]
        self._current_versions: Dict[str, str] = {}  # skill_id -> current_version
        
        # Tags pour la recherche
        self._tags_index: Dict[str, Set[str]] = defaultdict(set)  # tag -> {skill_ids}
        
        # Dependances
        self._dependencies: Dict[str, Set[str]] = defaultdict(set)  # skill_id -> {dep_ids}
        self._dependents: Dict[str, Set[str]] = defaultdict(set)  # skill_id -> {dependent_ids}
        
        # Injections
        self._knowledge_base: Optional[KnowledgeBase] = None
        self._message_bus: Optional[MessageBus] = None
        
        # Statistiques
        self._total_registrations = 0
        self._total_errors = 0
        
        self._initialized = True
        logger.info("SkillRegistry initialized")
    
    def initialize(
        self,
        knowledge_base: Optional[KnowledgeBase] = None,
        message_bus: Optional[MessageBus] = None
    ) -> None:
        """
        Initialise le registre avec les dependances externes.
        
        Args:
            knowledge_base: Base de connaissances pour le RAG
            message_bus: Bus de messages pour les evenements
        """
        self._knowledge_base = knowledge_base
        self._message_bus = message_bus
        
        if knowledge_base:
            logger.info("Knowledge base connected to SkillRegistry")
        if message_bus:
            logger.info("Message bus connected to SkillRegistry")
    
    # =========================================================================
    # OPERATIONS DE BASE
    # =========================================================================
    
    def register(
        self,
        skill_id: str,
        skill_class: Type[BaseSkill],
        metadata: Optional[SkillMetadata] = None,
        version: str = "1.0.0"
    ) -> None:
        """
        Enregistre une nouvelle competence.
        
        Args:
            skill_id: Identifiant de la competence
            skill_class: Classe de la competence
            metadata: Metadonnees de la competence (optionnel)
            version: Version de la competence
            
        Raises:
            ValueError: Si la competence est deja enregistree avec la meme version
        """
        # Validation
        if not skill_id:
            raise ValueError("skill_id cannot be empty")
        if not skill_class:
            raise ValueError("skill_class cannot be None")
        if not issubclass(skill_class, BaseSkill):
            raise ValueError(f"skill_class must be a subclass of BaseSkill")
        
        # Verifier si la version existe deja
        if skill_id in self._versions and version in self._versions[skill_id]:
            raise ValueError(f"Skill {skill_id} version {version} already registered")
        
        # Creation des metadonnees si non fournies
        if metadata is None:
            metadata = SkillMetadata(
                skill_id=skill_id,
                name=getattr(skill_class, 'name', skill_id),
                description=getattr(skill_class, 'description', 'No description'),
                version=version
            )
        
        # Enregistrement
        self._skill_classes[skill_id] = skill_class
        self._metadata[skill_id] = metadata
        self._versions[skill_id].append(version)
        self._current_versions[skill_id] = version
        
        # Indexation des tags
        for tag in metadata.tags:
            self._tags_index[tag].add(skill_id)
        
        # Indexation des dependances
        for dep_id in metadata.dependencies:
            self._dependencies[skill_id].add(dep_id)
            self._dependents[dep_id].add(skill_id)
        
        self._total_registrations += 1
        
        logger.info(f"Skill registered: {skill_id} v{version}")
        
        # Notification de l'evenement
        self._emit_event("skill_registered", {
            "skill_id": skill_id,
            "version": version,
            "metadata": metadata.to_dict()
        })
    
    def register_instance(
        self,
        skill_instance: BaseSkill,
        metadata: Optional[SkillMetadata] = None
    ) -> None:
        """
        Enregistre une instance de competence deja instanciee.
        
        Args:
            skill_instance: Instance de la competence
            metadata: Metadonnees (optionnel)
        """
        if not isinstance(skill_instance, BaseSkill):
            raise ValueError("skill_instance must be a BaseSkill instance")
        
        skill_id = skill_instance.skill_id
        version = getattr(skill_instance, 'version', '1.0.0')
        
        # Enregistrer la classe
        self.register(
            skill_id=skill_id,
            skill_class=type(skill_instance),
            metadata=metadata,
            version=version
        )
        
        # Stocker l'instance
        self._skills[skill_id] = skill_instance
        
        logger.info(f"Skill instance registered: {skill_id}")
    
    def get(self, skill_id: str, version: Optional[str] = None) -> Type[BaseSkill]:
        """
        Recupere une classe de competence par son ID.
        
        Args:
            skill_id: Identifiant de la competence
            version: Version specifique (optionnel)
            
        Returns:
            Type[BaseSkill]: Classe de la competence
            
        Raises:
            SkillNotFoundError: Si la competence n'existe pas
        """
        if skill_id not in self._skill_classes:
            self._total_errors += 1
            raise SkillNotFoundError(
                skill_id=skill_id,
                message=f"Skill '{skill_id}' not found"
            )
        
        # Mise a jour des metadonnees
        if skill_id in self._metadata:
            self._metadata[skill_id].usage_count += 1
            self._metadata[skill_id].last_used = datetime.utcnow()
        
        return self._skill_classes[skill_id]
    
    def get_instance(
        self,
        skill_id: str,
        version: Optional[str] = None,
        **kwargs
    ) -> BaseSkill:
        """
        Recupere une instance de competence.
        
        Args:
            skill_id: Identifiant de la competence
            version: Version specifique (optionnel)
            **kwargs: Arguments pour l'instantiation
            
        Returns:
            BaseSkill: Instance de la competence
            
        Raises:
            SkillNotFoundError: Si la competence n'existe pas
        """
        # Recuperer la classe
        skill_class = self.get(skill_id, version)
        
        # Creer une nouvelle instance
        skill_config = SkillConfig(
            skill_id=skill_id,
            name=self._metadata[skill_id].name,
            description=self._metadata[skill_id].description
        )
        
        try:
            instance = skill_class(
                config=skill_config,
                llm_client=kwargs.get('llm_client'),
                knowledge_base=kwargs.get('knowledge_base') or self._knowledge_base,
                **{k: v for k, v in kwargs.items() if k not in ['llm_client', 'knowledge_base']}
            )
            
            # Mise a jour des metadonnees
            self._metadata[skill_id].usage_count += 1
            self._metadata[skill_id].last_used = datetime.utcnow()
            
            logger.debug(f"Skill instance created: {skill_id}")
            return instance
            
        except Exception as e:
            logger.error(f"Failed to instantiate skill {skill_id}: {str(e)}")
            raise
    
    def get_metadata(self, skill_id: str) -> SkillMetadata:
        """
        Recupere les metadonnees d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            SkillMetadata: Metadonnees de la competence
            
        Raises:
            SkillNotFoundError: Si la competence n'existe pas
        """
        if skill_id not in self._metadata:
            raise SkillNotFoundError(
                skill_id=skill_id,
                message=f"Skill '{skill_id}' not found"
            )
        return self._metadata[skill_id]
    
    def has_skill(self, skill_id: str) -> bool:
        """
        Verifie si une competence existe.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            bool: True si la competence existe
        """
        return skill_id in self._skill_classes
    
    def list_skills(
        self,
        scope: Optional[SkillScope] = None,
        status: Optional[SkillStatus] = None,
        tag: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> List[str]:
        """
        Liste les IDs des competences avec filtres optionnels.
        
        Args:
            scope: Filtrer par portee
            status: Filtrer par statut
            tag: Filtrer par tag
            project_id: Filtrer par projet
            
        Returns:
            List[str]: Liste des IDs des competences
        """
        result = set(self._skill_classes.keys())
        
        # Filtrage
        if scope is not None:
            result = {s for s in result if self._metadata[s].scope == scope}
        
        if status is not None:
            result = {s for s in result if self._metadata[s].status == status}
        
        if tag is not None:
            result = result.intersection(self._tags_index.get(tag, set()))
        
        if project_id is not None:
            result = {s for s in result if self._metadata[s].project_id == project_id}
        
        return sorted(list(result))
    
    def list_versions(self, skill_id: str) -> List[str]:
        """
        Liste les versions disponibles d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            List[str]: Liste des versions
        """
        return self._versions.get(skill_id, [])
    
    def get_current_version(self, skill_id: str) -> Optional[str]:
        """
        Recupere la version active d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            Optional[str]: Version active ou None
        """
        return self._current_versions.get(skill_id)
    
    def set_current_version(self, skill_id: str, version: str) -> None:
        """
        Definit la version active d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            version: Version a activer
            
        Raises:
            ValueError: Si la version n'existe pas
        """
        if skill_id not in self._versions:
            raise SkillNotFoundError(skill_id=skill_id)
        
        if version not in self._versions[skill_id]:
            raise ValueError(f"Version {version} not found for skill {skill_id}")
        
        self._current_versions[skill_id] = version
        logger.info(f"Current version for {skill_id} set to {version}")
    
    # =========================================================================
    # GESTION DES TAGS
    # =========================================================================
    
    def add_tags(self, skill_id: str, tags: Set[str]) -> None:
        """
        Ajoute des tags a une competence.
        
        Args:
            skill_id: Identifiant de la competence
            tags: Tags a ajouter
        """
        if skill_id not in self._metadata:
            raise SkillNotFoundError(skill_id=skill_id)
        
        for tag in tags:
            self._metadata[skill_id].tags.add(tag)
            self._tags_index[tag].add(skill_id)
        
        logger.debug(f"Tags added to {skill_id}: {tags}")
    
    def remove_tag(self, skill_id: str, tag: str) -> None:
        """
        Supprime un tag d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            tag: Tag a supprimer
        """
        if skill_id not in self._metadata:
            raise SkillNotFoundError(skill_id=skill_id)
        
        self._metadata[skill_id].tags.discard(tag)
        self._tags_index[tag].discard(skill_id)
        
        logger.debug(f"Tag removed from {skill_id}: {tag}")
    
    def get_tags(self, skill_id: str) -> Set[str]:
        """
        Recupere les tags d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            Set[str]: Tags de la competence
        """
        if skill_id not in self._metadata:
            raise SkillNotFoundError(skill_id=skill_id)
        return self._metadata[skill_id].tags.copy()
    
    # =========================================================================
    # GESTION DES DEPENDANCES
    # =========================================================================
    
    def add_dependency(self, skill_id: str, dependency_id: str) -> None:
        """
        Ajoute une dependance a une competence.
        
        Args:
            skill_id: Identifiant de la competence
            dependency_id: Identifiant de la competence dependante
        """
        if skill_id not in self._metadata:
            raise SkillNotFoundError(skill_id=skill_id)
        
        self._dependencies[skill_id].add(dependency_id)
        self._dependents[dependency_id].add(skill_id)
        self._metadata[skill_id].dependencies.add(dependency_id)
        
        logger.debug(f"Dependency added: {skill_id} -> {dependency_id}")
    
    def get_dependencies(self, skill_id: str) -> Set[str]:
        """
        Recupere les dependances d'une competence.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            Set[str]: IDs des competences dependantes
        """
        return self._dependencies.get(skill_id, set()).copy()
    
    def get_dependents(self, skill_id: str) -> Set[str]:
        """
        Recupere les competences qui dependent de celle-ci.
        
        Args:
            skill_id: Identifiant de la competence
            
        Returns:
            Set[str]: IDs des competences qui en dependent
        """
        return self._dependents.get(skill_id, set()).copy()
    
    def get_dependency_graph(self) -> Dict[str, Set[str]]:
        """
        Recupere le graphe complet des dependances.
        
        Returns:
            Dict[str, Set[str]]: Graphe des dependances
        """
        return {k: v.copy() for k, v in self._dependencies.items()}
    
    # =========================================================================
    # PERSISTANCE
    # =========================================================================
    
    async def load_from_database(self, db_session) -> int:
        """
        Charge les competences depuis la base de donnees.
        
        Args:
            db_session: Session SQLAlchemy
            
        Returns:
            int: Nombre de competences chargees
        """
        from sqlalchemy import select
        
        try:
            stmt = select(SkillRecordModel)
            result = await db_session.execute(stmt)
            records = result.scalars().all()
            
            loaded_count = 0
            for record in records:
                try:
                    # Creer une classe dynamique pour la competence
                    # Note: Ceci est simplifie - dans la pratique, il faudrait
                    # utiliser une usine de classes ou du code generation
                    skill_class = self._create_skill_class_from_record(record)
                    self.register(
                        skill_id=record.skill_id,
                        skill_class=skill_class,
                        version="1.0.0"  # Version stockee dans les metadonnees
                    )
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"Failed to load skill {record.skill_id}: {str(e)}")
            
            logger.info(f"Loaded {loaded_count} skills from database")
            return loaded_count
            
        except Exception as e:
            logger.error(f"Failed to load skills from database: {str(e)}")
            return 0
    
    async def save_to_database(self, db_session) -> int:
        """
        Sauvegarde les competences en base de donnees.
        
        Args:
            db_session: Session SQLAlchemy
            
        Returns:
            int: Nombre de competences sauvegardees
        """
        saved_count = 0
        
        for skill_id, metadata in self._metadata.items():
            try:
                # Verification de l'existence
                from sqlalchemy import select
                stmt = select(SkillRecordModel).where(SkillRecordModel.skill_id == skill_id)
                result = await db_session.execute(stmt)
                record = result.scalar_one_or_none()
                
                if record:
                    # Mise a jour
                    record.name = metadata.name
                    record.prompt_rules = f"Version: {metadata.version}\nStatus: {metadata.status.value}"
                    # ... autres champs
                else:
                    # Creation
                    record = SkillRecordModel(
                        skill_id=skill_id,
                        name=metadata.name,
                        prompt_rules=f"Version: {metadata.version}\nStatus: {metadata.status.value}",
                        input_schema_json={},  # A remplir
                        python_code=""  # A remplir
                    )
                    db_session.add(record)
                
                saved_count += 1
                
            except Exception as e:
                logger.error(f"Failed to save skill {skill_id}: {str(e)}")
        
        await db_session.commit()
        logger.info(f"Saved {saved_count} skills to database")
        return saved_count
    
    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du registre.
        
        Returns:
            Dict: Statistiques detaillees
        """
        by_scope = defaultdict(int)
        by_status = defaultdict(int)
        
        for metadata in self._metadata.values():
            by_scope[metadata.scope.value] += 1
            by_status[metadata.status.value] += 1
        
        return {
            "total_skills": len(self._skill_classes),
            "total_instances": len(self._skills),
            "total_registrations": self._total_registrations,
            "total_errors": self._total_errors,
            "by_scope": dict(by_scope),
            "by_status": dict(by_status),
            "total_tags": len(self._tags_index),
            "skills_with_dependencies": len([s for s in self._dependencies if self._dependencies[s]]),
            "most_used": self._get_most_used_skills(5)
        }
    
    def _get_most_used_skills(self, limit: int = 5) -> List[Tuple[str, int]]:
        """
        Recupere les competences les plus utilisees.
        
        Args:
            limit: Nombre maximum de resultats
            
        Returns:
            List[Tuple[str, int]]: Liste des (skill_id, usage_count)
        """
        usage = [(s, m.usage_count) for s, m in self._metadata.items()]
        return sorted(usage, key=lambda x: x[1], reverse=True)[:limit]
    
    # =========================================================================
    # NETTOYAGE ET MAINTENANCE
    # =========================================================================
    
    def clear_cache(self) -> None:
        """Vide le cache des instances."""
        self._skills.clear()
        logger.info("Skill cache cleared")
    
    def archive_skill(self, skill_id: str) -> None:
        """
        Archive une competence (ne la supprime pas).
        
        Args:
            skill_id: Identifiant de la competence
        """
        if skill_id in self._metadata:
            self._metadata[skill_id].status = SkillStatus.ARCHIVED
            logger.info(f"Skill archived: {skill_id}")
    
    def unarchive_skill(self, skill_id: str) -> None:
        """
        Desarchive une competence.
        
        Args:
            skill_id: Identifiant de la competence
        """
        if skill_id in self._metadata:
            self._metadata[skill_id].status = SkillStatus.ACTIVE
            logger.info(f"Skill unarchived: {skill_id}")
    
    # =========================================================================
    # EVENEMENTS
    # =========================================================================
    
    def _emit_event(self, event_type: str, data: Dict) -> None:
        """
        Emet un evenement via le message bus.
        
        Args:
            event_type: Type d'evenement
            data: Donnees de l'evenement
        """
        if self._message_bus:
            try:
                # Emission asynchrone simplifiee
                logger.debug(f"Event emitted: {event_type}")
            except Exception as e:
                logger.error(f"Failed to emit event {event_type}: {str(e)}")
    
    # =========================================================================
    # METHODES UTILITAIRES PRIVEES
    # =========================================================================
    
    def _create_skill_class_from_record(self, record: SkillRecordModel) -> Type[BaseSkill]:
        """
        Cree une classe de competence a partir d'un enregistrement BDD.
        
        Args:
            record: Enregistrement de la competence
            
        Returns:
            Type[BaseSkill]: Classe de competence
        """
        # Implementation simplifiee - dans la pratique, il faudrait
        # utiliser des techniques de generation de code plus avancees
        
        # Creer une classe dynamique
        class DynamicSkill(BaseSkill):
            skill_id = record.skill_id
            name = record.name
            description = record.name
            
            async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "status": "SUCCESS",
                    "result": f"Executing {self.skill_id} with params: {params}"
                }
            
            def get_system_prompt_rules(self) -> str:
                return record.prompt_rules or f"Execute skill: {self.skill_id}"
        
        # Ajouter le schema si disponible
        if record.input_schema_json:
            from pydantic import create_model
            try:
                fields = {}
                for k, v in record.input_schema_json.items():
                    fields[k] = (type(v), ...)
                DynamicSkill.input_schema = create_model(f"{record.skill_id}_Input", **fields)
            except Exception as e:
                logger.warning(f"Failed to create schema for {record.skill_id}: {str(e)}")
        
        return DynamicSkill
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<SkillRegistry skills={len(self._skill_classes)} instances={len(self._skills)}>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le registre en dictionnaire.
        
        Returns:
            Dict: Representation du registre
        """
        return {
            "skills": list(self._skill_classes.keys()),
            "instances": list(self._skills.keys()),
            "metadata": {k: v.to_dict() for k, v in self._metadata.items()},
            "stats": self.get_stats()
        }


# =============================================================================
# DECORATEUR POUR L'ENREGISTREMENT AUTOMATIQUE
# =============================================================================

def register_skill(
    skill_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    version: str = "1.0.0",
    tags: Optional[Set[str]] = None,
    scope: SkillScope = SkillScope.GLOBAL
):
    """
    Decorateur pour enregistrer automatiquement une competence.
    
    Usage:
        @register_skill("erc20_generation", name="ERC20 Generator")
        class ERC20Skill(BaseSkill):
            ...
    
    Args:
        skill_id: Identifiant de la competence
        name: Nom de la competence (optionnel)
        description: Description (optionnel)
        version: Version (defaut: 1.0.0)
        tags: Tags pour la recherche (optionnel)
        scope: Portee de la competence (defaut: GLOBAL)
    
    Returns:
        Callable: Decorateur
    """
    def decorator(skill_class: Type[BaseSkill]) -> Type[BaseSkill]:
        # Recuperer le nom et la description depuis la classe si non fournis
        if name is None and hasattr(skill_class, 'name'):
            skill_class.name = skill_class.name
        else:
            skill_class.name = name or skill_id
        
        if description is None and hasattr(skill_class, 'description'):
            skill_class.description = skill_class.description
        else:
            skill_class.description = description or f"Skill: {skill_id}"
        
        # Creer les metadonnees
        metadata = SkillMetadata(
            skill_id=skill_id,
            name=skill_class.name,
            description=skill_class.description,
            version=version,
            scope=scope,
            tags=tags or set()
        )
        
        # Enregistrer automatiquement
        registry = SkillRegistry()
        registry.register(skill_id, skill_class, metadata, version)
        
        logger.info(f"Auto-registered skill: {skill_id}")
        return skill_class
    
    return decorator