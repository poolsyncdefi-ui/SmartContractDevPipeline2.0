# src/agents/factory/agent_factory.py

"""
Agent factory for the Smart Contract Dev Pipeline.
F18 – src/agents/factory/agent_factory.py

Rôle Fonctionnel : Fabrique logicielle instanciant les agents avec leurs competences.
Cette usine permet de creer des agents sur mesure en assemblant des competences
expertes (BaseSkill) instanciees a chaud. Elle supporte:
- La creation d'agents avec des combinaisons de competences
- L'injection de connaissances via RAG
- La validation des bonnes pratiques
- La mise en cache des agents pour les performances
- La gestion des configurations de projet

Le processus de creation suit les etapes:
1. Selection du template d'agent (role)
2. Recuperation des competences depuis le SkillRegistry
3. Instantiation des competences avec injection des dependances
4. Assemblage de l'agent final avec ses competences
5. Application des bonnes pratiques et validations
"""
from typing import List, Type, Dict, Any, Optional, Set, Union
from datetime import datetime
import logging
import asyncio
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.agents.base.abstract_agent import AbstractAgent
from src.agents.base.skill import BaseSkill
from src.agents.base.best_practice import BaseBestPractice
from src.agents.factory.skill_registry import SkillRegistry, SkillScope, SkillMetadata
from src.core.models import Skill as SkillConfig, BestPractice as BestPracticeConfig, ProjectConfig
from src.core.exceptions import PipelineError, SkillNotFoundError
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase
from src.communication.message_bus import MessageBus

# Configuration du logging
logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """
    Roles d'agents disponibles.
    """
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    SECURITY = "security"
    FEEDBACK = "feedback"
    TESTER = "tester"
    DEPLOYER = "deployer"
    CUSTOM = "custom"


@dataclass
class AgentCreationContext:
    """
    Contexte pour la creation d'un agent.
    
    Attributes:
        project_id (Optional[str]): ID du projet associe
        config (Optional[ProjectConfig]): Configuration du projet
        llm_client (Optional[LLMClient]): Client LLM pour l'agent
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances
        message_bus (Optional[MessageBus]): Bus de messages
        extra_params (Dict): Parametres supplementaires
    """
    project_id: Optional[str] = None
    config: Optional[ProjectConfig] = None
    llm_client: Optional[LLMClient] = None
    knowledge_base: Optional[KnowledgeBase] = None
    message_bus: Optional[MessageBus] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCreationResult:
    """
    Resultat de la creation d'un agent.
    
    Attributes:
        agent (AbstractAgent): Agent cree
        created_at (datetime): Date de creation
        duration (float): Duree de creation en secondes
        skills_used (List[str]): IDs des competences utilisees
        practices_applied (List[str]): IDs des pratiques appliquees
        success (bool): Succes de la creation
        error (Optional[str]): Message d'erreur si echec
    """
    agent: Optional[AbstractAgent] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    duration: float = 0.0
    skills_used: List[str] = field(default_factory=list)
    practices_applied: List[str] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


