# src/agents/base/skill.py

"""
Base skill class for the Smart Contract Dev Pipeline.
F15 – src/agents/base/skill.py

Rôle Fonctionnel : Encapsule une competence metier modulaire injectable.
Ce module definit la classe de base pour toutes les competences expertes
du pipeline. Une competence est un module autonome comprenant trois
composants indissociables:
1. Prompt Template & Rules: Directives d'expertise metier
2. Tooling Executable: Wrapper Python encapsulant les appels systeme
3. Schema Pydantic: Contrat de donnees strict pour les entrees/sorties

Les competences sont au coeur du moteur d'acquisition dynamique (Skill Engine)
et peuvent etre creees a la volee par l'Agent Architecte.
"""
from abc import ABC, abstractmethod
from pydantic import BaseModel, ValidationError
from typing import Dict, Any, Type, Optional, List, Tuple
from datetime import datetime
import json
import logging
import hashlib
from enum import Enum

# Import des modules du pipeline
from src.core.models import Skill as SkillConfig
from src.core.exceptions import PipelineError, LLMError

# Configuration du logging
logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """
    Enum des statuts possibles pour une competence.
    """
    INITIALIZED = "initialized"
    VALIDATED = "validated"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"


class BaseSkill(ABC):
    """
    Classe de base pour toutes les competences du pipeline.
    
    Une competence est un module autonome qui encapsule une expertise metier.
    Elle est composee de:
    - Des regles de prompt (expertise)
    - Un wrapper d'outils (execution)
    - Un schema Pydantic (validation)
    
    Les competences peuvent etre:
    - Pre-definies: Incluses dans le catalogue initial
    - Dynamiques: Creees a la volee par l'Agent Architecte
    - Reutilisables: Stockees dans le SkillRegistry pour d'autres projets
    
    Attributes:
        skill_id (str): Identifiant unique de la competence
        name (str): Nom descriptif de la competence
        description (str): Description detaillee de la competence
        input_schema (Type[BaseModel]): Schema Pydantic pour la validation
        version (str): Version de la competence (semver)
        status (SkillStatus): Statut actuel de la competence
        metadata (Dict): Metadonnees supplementaires
        llm_client: Client LLM pour les appels IA
        knowledge_base: Base de connaissances pour le RAG
        cache_enabled (bool): Active la mise en cache des resultats
        execution_history (List[Dict]): Historique des executions
    """
    
    # Attributs de classe - doivent etre definis par les classes filles
    skill_id: str = None
    name: str = None
    description: str = None
    input_schema: Type[BaseModel] = None
    version: str = "1.0.0"
    
    def __init__(
        self, 
        config: SkillConfig,
        llm_client = None,
        knowledge_base = None,
        cache_enabled: bool = True,
        max_retries: int = 3
    ):
        """
        Initialise une nouvelle competence.
        
        Args:
            config: Configuration de la competence (SkillConfig)
            llm_client: Client LLM pour les appels IA (optionnel)
            knowledge_base: Base de connaissances pour le RAG (optionnel)
            cache_enabled: Active la mise en cache (defaut: True)
            max_retries: Nombre maximum de tentatives (defaut: 3)
        """
        # Validation de la configuration
        if not config or not config.skill_id:
            raise ValueError("Skill configuration is required with a valid skill_id")
        
        # Attribution des proprietes depuis la config
        self.skill_id = config.skill_id
        self.name = config.name
        self.description = getattr(config, 'description', 'No description provided')
        
        # Si input_schema n'est pas defini par la classe fille, essayer de le charger
        if not self.input_schema:
            try:
                from pydantic import create_model
                # Creation d'un modele dynamique depuis la config
                self.input_schema = self._create_dynamic_schema(config)
                logger.info(f"Dynamic schema created for skill {self.skill_id}")
            except Exception as e:
                logger.warning(f"Could not create dynamic schema: {str(e)}")
        
        self.config = config
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self.cache_enabled = cache_enabled
        self.max_retries = max_retries
        self.status = SkillStatus.INITIALIZED
        self.metadata: Dict[str, Any] = {
            "created_at": datetime.utcnow().isoformat(),
            "version": self.version,
            "cache_enabled": cache_enabled
        }
        self.execution_history: List[Dict] = []
        self._cache: Dict[str, Any] = {}
        self._execution_count = 0
        
        logger.info(f"Skill initialized: {self.skill_id} v{self.version}")

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute la competence avec les parametres donnes.
        
        Cette methode doit etre implementee par chaque competence specifique.
        Elle inclut automatiquement:
        - La validation des parametres
        - La gestion des erreurs
        - Le logging d'execution
        - La mise en cache (si activee)
        
        Args:
            params: Parametres d'entree pour la competence
            
        Returns:
            Dict contenant le resultat de l'execution
            
        Raises:
            ValidationError: Si les parametres sont invalides
            LLMError: Si une erreur LLM survient
            PipelineError: Pour les autres erreurs du pipeline
        """
        pass

    @abstractmethod
    def get_system_prompt_rules(self) -> str:
        """
        Retourne les regles systeme pour le prompt.
        
        Ces regles sont injectees dans le prompt de l'agent pour guider
        le comportement du LLM. Elles doivent inclure:
        - Les contraintes metier
        - Les anti-patterns a eviter
        - Les exemples concrets (few-shot)
        
        Returns:
            str: Regles systeme formatees pour le prompt
        """
        pass

    async def execute_with_validation(
        self, 
        params: Dict[str, Any],
        validate_output: bool = True
    ) -> Dict[str, Any]:
        """
        Execute la competence avec validation complete.
        
        Cette methode encapsule l'execution avec:
        - Validation des parametres d'entree
        - Verification du cache
        - Execution avec retry
        - Validation de la sortie
        - Logging et metriques
        
        Args:
            params: Parametres d'entree
            validate_output: Valider la sortie (defaut: True)
            
        Returns:
            Dict: Resultat valide de l'execution
            
        Raises:
            ValidationError: Si la validation des entrees/sorties echoue
        """
        start_time = datetime.utcnow()
        self.status = SkillStatus.EXECUTING
        
        try:
            # 1. Validation des parametres d'entree
            validated_params = self.validate_parameters(params)
            logger.debug(f"Parameters validated for skill {self.skill_id}")
            
            # 2. Verification du cache
            cache_key = self._generate_cache_key(validated_params)
            if self.cache_enabled and cache_key in self._cache:
                logger.info(f"Cache hit for skill {self.skill_id}")
                self.status = SkillStatus.CACHED
                cached_result = self._cache[cache_key]
                cached_result["_from_cache"] = True
                return cached_result
            
            # 3. Execution avec retry
            result = None
            last_error = None
            
            for attempt in range(self.max_retries):
                try:
                    # Preparation du contexte
                    context = self._prepare_execution_context(validated_params)
                    
                    # Execution de la competence
                    result = await self.execute(context)
                    
                    # Validation de la sortie
                    if validate_output:
                        self._validate_output(result)
                    
                    # Succes - mise en cache
                    if self.cache_enabled:
                        self._cache[cache_key] = result
                    
                    self.status = SkillStatus.COMPLETED
                    self._execution_count += 1
                    
                    # Ajout des metriques
                    result["_metadata"] = {
                        "skill_id": self.skill_id,
                        "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                        "attempt": attempt + 1,
                        "cached": False,
                        "version": self.version
                    }
                    
                    # Logging
                    await self._log_execution(params, result, success=True)
                    
                    logger.info(f"Skill {self.skill_id} executed successfully")
                    return result
                    
                except (ValidationError, LLMError) as e:
                    last_error = str(e)
                    logger.warning(
                        f"Skill {self.skill_id} failed (attempt {attempt + 1}/{self.max_retries}): {last_error}"
                    )
                    
                    # Si ce n'est pas la derniere tentative, attendre
                    if attempt < self.max_retries - 1:
                        import asyncio
                        wait_time = 2 ** (attempt + 1)  # Backoff exponentiel
                        await asyncio.sleep(wait_time)
                    else:
                        raise
                        
                except Exception as e:
                    logger.error(f"Unexpected error in skill {self.skill_id}: {str(e)}")
                    raise PipelineError(f"Skill execution failed: {str(e)}")
            
            # Si on arrive ici, toutes les tentatives ont echoue
            self.status = SkillStatus.FAILED
            raise PipelineError(f"All retries failed for skill {self.skill_id}: {last_error}")
            
        except Exception as e:
            self.status = SkillStatus.FAILED
            await self._log_execution(params, None, success=False, error=str(e))
            raise
        
        finally:
            self.status = SkillStatus.COMPLETED if self.status != SkillStatus.FAILED else self.status

    def validate_parameters(self, params: Dict[str, Any]) -> BaseModel:
        """
        Valide les parametres d'entree avec le schema Pydantic.
        
        Args:
            params: Parametres a valider
            
        Returns:
            BaseModel: Modele valide
            
        Raises:
            ValidationError: Si les parametres sont invalides
        """
        if not self.input_schema:
            logger.warning(f"No input schema defined for skill {self.skill_id}")
            # Retourne un modele vide si pas de schema
            from pydantic import create_model
            return create_model("EmptyModel")(**{})
        
        try:
            validated = self.input_schema(**params)
            logger.debug(f"Parameters validated successfully for {self.skill_id}")
            return validated
        except ValidationError as e:
            logger.error(f"Parameter validation failed for {self.skill_id}: {str(e)}")
            raise

    def _validate_output(self, output: Dict[str, Any]) -> None:
        """
        Valide la sortie de la competence.
        
        Args:
            output: Sortie a valider
            
        Raises:
            ValidationError: Si la sortie est invalide
        """
        if not isinstance(output, dict):
            raise ValidationError("Output must be a dictionary")
        
        if "status" not in output:
            raise ValidationError("Output must contain 'status' field")
        
        if output["status"] not in ["SUCCESS", "FAILED"]:
            raise ValidationError(f"Invalid status: {output['status']}")

    def get_system_prompt_rules(self) -> str:
        """
        Retourne les regles systeme pour le prompt.
        
        Cette methode peut etre surchargee par les classes filles
        pour fournir des regles specifiques.
        
        Returns:
            str: Regles systeme par defaut
        """
        return f"""
        You are using the skill '{self.name}' ({self.skill_id}).
        Description: {self.description}
        
        Guidelines:
        - Follow best practices for smart contract development
        - Use secure coding patterns
        - Document all functions thoroughly
        - Include proper error handling
        - Follow the input/output schema defined for this skill
        """

    def set_llm_client(self, client) -> None:
        """
        Injecte le client LLM.
        
        Args:
            client: Client LLM a utiliser
        """
        self.llm_client = client
        logger.debug(f"LLM client set for skill {self.skill_id}")

    def set_knowledge_base(self, kb) -> None:
        """
        Injecte la base de connaissances.
        
        Args:
            kb: Base de connaissances a utiliser
        """
        self.knowledge_base = kb
        logger.debug(f"Knowledge base set for skill {self.skill_id}")

    def enable_cache(self) -> None:
        """Active la mise en cache des resultats."""
        self.cache_enabled = True
        logger.info(f"Cache enabled for skill {self.skill_id}")

    def disable_cache(self) -> None:
        """Desactive la mise en cache des resultats."""
        self.cache_enabled = False
        logger.info(f"Cache disabled for skill {self.skill_id}")

    def clear_cache(self) -> None:
        """Vide le cache de la competence."""
        cache_size = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared for skill {self.skill_id} ({cache_size} entries)")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques d'execution de la competence.
        
        Returns:
            Dict: Statistiques d'execution
        """
        successful = [h for h in self.execution_history if h.get("success", False)]
        failed = [h for h in self.execution_history if not h.get("success", True)]
        
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "total_executions": len(self.execution_history),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / len(self.execution_history) if self.execution_history else 0,
            "cache_size": len(self._cache),
            "cache_enabled": self.cache_enabled,
            "execution_count": self._execution_count,
            "metadata": self.metadata
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit la competence en dictionnaire pour la serialisation.
        
        Returns:
            Dict: Representation dictionnaire de la competence
        """
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status.value,
            "metadata": self.metadata,
            "cache_enabled": self.cache_enabled,
            "execution_count": self._execution_count,
            "statistics": self.get_statistics()
        }

    def _generate_cache_key(self, params: BaseModel) -> str:
        """
        Genere une cle de cache a partir des parametres.
        
        Args:
            params: Parametres valides
            
        Returns:
            str: Cle de cache unique
        """
        # Serialisation stable des parametres
        param_str = json.dumps(params.dict(), sort_keys=True)
        return hashlib.sha256(param_str.encode()).hexdigest()

    def _prepare_execution_context(self, params: BaseModel) -> Dict[str, Any]:
        """
        Prepare le contexte d'execution avec les connaissances RAG.
        
        Args:
            params: Parametres valides
            
        Returns:
            Dict: Contexte d'execution enrichi
        """
        context = params.dict()
        
        # Ajout des connaissances RAG si disponibles
        if self.knowledge_base:
            try:
                # Recherche de contextes pertinents
                query = f"{self.name} {self.skill_id} {context.get('description', '')}"
                relevant_docs = self.knowledge_base.query_context(query)
                if relevant_docs:
                    context["_rag_context"] = relevant_docs
                    logger.debug(f"RAG context added ({len(relevant_docs)} docs)")
            except Exception as e:
                logger.warning(f"RAG query failed: {str(e)}")
        
        return context

    async def _log_execution(
        self, 
        params: Dict[str, Any], 
        result: Optional[Dict[str, Any]], 
        success: bool,
        error: Optional[str] = None
    ) -> None:
        """
        Enregistre l'execution dans l'historique.
        
        Args:
            params: Parametres d'entree
            result: Resultat (si success)
            success: Indique si l'execution a reussi
            error: Message d'erreur (si echec)
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "params": params,
            "success": success,
            "skill_id": self.skill_id,
            "version": self.version
        }
        
        if success and result:
            entry["result"] = result
        if error:
            entry["error"] = error
        
        self.execution_history.append(entry)
        
        # Limite de l'historique (1000 entrées max)
        if len(self.execution_history) > 1000:
            self.execution_history = self.execution_history[-1000:]

    def _create_dynamic_schema(self, config: SkillConfig) -> Type[BaseModel]:
        """
        Cree un schema Pydantic dynamique a partir de la configuration.
        
        Args:
            config: Configuration de la competence
            
        Returns:
            Type[BaseModel]: Schema Pydantic dynamique
        """
        from pydantic import create_model
        
        # Extraction des champs depuis la config
        fields = {}
        if hasattr(config, 'input_schema') and config.input_schema:
            for field_name, field_type in config.input_schema.items():
                fields[field_name] = (field_type, ...)
        
        # Creation du modele dynamique
        model_name = f"{self.skill_id}_Input"
        return create_model(model_name, **fields)

    def __repr__(self) -> str:
        """
        Representation lisible de la competence.
        """
        return f"<BaseSkill(skill_id='{self.skill_id}', name='{self.name}', status='{self.status.value}')>"


