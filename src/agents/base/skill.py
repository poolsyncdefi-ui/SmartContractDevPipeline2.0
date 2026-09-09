# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Base Skill
# ==============================================================================
# Fichier: src/agents/base/skill.py
# Description: Encapsule une compétence métier modulaire injectable avec support
#              du RAG, mise en cache, validation Pydantic et exécution LLM.
#              Version refactorisée avec intégration des nouveaux modules système.
# ==============================================================================

from abc import ABC, abstractmethod
from pydantic import BaseModel, ValidationError, create_model
from typing import Dict, Any, Type, Optional, List, Union
from datetime import datetime, timezone
import json
import logging
import hashlib
from enum import Enum
import asyncio

# Import des modules du pipeline
from src.core.models import Skill as SkillConfig
from src.core.exceptions import PipelineError, LLMError
from src.core.status_manager import StatusManager, normalize_status, status_manager
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.intelligent_cache import IntelligentCache, CacheStrategy
from src.core.contract_validator import ContractValidator, validate_contract

# Configuration du logging
logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """
    Enum des statuts possibles pour une compétence.
    """
    INITIALIZED = "initialized"
    VALIDATED = "validated"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"


class BaseSkill(ABC):
    """
    Classe de base pour toutes les compétences du pipeline.
    
    Une compétence est un module autonome qui encapsule une expertise métier.
    Elle est composée de :
    - Des règles de prompt (expertise)
    - Un wrapper d'outils (exécution)
    - Un schéma Pydantic (validation)
    
    Attributes:
        skill_id (str): Identifiant unique de la compétence
        name (str): Nom descriptif de la compétence
        description (str): Description détaillée de la compétence
        input_schema (Type[BaseModel]): Schéma Pydantic pour la validation
        version (str): Version de la compétence (semver)
        status (SkillStatus): Statut actuel de la compétence
        metadata (Dict): Métadonnées supplémentaires
        llm_client: Client LLM pour les appels IA
        knowledge_base: Base de connaissances pour le RAG
        cache_enabled (bool): Active la mise en cache des résultats
        execution_history (List[Dict]): Historique des exécutions
    """
    
    skill_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Type[BaseModel]] = None
    version: str = "1.0.0"
    
    def __init__(
        self, 
        config: SkillConfig,
        llm_client = None,
        knowledge_base = None,
        cache_enabled: bool = True,
        max_retries: int = 3,
        cache_ttl: int = 3600
    ):
        """
        Initialise une nouvelle compétence.
        
        Args:
            config: Configuration de la compétence (SkillConfig)
            llm_client: Client LLM pour les appels IA (optionnel)
            knowledge_base: Base de connaissances pour le RAG (optionnel)
            cache_enabled: Active la mise en cache (défaut: True)
            max_retries: Nombre maximum de tentatives (défaut: 3)
            cache_ttl: Durée de vie du cache en secondes (défaut: 3600)
        """
        if not config or not config.skill_id:
            raise ValueError("Skill configuration is required with a valid skill_id")
        
        self.skill_id = config.skill_id
        self.name = config.name
        self.description = getattr(config, 'description', 'No description provided')
        
        # Schéma dynamique (créé à partir de la configuration)
        self.input_schema = self._create_dynamic_schema(config)
        if self.input_schema:
            logger.info(f"Dynamic schema created for skill {self.skill_id}")
        
        self.config = config
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self.cache_enabled = cache_enabled
        self.max_retries = max_retries
        self.status = SkillStatus.INITIALIZED
        self.metadata: Dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": self.version,
            "cache_enabled": cache_enabled
        }
        self.execution_history: List[Dict] = []
        self._execution_count = 0
        
        # Cache intelligent
        self._cache = IntelligentCache(
            default_ttl=cache_ttl,
            max_entries=1000,
            strategy=CacheStrategy.ADAPTIVE,
            enable_metrics=True
        )
        
        # Logger structuré
        self.logger = StructuredLogger(
            component_name=f"Skill_{self.skill_id}",
            log_level=LogLevel.INFO
        )
        self.logger.set_context(skill_id=self.skill_id)
        
        # Validation du contrat
        self._validate_contract()
        
        logger.info(f"Skill initialized: {self.skill_id} v{self.version}")

    def _validate_contract(self) -> None:
        """
        Valide que la compétence implémente bien le contrat attendu.
        """
        # Vérifier que execute est implémentée
        if not ContractValidator.validate_method_exists(self, 'execute'):
            raise AttributeError(
                f"Skill {self.skill_id} must implement execute method"
            )
        
        # Vérifier que get_system_prompt_rules est implémentée
        if not ContractValidator.validate_method_exists(self, 'get_system_prompt_rules'):
            raise AttributeError(
                f"Skill {self.skill_id} must implement get_system_prompt_rules method"
            )

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute la compétence avec les paramètres donnés.
        """
        pass

    @abstractmethod
    def get_system_prompt_rules(self) -> str:
        """
        Retourne les règles système pour le prompt.
        """
        pass

    async def execute_with_validation(
        self, 
        params: Dict[str, Any],
        validate_output: bool = True
    ) -> Dict[str, Any]:
        """
        Exécute la compétence avec validation complète (paramètres, cache, retry, sortie).
        """
        start_time = datetime.now(timezone.utc)
        self.status = SkillStatus.EXECUTING
        self.logger.set_context(execution_id=f"exec_{int(start_time.timestamp())}")
        
        try:
            # 1. Validation des paramètres d'entrée
            validated_params = self.validate_parameters(params)
            logger.debug(f"Parameters validated for skill {self.skill_id}")
            
            # 2. Vérification du cache
            cache_key = self._generate_cache_key(validated_params)
            if self.cache_enabled:
                cached_result = await self._cache.get(cache_key)
                if cached_result is not None:
                    logger.info(f"Cache hit for skill {self.skill_id}")
                    self.status = SkillStatus.CACHED
                    cached_result["_from_cache"] = True
                    self.logger.log_info(
                        f"Cache hit for skill {self.skill_id}",
                        "cache_hit",
                        cache_key=cache_key[:8]
                    )
                    return cached_result
            
            # 3. Exécution avec retry
            result = None
            last_error = None
            
            for attempt in range(self.max_retries):
                try:
                    context = self._prepare_execution_context(validated_params)
                    result = await self.execute(context)
                    
                    if validate_output:
                        self._validate_output(result)
                    
                    # Mise en cache
                    if self.cache_enabled:
                        await self._cache.set(cache_key, result.copy(), tags=[self.skill_id])
                    
                    self.status = SkillStatus.COMPLETED
                    self._execution_count += 1
                    
                    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                    result["_metadata"] = {
                        "skill_id": self.skill_id,
                        "execution_time": duration,
                        "attempt": attempt + 1,
                        "cached": False,
                        "version": self.version
                    }
                    
                    self.logger.log_info(
                        f"Skill {self.skill_id} executed successfully",
                        "skill_execution",
                        duration=duration,
                        attempt=attempt + 1,
                        execution_count=self._execution_count
                    )
                    
                    logger.info(f"Skill {self.skill_id} executed successfully")
                    return result
                    
                except (ValidationError, LLMError) as e:
                    last_error = str(e)
                    self.logger.log_warning(
                        f"Skill {self.skill_id} failed (attempt {attempt + 1}/{self.max_retries}): {last_error}",
                        "skill_retry",
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    
                    if attempt < self.max_retries - 1:
                        wait_time = 2 ** (attempt + 1)
                        await asyncio.sleep(wait_time)
                    else:
                        raise
                        
                except Exception as e:
                    self.logger.log_error(
                        f"Unexpected error in skill {self.skill_id}",
                        e,
                        "skill_error",
                        attempt=attempt + 1
                    )
                    raise PipelineError(f"Skill execution failed: {str(e)}")
            
            self.status = SkillStatus.FAILED
            raise PipelineError(f"All retries failed for skill {self.skill_id}: {last_error}")
            
        except Exception as e:
            self.status = SkillStatus.FAILED
            self.logger.log_error(
                f"Skill {self.skill_id} execution failed",
                e,
                "skill_failed"
            )
            raise
        
        finally:
            # Réinitialiser le contexte
            self.logger.clear_context()
            if self.status != SkillStatus.FAILED:
                self.status = SkillStatus.COMPLETED

    def validate_parameters(self, params: Dict[str, Any]) -> BaseModel:
        """
        Valide les paramètres d'entrée avec le schéma Pydantic.
        """
        if not self.input_schema:
            logger.warning(f"No input schema defined for skill {self.skill_id}")
            return create_model("EmptyModel")(**{})
        
        try:
            if isinstance(params, BaseModel):
                return params
            validated = self.input_schema(**params)
            logger.debug(f"Parameters validated successfully for {self.skill_id}")
            return validated
        except ValidationError as e:
            self.logger.log_error(
                f"Parameter validation failed for {self.skill_id}",
                e,
                "validation_error",
                params=params
            )
            raise

    def _validate_output(self, output: Dict[str, Any]) -> None:
        """
        Valide la sortie de la compétence.
        
        Les statuts acceptés sont en minuscules pour correspondre à l'Enum TaskStatus:
        - "success": Exécution réussie
        - "failed": Exécution échouée
        """
        if not isinstance(output, dict):
            raise ValidationError("Output must be a dictionary")
        
        if "status" not in output:
            raise ValidationError("Output must contain 'status' field")
        
        # Utiliser StatusManager pour valider le statut
        if not status_manager.validate_status(output["status"], {"success", "failed"}):
            raise ValidationError(f"Invalid status: {output['status']}. Allowed: success, failed")

    def get_system_prompt_rules(self) -> str:
        """
        Retourne les règles système pour le prompt.
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
        """
        self.llm_client = client
        logger.debug(f"LLM client set for skill {self.skill_id}")

    def set_knowledge_base(self, kb) -> None:
        """
        Injecte la base de connaissances.
        """
        self.knowledge_base = kb
        logger.debug(f"Knowledge base set for skill {self.skill_id}")

    def enable_cache(self) -> None:
        """
        Active la mise en cache des résultats.
        """
        self.cache_enabled = True
        logger.info(f"Cache enabled for skill {self.skill_id}")

    def disable_cache(self) -> None:
        """
        Désactive la mise en cache des résultats.
        """
        self.cache_enabled = False
        logger.info(f"Cache disabled for skill {self.skill_id}")

    async def clear_cache(self) -> None:
        """
        Vide le cache de la compétence.
        """
        cache_size = len(self._cache)
        await self._cache.clear()
        logger.info(f"Cache cleared for skill {self.skill_id} ({cache_size} entries)")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques d'exécution de la compétence.
        """
        successful = [h for h in self.execution_history if h.get("success", False)]
        failed = [h for h in self.execution_history if not h.get("success", True)]
        
        cache_metrics = self._cache.get_metrics() if self.cache_enabled else {}
        
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "total_executions": len(self.execution_history),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / len(self.execution_history) if self.execution_history else 0.0,
            "cache_enabled": self.cache_enabled,
            "cache_metrics": cache_metrics,
            "execution_count": self._execution_count,
            "metadata": self.metadata
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit la compétence en dictionnaire pour la sérialisation.
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
        Génère une clé de cache à partir des paramètres.
        
        Args:
            params: Paramètres validés (BaseModel)
            
        Returns:
            str: Clé de cache SHA256
        """
        try:
            # Utilisation de model_dump() pour Pydantic v2, fallback sur dict()
            if hasattr(params, 'model_dump'):
                param_dict = params.model_dump()
            else:
                param_dict = params.dict() if hasattr(params, 'dict') else {}
            
            # Ajouter l'ID de la compétence pour éviter les collisions
            param_dict["_skill_id"] = self.skill_id
            
            param_str = json.dumps(param_dict, sort_keys=True, default=str)
            return hashlib.sha256(param_str.encode()).hexdigest()
        except Exception as e:
            logger.warning(f"Cache key generation failed: {str(e)}")
            # Fallback: utiliser l'ID de la compétence et un timestamp
            return f"{self.skill_id}_{datetime.now(timezone.utc).timestamp()}"

    def _prepare_execution_context(self, params: BaseModel) -> Dict[str, Any]:
        """
        Prépare le contexte d'exécution avec les connaissances RAG.
        
        Args:
            params: Paramètres validés (BaseModel)
            
        Returns:
            Dict[str, Any]: Contexte d'exécution (dictionnaire)
        """
        # Conversion des paramètres en dictionnaire
        if hasattr(params, 'model_dump'):
            context = params.model_dump()
        else:
            context = params.dict() if hasattr(params, 'dict') else {}
        
        # Ajout du contexte RAG si disponible
        if self.knowledge_base:
            try:
                query = f"{self.name} {self.skill_id} {context.get('description', '')}"
                relevant_docs = self.knowledge_base.query_context(query, n_results=3)
                if relevant_docs:
                    context["_rag_context"] = relevant_docs
                    logger.debug(f"RAG context added ({len(relevant_docs)} docs)")
            except Exception as e:
                logger.warning(f"RAG query failed: {str(e)}")
        
        return context

    def _create_dynamic_schema(self, config: SkillConfig) -> Optional[Type[BaseModel]]:
        """
        Crée un schéma Pydantic dynamique à partir de la configuration.
        
        Args:
            config: Configuration de la compétence
            
        Returns:
            Optional[Type[BaseModel]]: Modèle Pydantic dynamique ou None
        """
        fields = {}
        schema = None
        
        # Récupération du schéma depuis différentes sources possibles
        if hasattr(config, 'parameters_schema'):
            schema = config.parameters_schema
        elif hasattr(config, 'input_schema'):
            schema = config.input_schema
        elif hasattr(config, 'schema'):
            schema = config.schema
        
        if not schema or not isinstance(schema, dict):
            logger.debug(f"No valid schema found for skill {self.skill_id}")
            return None
        
        # Construction du dictionnaire de champs pour create_model
        for field_name, field_info in schema.items():
            if isinstance(field_info, dict):
                # Gestion des champs avec des métadonnées
                field_type = field_info.get('type', Any)
                default = field_info.get('default', ...)
                # Conversion des types string vers types Python
                if isinstance(field_type, str):
                    type_mapping = {
                        'str': str,
                        'int': int,
                        'float': float,
                        'bool': bool,
                        'list': List,
                        'dict': Dict,
                        'any': Any,
                        'string': str,
                        'integer': int,
                        'number': float,
                        'boolean': bool,
                        'array': List,
                        'object': Dict
                    }
                    field_type = type_mapping.get(field_type, Any)
                fields[field_name] = (field_type, default)
            else:
                # Gestion simple (type directement)
                if isinstance(field_info, str):
                    type_mapping = {
                        'str': str,
                        'int': int,
                        'float': float,
                        'bool': bool,
                        'list': List,
                        'dict': Dict,
                        'any': Any,
                        'string': str,
                        'integer': int,
                        'number': float,
                        'boolean': bool,
                        'array': List,
                        'object': Dict
                    }
                    field_type = type_mapping.get(field_info, Any)
                else:
                    field_type = field_info
                fields[field_name] = (field_type, ...)
        
        if not fields:
            logger.debug(f"No fields found in schema for skill {self.skill_id}")
            return None
        
        try:
            model_name = f"{self.skill_id}_Input"
            return create_model(model_name, **fields)
        except Exception as e:
            logger.error(f"Failed to create dynamic schema for {self.skill_id}: {str(e)}")
            return None

    def get_cache_metrics(self) -> Dict[str, Any]:
        """
        Retourne les métriques du cache.
        
        Returns:
            Dict[str, Any]: Métriques du cache
        """
        return self._cache.get_metrics() if self.cache_enabled else {}

    def __repr__(self) -> str:
        return f"<BaseSkill(skill_id='{self.skill_id}', name='{self.name}', status='{self.status.value}')>"


class BaseLLMSkill(BaseSkill):
    """
    Classe de base pour les compétences qui utilisent un LLM.
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
        Exécute la compétence avec le LLM.
        """
        if not self.llm_client:
            raise LLMError(f"No LLM client configured for skill {self.skill_id}")
        
        prompt = self._format_prompt(params)
        
        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=self.get_system_prompt_rules(),
                temperature=self.temperature
            )
            
            return {
                "status": "success",  # Statut en minuscules pour correspondre à TaskStatus
                "result": response,
                "prompt": prompt
            }
        except Exception as e:
            raise LLMError(f"LLM execution failed: {str(e)}")
    
    def _format_prompt(self, params: Dict[str, Any]) -> str:
        """
        Formate le prompt à partir des paramètres.
        """
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