class AgentFactory:
    """
    Fabrique d'instanciation d'agents.
    
    Cette usine permet de creer des agents dynamiquement en assemblant
    des competences et en appliquant des bonnes pratiques.
    
    Attributes:
        registry (SkillRegistry): Registre des competences
        llm_client (Optional[LLMClient]): Client LLM par defaut
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances par defaut
        message_bus (Optional[MessageBus]): Bus de messages par defaut
        _templates (Dict[str, Type[AbstractAgent]]): Templates d'agents
        _skill_configs (Dict[str, SkillConfig]): Configurations des competences
        _practice_configs (Dict[str, BestPracticeConfig]): Configurations des pratiques
        _practice_instances (Dict[str, BaseBestPractice]): Instances des pratiques
        _cache (Dict[str, AbstractAgent]): Cache des agents crees
        _creation_stats (Dict): Statistiques de creation
        _default_practices (Set[str]): IDs des pratiques par defaut
    """
    
    def __init__(
        self,
        registry: SkillRegistry,
        llm_client: Optional[LLMClient] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        message_bus: Optional[MessageBus] = None,
        cache_enabled: bool = True,
        default_practices: Optional[Set[str]] = None
    ):
        """
        Initialise la fabrique d'agents.
        
        Args:
            registry: Registre des competences
            llm_client: Client LLM par defaut (optionnel)
            knowledge_base: Base de connaissances par defaut (optionnel)
            message_bus: Bus de messages par defaut (optionnel)
            cache_enabled: Active la mise en cache des agents (defaut: True)
            default_practices: IDs des pratiques par defaut (optionnel)
        """
        self.registry = registry
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self.message_bus = message_bus
        self.cache_enabled = cache_enabled
        self._templates: Dict[str, Type[AbstractAgent]] = {}
        self._skill_configs: Dict[str, SkillConfig] = {}
        self._practice_configs: Dict[str, BestPracticeConfig] = {}
        self._practice_instances: Dict[str, BaseBestPractice] = {}
        self._cache: Dict[str, AbstractAgent] = {}
        self._default_practices = default_practices or set()
        
        # Statistiques
        self._creation_stats = {
            "total_creations": 0,
            "successful_creations": 0,
            "failed_creations": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "by_role": {},
            "by_skill": {}
        }
        
        # Enregistrer les templates par defaut
        self._register_default_templates()
        
        logger.info("AgentFactory initialized")
    
    # =========================================================================
    # ENREGISTREMENT DES TEMPLATES
    # =========================================================================
    
    def register_agent_template(
        self,
        role_name: str,
        agent_class: Type[AbstractAgent],
        default_skills: Optional[List[str]] = None,
        default_practices: Optional[List[str]] = None
    ) -> None:
        """
        Enregistre un template d'agent.
        
        Args:
            role_name: Nom du role (ex: 'developer', 'architect')
            agent_class: Classe de l'agent
            default_skills: Competences par defaut pour ce role (optionnel)
            default_practices: Pratiques par defaut pour ce role (optionnel)
        """
        if not issubclass(agent_class, AbstractAgent):
            raise ValueError(f"agent_class must be a subclass of AbstractAgent")
        
        self._templates[role_name] = agent_class
        
        # Si des competences par defaut sont fournies, les enregistrer dans la config
        if default_skills:
            for skill_id in default_skills:
                if skill_id not in self._skill_configs:
                    # Creer une configuration par defaut si elle n'existe pas
                    self._skill_configs[skill_id] = SkillConfig(
                        skill_id=skill_id,
                        name=skill_id,
                        description=f"Default skill for {role_name}"
                    )
        
        # Ajout des pratiques par defaut
        if default_practices:
            self._default_practices.update(default_practices)
        
        logger.info(f"Agent template registered: {role_name} with {len(default_skills or [])} default skills")
    
    def _register_default_templates(self) -> None:
        """
        Enregistre les templates d'agents par defaut.
        
        Cette methode est appelee automatiquement a l'initialisation.
        """
        # Les templates seront importes depuis les modules d'agents
        # Cette methode est un placeholder pour les imports futurs
        pass
    
    # =========================================================================
    # CHARGEMENT DES CONFIGURATIONS
    # =========================================================================
    
    def load_configs(
        self,
        skill_configs: Dict[str, SkillConfig],
        practice_configs: Dict[str, BestPracticeConfig]
    ) -> None:
        """
        Charge les configurations des competences et des pratiques.
        
        Args:
            skill_configs: Dictionnaire des configurations de competences
            practice_configs: Dictionnaire des configurations de pratiques
        """
        self._skill_configs = skill_configs
        self._practice_configs = practice_configs
        
        # Charger les instances de pratiques
        for practice_id, config in practice_configs.items():
            try:
                practice = self._create_practice_instance(config)
                if practice:
                    self._practice_instances[practice_id] = practice
            except Exception as e:
                logger.error(f"Failed to create practice instance {practice_id}: {str(e)}")
        
        logger.info(f"Loaded {len(skill_configs)} skill configs and {len(practice_configs)} practice configs")
    
    def add_practice(self, practice: BaseBestPractice) -> None:
        """
        Ajoute une pratique a la fabrique.
        
        Args:
            practice: Instance de pratique a ajouter
        """
        practice_id = practice.config.practice_id
        self._practice_instances[practice_id] = practice
        self._practice_configs[practice_id] = practice.config
        self._default_practices.add(practice_id)
        logger.info(f"Practice added: {practice_id}")
    
    # =========================================================================
    # CREATION D'AGENTS
    # =========================================================================
    
    def create_agent(
        self,
        agent_id: str,
        role_name: str,
        skill_ids: List[str],
        context: Optional[AgentCreationContext] = None,
        practice_ids: Optional[List[str]] = None,
        use_cache: bool = True,
        skip_validation: bool = False
    ) -> AbstractAgent:
        """
        Cree un agent avec les competences specifiees.
        
        Args:
            agent_id: Identifiant unique de l'agent
            role_name: Role de l'agent (ex: 'developer', 'architect')
            skill_ids: Liste des IDs des competences a utiliser
            context: Contexte de creation (optionnel)
            practice_ids: Liste des pratiques a appliquer (optionnel)
            use_cache: Utiliser le cache (defaut: True)
            skip_validation: Ignorer les validations (defaut: False)
            
        Returns:
            AbstractAgent: Agent cree
            
        Raises:
            ValueError: Si le template n'existe pas ou si les competences sont invalides
            SkillNotFoundError: Si une competence n'existe pas
            PipelineError: Pour les autres erreurs de creation
        """
        start_time = datetime.utcnow()
        context = context or AgentCreationContext()
        
        # Mise a jour des statistiques
        self._creation_stats["total_creations"] += 1
        
        # Verification du cache
        cache_key = self._generate_cache_key(agent_id, role_name, skill_ids, practice_ids)
        if use_cache and self.cache_enabled and cache_key in self._cache:
            self._creation_stats["cache_hits"] += 1
            logger.debug(f"Agent {agent_id} returned from cache")
            return self._cache[cache_key]
        
        self._creation_stats["cache_misses"] += 1
        
        try:
            # 1. Recuperation du template
            agent_cls = self._templates.get(role_name)
            if not agent_cls:
                raise ValueError(f"Agent template '{role_name}' not found")
            
            # 2. Preparation des competences
            skills = self._prepare_skills(skill_ids, context)
            
            # 3. Validation des competences (si non ignore)
            if not skip_validation:
                self._validate_skills(skills, context)
            
            # 4. Creation de l'agent
            agent = agent_cls(
                agent_id=agent_id,
                name=role_name,
                skills=skills,
                llm_client=context.llm_client or self.llm_client,
                knowledge_base=context.knowledge_base or self.knowledge_base
            )
            
            # 5. Application des pratiques
            practices = self._prepare_practices(practice_ids, context)
            if practices:
                self._apply_practices(agent, practices)
            
            # 6. Notification via message bus
            if context.message_bus or self.message_bus:
                self._notify_agent_creation(agent, context)
            
            # 7. Mise en cache
            if use_cache and self.cache_enabled:
                self._cache[cache_key] = agent
                self._cache[agent_id] = agent  # Index par ID aussi
            
            # Mise a jour des statistiques
            self._creation_stats["successful_creations"] += 1
            self._creation_stats["by_role"][role_name] = self._creation_stats["by_role"].get(role_name, 0) + 1
            for skill_id in skill_ids:
                self._creation_stats["by_skill"][skill_id] = self._creation_stats["by_skill"].get(skill_id, 0) + 1
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Agent {agent_id} created in {duration:.2f}s with {len(skills)} skills")
            
            return agent
            
        except Exception as e:
            self._creation_stats["failed_creations"] += 1
            logger.error(f"Failed to create agent {agent_id}: {str(e)}")
            raise PipelineError(f"Agent creation failed: {str(e)}")
    
    async def create_agent_async(
        self,
        agent_id: str,
        role_name: str,
        skill_ids: List[str],
        context: Optional[AgentCreationContext] = None,
        practice_ids: Optional[List[str]] = None,
        use_cache: bool = True,
        skip_validation: bool = False
    ) -> AbstractAgent:
        """
        Cree un agent de maniere asynchrone.
        
        Cette methode est identique a create_agent mais permet des
        operations asynchrones si necessaire (ex: chargement RAG).
        
        Args:
            Mêmes parametres que create_agent
            
        Returns:
            AbstractAgent: Agent cree
        """
        # Pour l'instant, appels synchrones, mais prete pour des extensions async
        return self.create_agent(
            agent_id=agent_id,
            role_name=role_name,
            skill_ids=skill_ids,
            context=context,
            practice_ids=practice_ids,
            use_cache=use_cache,
            skip_validation=skip_validation
        )
    
    def create_agent_with_defaults(
        self,
        agent_id: str,
        role_name: str,
        context: Optional[AgentCreationContext] = None,
        practice_ids: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> AbstractAgent:
        """
        Cree un agent avec les competences par defaut du role.
        
        Args:
            agent_id: Identifiant unique de l'agent
            role_name: Role de l'agent
            context: Contexte de creation (optionnel)
            practice_ids: Pratiques a appliquer (optionnel)
            use_cache: Utiliser le cache (defaut: True)
            
        Returns:
            AbstractAgent: Agent cree
        """
        # Recuperer les competences par defaut pour le role
        # Cette methode peut etre surchargee par des configurations specifiques
        default_skills = self._get_default_skills_for_role(role_name)
        
        if not default_skills:
            logger.warning(f"No default skills found for role {role_name}")
        
        return self.create_agent(
            agent_id=agent_id,
            role_name=role_name,
            skill_ids=default_skills,
            context=context,
            practice_ids=practice_ids,
            use_cache=use_cache
        )
    
    def create_development_squad(
        self,
        project_id: str,
        context: Optional[AgentCreationContext] = None,
        **kwargs
    ) -> Dict[str, AbstractAgent]:
        """
        Cree une equipe complete d'agents pour un projet.
        
        Args:
            project_id: ID du projet
            context: Contexte de creation (optionnel)
            **kwargs: Parametres supplementaires pour la creation
            
        Returns:
            Dict[str, AbstractAgent]: Dictionnaire des agents crees par role
        """
        context = context or AgentCreationContext(project_id=project_id)
        
        roles = {
            AgentRole.ARCHITECT: ["project_analysis", "task_planning"],
            AgentRole.DEVELOPER: ["solidity_generation", "test_generation"],
            AgentRole.SECURITY: ["security_audit", "formal_verification"],
            AgentRole.FEEDBACK: ["code_review", "optimization"]
        }
        
        agents = {}
        
        for role, skill_ids in roles.items():
            try:
                agent_id = f"{project_id}_{role.value}"
                agent = self.create_agent(
                    agent_id=agent_id,
                    role_name=role.value,
                    skill_ids=skill_ids,
                    context=context,
                    **kwargs
                )
                agents[role.value] = agent
                logger.info(f"Created {role.value} agent for project {project_id}")
            except Exception as e:
                logger.error(f"Failed to create {role.value} agent: {str(e)}")
                # Continuation sur erreur pour creer les autres agents
        
        return agents
    
    # =========================================================================
    # GESTION DU CACHE
    # =========================================================================
    
    def clear_cache(self) -> None:
        """Vide le cache des agents."""
        cache_size = len(self._cache)
        self._cache.clear()
        logger.info(f"Agent cache cleared ({cache_size} entries)")
    
    def get_cached_agent(self, agent_id: str) -> Optional[AbstractAgent]:
        """
        Recupere un agent depuis le cache.
        
        Args:
            agent_id: ID de l'agent
            
        Returns:
            Optional[AbstractAgent]: Agent ou None
        """
        return self._cache.get(agent_id)
    
    def remove_cached_agent(self, agent_id: str) -> bool:
        """
        Supprime un agent du cache.
        
        Args:
            agent_id: ID de l'agent
            
        Returns:
            bool: True si supprime, False sinon
        """
        if agent_id in self._cache:
            del self._cache[agent_id]
            # Nettoyer aussi les cles de cache derives
            keys_to_remove = [k for k in self._cache if k.startswith(f"{agent_id}_")]
            for key in keys_to_remove:
                del self._cache[key]
            logger.info(f"Agent {agent_id} removed from cache")
            return True
        return False
    
    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de la fabrique.
        
        Returns:
            Dict: Statistiques detaillees
        """
        stats = self._creation_stats.copy()
        stats.update({
            "cache_size": len(self._cache),
            "templates_available": len(self._templates),
            "skills_available": len(self._skill_configs),
            "practices_available": len(self._practice_instances),
            "cache_hit_rate": (
                stats["cache_hits"] / (stats["cache_hits"] + stats["cache_misses"])
                if stats["cache_hits"] + stats["cache_misses"] > 0
                else 0
            ),
            "success_rate": (
                stats["successful_creations"] / stats["total_creations"]
                if stats["total_creations"] > 0
                else 0
            )
        })
        return stats
    
    # =========================================================================
    # METHODES PRIVEES
    # =========================================================================
    
    def _prepare_skills(
        self,
        skill_ids: List[str],
        context: AgentCreationContext
    ) -> List[BaseSkill]:
        """
        Prepare les instances de competences.
        
        Args:
            skill_ids: IDs des competences
            context: Contexte de creation
            
        Returns:
            List[BaseSkill]: Liste des competences instanciees
        """
        skills = []
        missing_skills = []
        
        for skill_id in skill_ids:
            try:
                # Recuperer la classe depuis le registre
                skill_cls = self.registry.get(skill_id)
                skill_config = self._skill_configs.get(skill_id)
                
                if not skill_config:
                    # Creer une configuration par defaut
                    skill_config = SkillConfig(
                        skill_id=skill_id,
                        name=skill_id,
                        description=f"Skill: {skill_id}"
                    )
                    logger.warning(f"Using default config for skill {skill_id}")
                
                # Instancier la competence
                skill_instance = skill_cls(
                    config=skill_config,
                    llm_client=context.llm_client or self.llm_client,
                    knowledge_base=context.knowledge_base or self.knowledge_base
                )
                
                skills.append(skill_instance)
                logger.debug(f"Skill {skill_id} instantiated")
                
            except SkillNotFoundError:
                missing_skills.append(skill_id)
                logger.warning(f"Skill {skill_id} not found in registry")
        
        if missing_skills:
            raise ValueError(f"Missing skills: {', '.join(missing_skills)}")
        
        return skills
    
    def _validate_skills(
        self,
        skills: List[BaseSkill],
        context: AgentCreationContext
    ) -> None:
        """
        Valide les competences avant creation.
        
        Args:
            skills: Liste des competences
            context: Contexte de creation
            
        Raises:
            ValueError: Si une competence est invalide
        """
        for skill in skills:
            # Verification des attributs requis
            if not skill.skill_id:
                raise ValueError("Skill missing skill_id")
            if not skill.name:
                raise ValueError(f"Skill {skill.skill_id} missing name")
            if not skill.input_schema:
                logger.warning(f"Skill {skill.skill_id} missing input_schema")
            
            # Verification des dependances
            metadata = self.registry.get_metadata(skill.skill_id)
            for dep_id in metadata.dependencies:
                if not self.registry.has_skill(dep_id):
                    raise ValueError(
                        f"Skill {skill.skill_id} depends on {dep_id} which is not registered"
                    )
    
    def _prepare_practices(
        self,
        practice_ids: Optional[List[str]],
        context: AgentCreationContext
    ) -> List[BaseBestPractice]:
        """
        Prepare les instances de pratiques.
        
        Args:
            practice_ids: IDs des pratiques
            context: Contexte de creation
            
        Returns:
            List[BaseBestPractice]: Liste des pratiques instanciees
        """
        practices = []
        ids_to_use = practice_ids or list(self._default_practices)
        
        for practice_id in ids_to_use:
            if practice_id in self._practice_instances:
                practices.append(self._practice_instances[practice_id])
            else:
                logger.warning(f"Practice {practice_id} not found")
        
        return practices
    
    def _apply_practices(
        self,
        agent: AbstractAgent,
        practices: List[BaseBestPractice]
    ) -> None:
        """
        Applique les pratiques a l'agent.
        
        Args:
            agent: Agent a configurer
            practices: Liste des pratiques a appliquer
        """
        # Les pratiques sont stockees dans les metadonnees de l'agent
        if hasattr(agent, '_practices'):
            agent._practices = practices
        else:
            # Ajouter dynamiquement l'attribut
            setattr(agent, '_practices', practices)
        
        logger.info(f"Applied {len(practices)} practices to agent {agent.agent_id}")
    
    def _notify_agent_creation(
        self,
        agent: AbstractAgent,
        context: AgentCreationContext
    ) -> None:
        """
        Notifie la creation d'un agent via le message bus.
        
        Args:
            agent: Agent cree
            context: Contexte de creation
        """
        message_bus = context.message_bus or self.message_bus
        if message_bus:
            try:
                # Emission asynchrone simplifiee
                # Dans la pratique, utiliserait une methode asynchrone
                logger.debug(f"Agent creation notified: {agent.agent_id}")
            except Exception as e:
                logger.error(f"Failed to notify agent creation: {str(e)}")
    
    def _generate_cache_key(
        self,
        agent_id: str,
        role_name: str,
        skill_ids: List[str],
        practice_ids: Optional[List[str]]
    ) -> str:
        """
        Genere une cle de cache pour un agent.
        
        Args:
            agent_id: ID de l'agent
            role_name: Role de l'agent
            skill_ids: Liste des competences
            practice_ids: Liste des pratiques
            
        Returns:
            str: Cle de cache
        """
        # Une cle simple basee sur les parametres
        practice_key = ','.join(sorted(practice_ids or []))
        return f"{role_name}_{','.join(sorted(skill_ids))}_{practice_key}"
    
    def _get_default_skills_for_role(self, role_name: str) -> List[str]:
        """
        Recupere les competences par defaut pour un role.
        
        Args:
            role_name: Nom du role
            
        Returns:
            List[str]: IDs des competences par defaut
        """
        # Mapping des roles vers leurs competences par defaut
        default_mapping = {
            AgentRole.ARCHITECT.value: ["project_analysis", "task_planning", "requirement_analysis"],
            AgentRole.DEVELOPER.value: ["solidity_generation", "test_generation", "code_optimization"],
            AgentRole.SECURITY.value: ["security_audit", "formal_verification", "vulnerability_scanning"],
            AgentRole.FEEDBACK.value: ["code_review", "quality_assessment", "improvement_suggestion"],
            AgentRole.TESTER.value: ["test_generation", "test_execution", "coverage_analysis"],
            AgentRole.DEPLOYER.value: ["deployment_script", "verification", "gas_estimation"]
        }
        
        return default_mapping.get(role_name, [])
    
    def _create_practice_instance(
        self,
        config: BestPracticeConfig
    ) -> Optional[BaseBestPractice]:
        """
        Cree une instance de pratique a partir de sa configuration.
        
        Args:
            config: Configuration de la pratique
            
        Returns:
            Optional[BaseBestPractice]: Instance de pratique ou None
        """
        # Dans la pratique, cette methode utiliserait une usine de pratiques
        # Pour l'instant, retourne None (sera implemente plus tard)
        logger.debug(f"Practice instance creation not implemented for {config.practice_id}")
        return None
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<AgentFactory templates={len(self._templates)} cache={len(self._cache)}>"
    
    def to_dict(self) -> Dict:
        """
        Convertit la fabrique en dictionnaire.
        
        Returns:
            Dict: Representation de la fabrique
        """
        return {
            "templates": list(self._templates.keys()),
            "skills": list(self._skill_configs.keys()),
            "practices": list(self._practice_instances.keys()),
            "cache_size": len(self._cache),
            "stats": self.get_stats()
        }