# =============================================================================
# CLASSE DE BASE POUR LES COMPETENCES AVEC EXECUTION LLM
# =============================================================================

class BaseLLMSkill(BaseSkill):
    """
    Classe de base pour les competences qui utilisent un LLM.
    
    Cette classe etend BaseSkill pour les competences qui doivent
    faire appel a un LLM pour l'execution.
    """
    
    def __init__(
        self,
        config: SkillConfig,
        llm_client=None,
        knowledge_base=None,
        cache_enabled: bool = True,
        max_retries: int = 3,
        temperature: float = 0.7
    ):
        super().__init__(config, llm_client, knowledge_base, cache_enabled, max_retries)
        self.temperature = temperature
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute la competence avec le LLM.
        
        Cette implementation par defaut fait appel au LLM avec:
        - Les regles systeme de la competence
        - Le prompt formatte avec les parametres
        - La temperature configuree
        
        Les classes filles peuvent surcharger cette methode
        pour un comportement plus specifique.
        """
        if not self.llm_client:
            raise LLMError(f"No LLM client configured for skill {self.skill_id}")
        
        # Formatage du prompt
        prompt = self._format_prompt(params)
        
        # Appel au LLM
        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=self.get_system_prompt_rules(),
                temperature=self.temperature
            )
            
            return {
                "status": "SUCCESS",
                "result": response,
                "prompt": prompt
            }
        except Exception as e:
            raise LLMError(f"LLM execution failed: {str(e)}")
    
    def _format_prompt(self, params: Dict[str, Any]) -> str:
        """
        Formate le prompt a partir des parametres.
        
        Args:
            params: Parametres d'entree
            
        Returns:
            str: Prompt formatte
        """
        # Implementation par defaut - peut etre surchargee
        prompt_parts = [
            f"Executing skill: {self.name} ({self.skill_id})",
            f"Description: {self.description}",
            "",
            "Parameters:"
        ]
        
        for key, value in params.items():
            prompt_parts.append(f"- {key}: {value}")
        
        return "\n".join(prompt_parts)
    
    def __repr__(self) -> str:
        return f"<BaseLLMSkill(skill_id='{self.skill_id}', name='{self.name}', temperature={self.temperature})>"