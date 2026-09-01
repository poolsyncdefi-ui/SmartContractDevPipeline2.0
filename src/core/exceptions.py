# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Core Exceptions
# ==============================================================================
# Fichier: src/core/exceptions.py
# Description: Hiérarchie complète des exceptions personnalisées du pipeline.
#              Chaque exception stocke le contexte nécessaire au débogage.
#              Toutes les exceptions héritent de PipelineError.
# ==============================================================================

from typing import Optional, Any, Dict, List, Union
from datetime import datetime
from enum import Enum


# ==============================================================================
# EXCEPTION DE BASE
# ==============================================================================

class PipelineError(Exception):
    """
    Classe de base pour toutes les exceptions du pipeline.
    Toutes les exceptions personnalisées doivent en hériter.
    
    Attributes:
        message (str): Message d'erreur explicite
        details (Dict[str, Any]): Détails supplémentaires pour le débogage
        timestamp (str): Horodatage de l'erreur
        code (Optional[str]): Code d'erreur pour l'API
    """
    
    def __init__(
        self, 
        message: str, 
        details: Optional[Dict[str, Any]] = None,
        code: Optional[str] = None
    ):
        """
        Args:
            message: Message d'erreur explicite
            details: Dictionnaire de détails supplémentaires (optionnel)
            code: Code d'erreur pour l'API (optionnel)
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()
        self.code = code or self.__class__.__name__.upper()

    def __str__(self) -> str:
        """Retourne une représentation lisible de l'erreur."""
        base = f"[{self.timestamp}] {self.code}: {self.message}"
        if self.details:
            base += f"\n  Détails: {self.details}"
        return base
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit l'exception en dictionnaire pour l'API.
        
        Returns:
            Dict: Représentation de l'erreur
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "type": self.__class__.__name__
        }


# ==============================================================================
# ERREURS DE CONFIGURATION
# ==============================================================================

class ConfigurationError(PipelineError):
    """
    Erreur de configuration.
    Levée lorsque :
    - Un fichier de configuration est manquant
    - Une variable d'environnement obligatoire est absente
    - Un fichier YAML est mal formé ou invalide
    """
    def __init__(
        self, 
        message: str, 
        config_file: Optional[str] = None, 
        missing_env: Optional[str] = None,
        field: Optional[str] = None
    ):
        details = {}
        if config_file:
            details["config_file"] = config_file
        if missing_env:
            details["missing_env"] = missing_env
        if field:
            details["field"] = field
        super().__init__(message, details, code="CONFIG_ERROR")


class EnvironmentVariableError(ConfigurationError):
    """
    Variable d'environnement manquante ou invalide.
    """
    def __init__(self, var_name: str, message: Optional[str] = None):
        if message is None:
            message = f"Environment variable '{var_name}' is missing or invalid"
        super().__init__(message, missing_env=var_name, code="ENV_ERROR")


class YAMLParseError(ConfigurationError):
    """
    Erreur de parsing d'un fichier YAML.
    """
    def __init__(self, file_path: str, line: Optional[int] = None, column: Optional[int] = None):
        details = {"file": file_path}
        if line:
            details["line"] = line
        if column:
            details["column"] = column
        message = f"Failed to parse YAML file: {file_path}"
        super().__init__(message, details, code="YAML_PARSE_ERROR")


# ==============================================================================
# ERREURS DE COMPÉTENCES (SKILLS)
# ==============================================================================

class SkillError(PipelineError):
    """
    Erreur lors de l'exécution d'une compétence.
    """
    def __init__(
        self, 
        skill_id: str, 
        message: str, 
        cause: Optional[Exception] = None, 
        **kwargs
    ):
        """
        Args:
            skill_id: Identifiant de la compétence
            message: Message d'erreur
            cause: Exception originale (optionnel)
            **kwargs: Détails supplémentaires
        """
        details = {"skill_id": skill_id}
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        details.update(kwargs)
        super().__init__(message, details, code="SKILL_ERROR")
        self.skill_id = skill_id
        self.cause = cause


class SkillNotFoundError(SkillError):
    """
    Compétence non trouvée dans le registre.
    """
    def __init__(self, skill_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Skill '{skill_id}' not found in registry"
        super().__init__(skill_id, message, code="SKILL_NOT_FOUND")


class SkillValidationError(SkillError):
    """
    Erreur de validation des paramètres d'une compétence.
    """
    def __init__(
        self, 
        skill_id: str, 
        validation_errors: List[Dict[str, Any]], 
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Validation failed for skill '{skill_id}'"
        super().__init__(
            skill_id, 
            message, 
            validation_errors=validation_errors,
            code="SKILL_VALIDATION_ERROR"
        )


class SkillExecutionTimeoutError(SkillError):
    """
    Timeout lors de l'exécution d'une compétence.
    """
    def __init__(
        self, 
        skill_id: str, 
        timeout_seconds: int, 
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Skill '{skill_id}' timed out after {timeout_seconds}s"
        super().__init__(
            skill_id, 
            message, 
            timeout_seconds=timeout_seconds,
            code="SKILL_TIMEOUT"
        )


class SkillExecutionError(SkillError):
    """
    Erreur générale lors de l'exécution d'une compétence.
    """
    def __init__(
        self, 
        skill_id: str, 
        message: str, 
        cause: Optional[Exception] = None
    ):
        super().__init__(skill_id, message, cause=cause, code="SKILL_EXECUTION_ERROR")


class SkillDependencyError(SkillError):
    """
    Erreur de dépendance entre compétences.
    """
    def __init__(
        self, 
        skill_id: str, 
        missing_dependencies: List[str], 
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Skill '{skill_id}' missing dependencies: {missing_dependencies}"
        super().__init__(
            skill_id, 
            message, 
            missing_dependencies=missing_dependencies,
            code="SKILL_DEPENDENCY_ERROR"
        )


# ==============================================================================
# ERREURS D'AGENTS
# ==============================================================================

class AgentError(PipelineError):
    """
    Erreur liée à un agent.
    """
    def __init__(
        self, 
        agent_id: str, 
        message: str, 
        cause: Optional[Exception] = None, 
        **kwargs
    ):
        details = {"agent_id": agent_id}
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        details.update(kwargs)
        super().__init__(message, details, code="AGENT_ERROR")
        self.agent_id = agent_id
        self.cause = cause


class AgentNotFoundError(AgentError):
    """
    Agent non trouvé.
    """
    def __init__(self, agent_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Agent '{agent_id}' not found"
        super().__init__(agent_id, message, code="AGENT_NOT_FOUND")


class AgentInitializationError(AgentError):
    """
    Erreur lors de l'initialisation d'un agent.
    """
    def __init__(self, agent_id: str, message: str, cause: Optional[Exception] = None):
        super().__init__(agent_id, f"Failed to initialize agent: {message}", cause=cause, code="AGENT_INIT_ERROR")


class AgentAlreadyRunningError(AgentError):
    """
    L'agent est déjà en cours d'exécution.
    """
    def __init__(self, agent_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Agent '{agent_id}' is already running"
        super().__init__(agent_id, message, code="AGENT_ALREADY_RUNNING")


class AgentNotReadyError(AgentError):
    """
    L'agent n'est pas prêt pour l'exécution.
    """
    def __init__(self, agent_id: str, missing_skills: List[str], message: Optional[str] = None):
        if message is None:
            message = f"Agent '{agent_id}' is not ready: missing skills {missing_skills}"
        super().__init__(agent_id, message, missing_skills=missing_skills, code="AGENT_NOT_READY")


# ==============================================================================
# ERREURS DE TÂCHES
# ==============================================================================

class TaskError(PipelineError):
    """
    Erreur liée à l'exécution d'une tâche.
    """
    def __init__(
        self, 
        task_id: str, 
        message: str, 
        cause: Optional[Exception] = None, 
        **kwargs
    ):
        details = {"task_id": task_id}
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        details.update(kwargs)
        super().__init__(message, details, code="TASK_ERROR")
        self.task_id = task_id
        self.cause = cause


class TaskExecutionError(TaskError):
    """
    Erreur lors de l'exécution d'une tâche.
    """
    def __init__(self, task_id: str, message: str, cause: Optional[Exception] = None):
        super().__init__(task_id, message, cause=cause, code="TASK_EXECUTION_ERROR")


class TaskDependencyError(TaskError):
    """
    Erreur de dépendance entre tâches (DAG).
    """
    def __init__(
        self, 
        task_id: str, 
        missing_dependencies: List[str], 
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Task '{task_id}' missing dependencies: {missing_dependencies}"
        super().__init__(
            task_id, 
            message, 
            missing_dependencies=missing_dependencies,
            code="TASK_DEPENDENCY_ERROR"
        )


class TaskCircularDependencyError(TaskError):
    """
    Cycle détecté dans le DAG des tâches.
    """
    def __init__(self, task_ids: List[str], message: Optional[str] = None):
        if message is None:
            message = f"Circular dependency detected: {' -> '.join(task_ids)}"
        super().__init__(
            task_ids[0] if task_ids else "unknown", 
            message, 
            cycle=task_ids,
            code="TASK_CIRCULAR_DEPENDENCY"
        )


class TaskTimeoutError(TaskError):
    """
    Timeout lors de l'exécution d'une tâche.
    """
    def __init__(self, task_id: str, timeout_seconds: int, message: Optional[str] = None):
        if message is None:
            message = f"Task '{task_id}' timed out after {timeout_seconds}s"
        super().__init__(task_id, message, timeout_seconds=timeout_seconds, code="TASK_TIMEOUT")


class TaskCancelledError(TaskError):
    """
    Tâche annulée.
    """
    def __init__(self, task_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Task '{task_id}' was cancelled"
        super().__init__(task_id, message, code="TASK_CANCELLED")


# ==============================================================================
# ERREURS DE VALIDATION
# ==============================================================================

class ValidationError(PipelineError):
    """
    Erreur de validation (bonne pratique non respectée).
    """
    def __init__(self, rule_id: str, message: str, details: Optional[Dict[str, Any]] = None):
        full_details = {"rule_id": rule_id}
        if details:
            full_details.update(details)
        super().__init__(message, full_details, code="VALIDATION_ERROR")
        self.rule_id = rule_id


class MultipleValidationError(PipelineError):
    """
    Erreurs de validation multiples.
    """
    def __init__(self, errors: List[ValidationError], message: Optional[str] = None):
        if message is None:
            message = f"Validation failed with {len(errors)} errors"
        details = {"errors": [{"rule_id": e.rule_id, "message": e.message} for e in errors]}
        super().__init__(message, details, code="MULTIPLE_VALIDATION_ERROR")
        self.errors = errors


class BestPracticeViolationError(ValidationError):
    """
    Violation d'une bonne pratique.
    """
    def __init__(
        self, 
        rule_id: str, 
        message: str, 
        severity: str = "medium",
        suggestion: Optional[str] = None
    ):
        details = {"severity": severity}
        if suggestion:
            details["suggestion"] = suggestion
        super().__init__(rule_id, message, details)
        self.severity = severity
        self.suggestion = suggestion


# ==============================================================================
# ERREURS DE COMMUNICATION
# ==============================================================================

class CommunicationError(PipelineError):
    """
    Erreur de communication (bus, réseau, Redis, etc.).
    """
    def __init__(
        self, 
        message: str, 
        channel: Optional[str] = None, 
        cause: Optional[Exception] = None
    ):
        details = {}
        if channel:
            details["channel"] = channel
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        super().__init__(message, details, code="COMMUNICATION_ERROR")


class MessageBusError(CommunicationError):
    """
    Erreur spécifique au bus de messages.
    """
    def __init__(
        self, 
        message: str, 
        topic: Optional[str] = None, 
        operation: Optional[str] = None
    ):
        details = {}
        if topic:
            details["topic"] = topic
        if operation:
            details["operation"] = operation
        super().__init__(message, **details)
        self.code = "MESSAGE_BUS_ERROR"


class MessageSerializationError(CommunicationError):
    """
    Erreur de sérialisation/désérialisation des messages.
    """
    def __init__(self, message: str, message_type: Optional[str] = None):
        details = {}
        if message_type:
            details["message_type"] = message_type
        super().__init__(f"Message serialization error: {message}", **details)
        self.code = "MESSAGE_SERIALIZATION_ERROR"


class RedisConnectionError(CommunicationError):
    """
    Erreur de connexion à Redis.
    """
    def __init__(self, url: str, message: Optional[str] = None):
        if message is None:
            message = f"Failed to connect to Redis at {url}"
        super().__init__(message, channel="redis", details={"url": url})
        self.code = "REDIS_CONNECTION_ERROR"


# ==============================================================================
# ERREURS DE BASE DE CONNAISSANCES
# ==============================================================================

class KnowledgeBaseError(PipelineError):
    """
    Erreur d'accès à la base de connaissances (ChromaDB).
    """
    def __init__(
        self, 
        message: str, 
        collection: Optional[str] = None, 
        operation: Optional[str] = None
    ):
        details = {}
        if collection:
            details["collection"] = collection
        if operation:
            details["operation"] = operation
        super().__init__(message, details, code="KNOWLEDGE_BASE_ERROR")


class EmbeddingError(KnowledgeBaseError):
    """
    Erreur de génération d'embedding.
    """
    def __init__(self, message: str, text_preview: Optional[str] = None):
        details = {}
        if text_preview:
            details["text_preview"] = text_preview[:100] + "..." if len(text_preview) > 100 else text_preview
        super().__init__(f"Embedding generation failed: {message}", **details)
        self.code = "EMBEDDING_ERROR"


class ChromaDBConnectionError(KnowledgeBaseError):
    """
    Erreur de connexion à ChromaDB.
    """
    def __init__(self, host: str, port: int, message: Optional[str] = None):
        if message is None:
            message = f"Failed to connect to ChromaDB at {host}:{port}"
        super().__init__(message, collection="chromadb", details={"host": host, "port": port})
        self.code = "CHROMADB_CONNECTION_ERROR"


# ==============================================================================
# ERREURS GIT / GITHUB
# ==============================================================================

class GitSyncError(PipelineError):
    """
    Erreur lors des opérations Git/GitHub.
    """
    def __init__(self, message: str, repo: Optional[str] = None, operation: Optional[str] = None):
        details = {}
        if repo:
            details["repo"] = repo
        if operation:
            details["operation"] = operation
        super().__init__(message, details, code="GIT_SYNC_ERROR")


class GitAuthenticationError(GitSyncError):
    """
    Erreur d'authentification Git/GitHub.
    """
    def __init__(self, message: str = "GitHub authentication failed"):
        super().__init__(message, operation="authentication", code="GIT_AUTH_ERROR")


class GistPublishError(GitSyncError):
    """
    Erreur de publication de Gist.
    """
    def __init__(self, filename: str, message: str, status_code: Optional[int] = None):
        details = {"filename": filename}
        if status_code:
            details["status_code"] = status_code
        super().__init__(f"Failed to publish gist '{filename}': {message}", **details)
        self.code = "GIST_PUBLISH_ERROR"


class GitPushError(GitSyncError):
    """
    Erreur de push Git.
    """
    def __init__(self, branch: str, message: str, cause: Optional[Exception] = None):
        details = {"branch": branch}
        if cause:
            details["cause"] = str(cause)
        super().__init__(f"Failed to push to branch '{branch}': {message}", **details)
        self.code = "GIT_PUSH_ERROR"


# ==============================================================================
# ERREURS LLM
# ==============================================================================

class LLMError(PipelineError):
    """
    Erreur d'appel au LLM (Ollama/OpenAI).
    """
    def __init__(
        self, 
        message: str, 
        provider: Optional[str] = None, 
        model: Optional[str] = None
    ):
        details = {}
        if provider:
            details["provider"] = provider
        if model:
            details["model"] = model
        super().__init__(message, details, code="LLM_ERROR")


class LLMConnectionError(LLMError):
    """
    Erreur de connexion au serveur LLM.
    """
    def __init__(self, url: str, message: Optional[str] = None):
        if message is None:
            message = f"Failed to connect to LLM server at {url}"
        super().__init__(message, provider="ollama", details={"url": url})
        self.code = "LLM_CONNECTION_ERROR"


class LLMResponseError(LLMError):
    """
    Erreur de réponse du LLM (format invalide, timeout, etc.).
    """
    def __init__(self, message: str, response_preview: Optional[str] = None):
        details = {}
        if response_preview:
            details["response_preview"] = response_preview[:200] + "..." if len(response_preview) > 200 else response_preview
        super().__init__(message, **details)
        self.code = "LLM_RESPONSE_ERROR"


class LLMTimeoutError(LLMError):
    """
    Timeout lors de l'appel au LLM.
    """
    def __init__(self, timeout_seconds: int, message: Optional[str] = None):
        if message is None:
            message = f"LLM request timed out after {timeout_seconds}s"
        super().__init__(message, details={"timeout_seconds": timeout_seconds})
        self.code = "LLM_TIMEOUT_ERROR"


class LLMRateLimitError(LLMError):
    """
    Erreur de rate limit du LLM.
    """
    def __init__(self, retry_after: Optional[int] = None, message: Optional[str] = None):
        if message is None:
            message = "LLM rate limit exceeded"
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(message, **details)
        self.code = "LLM_RATE_LIMIT_ERROR"


# ==============================================================================
# ERREURS DE SÉCURITÉ
# ==============================================================================

class SecurityError(PipelineError):
    """
    Erreur liée à la sécurité (audit, analyse, etc.).
    """
    def __init__(
        self, 
        message: str, 
        tool: Optional[str] = None, 
        contract: Optional[str] = None
    ):
        details = {}
        if tool:
            details["tool"] = tool
        if contract:
            details["contract"] = contract
        super().__init__(message, details, code="SECURITY_ERROR")


class SecurityAuditError(SecurityError):
    """
    Erreur lors de l'audit de sécurité.
    """
    def __init__(self, tool: str, message: str, output: Optional[str] = None):
        details = {"output": output[:500] + "..." if output and len(output) > 500 else output}
        super().__init__(f"{tool} audit failed: {message}", tool=tool, **details)
        self.code = "SECURITY_AUDIT_ERROR"


class SecurityVulnerabilityFoundError(SecurityError):
    """
    Vulnérabilité de sécurité trouvée lors de l'audit.
    """
    def __init__(
        self, 
        vulnerabilities: List[Dict[str, Any]], 
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Found {len(vulnerabilities)} security vulnerabilities"
        super().__init__(
            message, 
            details={"vulnerabilities": vulnerabilities},
            tool="security_audit"
        )
        self.code = "SECURITY_VULNERABILITY_FOUND"


class FormalVerificationError(SecurityError):
    """
    Erreur de vérification formelle.
    """
    def __init__(self, property_name: str, message: str, counterexample: Optional[str] = None):
        details = {"property": property_name}
        if counterexample:
            details["counterexample"] = counterexample
        super().__init__(f"Formal verification failed for '{property_name}': {message}", **details)
        self.code = "FORMAL_VERIFICATION_ERROR"


# ==============================================================================
# ERREURS D'ORCHESTRATION
# ==============================================================================

class OrchestrationError(PipelineError):
    """
    Erreur lors de l'orchestration du workflow.
    """
    def __init__(
        self, 
        message: str, 
        workflow_id: Optional[str] = None, 
        step: Optional[int] = None
    ):
        details = {}
        if workflow_id:
            details["workflow_id"] = workflow_id
        if step is not None:
            details["step"] = step
        super().__init__(message, details, code="ORCHESTRATION_ERROR")


class CircuitBreakerError(OrchestrationError):
    """
    Erreur du circuit breaker (trop de tentatives).
    """
    def __init__(
        self, 
        task_id: str, 
        retry_count: int, 
        max_retries: int, 
        last_error: str
    ):
        details = {
            "retry_count": retry_count,
            "max_retries": max_retries,
            "last_error": last_error[:200] + "..." if len(last_error) > 200 else last_error
        }
        super().__init__(
            f"Circuit breaker open for task '{task_id}' after {retry_count} retries",
            workflow_id=task_id,
            **details
        )
        self.code = "CIRCUIT_BREAKER_ERROR"


class WorkflowBlockedError(OrchestrationError):
    """
    Workflow bloqué (aucune tâche prête à être exécutée).
    """
    def __init__(self, workflow_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Workflow '{workflow_id}' is blocked: no tasks ready"
        super().__init__(message, workflow_id=workflow_id)
        self.code = "WORKFLOW_BLOCKED"


class WorkflowTimeoutError(OrchestrationError):
    """
    Timeout du workflow.
    """
    def __init__(self, workflow_id: str, timeout_seconds: int, message: Optional[str] = None):
        if message is None:
            message = f"Workflow '{workflow_id}' timed out after {timeout_seconds}s"
        super().__init__(message, workflow_id=workflow_id, details={"timeout_seconds": timeout_seconds})
        self.code = "WORKFLOW_TIMEOUT"


# ==============================================================================
# ERREURS DE STOCKAGE
# ==============================================================================

class StorageError(PipelineError):
    """
    Erreur de stockage (base de données, fichiers, etc.).
    """
    def __init__(
        self, 
        message: str, 
        table: Optional[str] = None, 
        operation: Optional[str] = None
    ):
        details = {}
        if table:
            details["table"] = table
        if operation:
            details["operation"] = operation
        super().__init__(message, details, code="STORAGE_ERROR")


class DatabaseConnectionError(StorageError):
    """
    Erreur de connexion à la base de données.
    """
    def __init__(self, url: str, message: Optional[str] = None):
        if message is None:
            message = f"Failed to connect to database at {url}"
        super().__init__(message, operation="connection")
        self.code = "DB_CONNECTION_ERROR"


class DatabaseQueryError(StorageError):
    """
    Erreur lors de l'exécution d'une requête SQL.
    """
    def __init__(self, query: str, message: str, cause: Optional[Exception] = None):
        details = {"query": query[:200] + "..." if len(query) > 200 else query}
        if cause:
            details["cause"] = str(cause)
        super().__init__(f"Database query failed: {message}", **details)
        self.code = "DB_QUERY_ERROR"


class RecordNotFoundError(StorageError):
    """
    Enregistrement non trouvé dans la base de données.
    """
    def __init__(self, table: str, record_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Record '{record_id}' not found in table '{table}'"
        super().__init__(message, table=table, details={"record_id": record_id})
        self.code = "RECORD_NOT_FOUND"


# ==============================================================================
# ERREURS D'ARTEFACTS
# ==============================================================================

class ArtifactError(PipelineError):
    """
    Erreur liée aux artefacts.
    """
    def __init__(
        self, 
        message: str, 
        artifact_id: Optional[str] = None, 
        artifact_type: Optional[str] = None
    ):
        details = {}
        if artifact_id:
            details["artifact_id"] = artifact_id
        if artifact_type:
            details["artifact_type"] = artifact_type
        super().__init__(message, details, code="ARTIFACT_ERROR")


class ArtifactNotFoundError(ArtifactError):
    """
    Artefact non trouvé.
    """
    def __init__(self, artifact_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Artifact '{artifact_id}' not found"
        super().__init__(message, artifact_id=artifact_id)
        self.code = "ARTIFACT_NOT_FOUND"


class ArtifactStorageError(ArtifactError):
    """
    Erreur de stockage d'artefact.
    """
    def __init__(self, artifact_id: str, message: str, cause: Optional[Exception] = None):
        details = {}
        if cause:
            details["cause"] = str(cause)
        super().__init__(f"Failed to store artifact '{artifact_id}': {message}", artifact_id=artifact_id, **details)
        self.code = "ARTIFACT_STORAGE_ERROR"


# ==============================================================================
# ERREURS DE DÉPLOIEMENT
# ==============================================================================

class DeploymentError(PipelineError):
    """
    Erreur lors du déploiement.
    """
    def __init__(
        self, 
        message: str, 
        network: Optional[str] = None, 
        contract: Optional[str] = None
    ):
        details = {}
        if network:
            details["network"] = network
        if contract:
            details["contract"] = contract
        super().__init__(message, details, code="DEPLOYMENT_ERROR")


class DeploymentTimeoutError(DeploymentError):
    """
    Timeout lors du déploiement.
    """
    def __init__(self, network: str, timeout_seconds: int, message: Optional[str] = None):
        if message is None:
            message = f"Deployment to '{network}' timed out after {timeout_seconds}s"
        super().__init__(message, network=network, details={"timeout_seconds": timeout_seconds})
        self.code = "DEPLOYMENT_TIMEOUT"


class ContractVerificationError(DeploymentError):
    """
    Erreur de vérification du contrat déployé.
    """
    def __init__(self, contract_address: str, message: str):
        super().__init__(f"Contract verification failed for {contract_address}: {message}", contract=contract_address)
        self.code = "CONTRACT_VERIFICATION_ERROR"


# ==============================================================================
# FONCTIONS UTILITAIRES
# ==============================================================================

def format_exception(e: Exception) -> Dict[str, Any]:
    """
    Formate une exception en dictionnaire pour les logs et l'API.
    
    Args:
        e: L'exception à formater
        
    Returns:
        Dictionnaire contenant le type, le message et les détails
    """
    result = {
        "type": type(e).__name__,
        "message": str(e),
    }
    
    if isinstance(e, PipelineError):
        result["code"] = e.code
        result["timestamp"] = e.timestamp
        result["details"] = e.details
    
    if isinstance(e, (SkillError, AgentError, TaskError)):
        if hasattr(e, "cause") and e.cause:
            result["cause"] = str(e.cause)
    
    return result


def exception_to_response(e: Exception) -> Dict[str, Any]:
    """
    Convertit une exception en réponse HTTP.
    
    Args:
        e: L'exception à convertir
        
    Returns:
        Dictionnaire pour la réponse HTTP
    """
    formatted = format_exception(e)
    
    # Déterminer le statut HTTP
    status_code = 500
    if isinstance(e, (ValidationError, MultipleValidationError, BestPracticeViolationError)):
        status_code = 400
    elif isinstance(e, (ConfigurationError, EnvironmentVariableError)):
        status_code = 400
    elif isinstance(e, (SkillNotFoundError, AgentNotFoundError, ArtifactNotFoundError, RecordNotFoundError)):
        status_code = 404
    elif isinstance(e, (GitAuthenticationError, LLMConnectionError, DatabaseConnectionError, ChromaDBConnectionError)):
        status_code = 401
    elif isinstance(e, (CircuitBreakerError, WorkflowBlockedError)):
        status_code = 429
    elif isinstance(e, (LLMTimeoutError, TaskTimeoutError, SkillExecutionTimeoutError, WorkflowTimeoutError)):
        status_code = 408
    
    formatted["status_code"] = status_code
    return formatted


def is_retryable(e: Exception) -> bool:
    """
    Vérifie si une exception est réessayable.
    
    Args:
        e: L'exception à vérifier
        
    Returns:
        bool: True si réessayable
    """
    retryable_types = (
        LLMConnectionError,
        LLMTimeoutError,
        LLMRateLimitError,
        RedisConnectionError,
        DatabaseConnectionError,
        ChromaDBConnectionError,
        CircuitBreakerError,
        GitAuthenticationError,
        CommunicationError
    )
    
    if isinstance(e, retryable_types):
        return True
    
    if isinstance(e, PipelineError) and e.code in [
        "LLM_CONNECTION_ERROR", "LLM_TIMEOUT_ERROR", "LLM_RATE_LIMIT_ERROR",
        "REDIS_CONNECTION_ERROR", "DB_CONNECTION_ERROR", "CHROMADB_CONNECTION_ERROR",
        "CIRCUIT_BREAKER_ERROR", "GIT_AUTH_ERROR", "COMMUNICATION_ERROR"
    ]:
        return True
    
    return False


def get_retry_delay(e: Exception, attempt: int) -> float:
    """
    Calcule le délai de retry en fonction de l'exception et du nombre de tentatives.
    
    Args:
        e: L'exception
        attempt: Numéro de la tentative (0-indexé)
        
    Returns:
        float: Délai en secondes
    """
    base_delay = 1.0
    
    if isinstance(e, LLMRateLimitError):
        # Si disponible, utiliser le retry_after du rate limit
        if hasattr(e, 'details') and e.details.get('retry_after'):
            return float(e.details['retry_after'])
    
    # Backoff exponentiel
    return base_delay * (2 ** attempt)


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    # Exemple de test rapide
    try:
        raise SkillNotFoundError("test_skill")
    except SkillNotFoundError as e:
        print(f"Exception attrapée: {e}")
        print(f"Formaté: {format_exception(e)}")
    
    try:
        raise CircuitBreakerError("task_123", 3, 3, "Too many failures")
    except CircuitBreakerError as e:
        print(f"Exception attrapée: {e}")
        print(f"Formaté: {format_exception(e)}")
        print(f"Réessayable: {is_retryable(e)}")
    
    try:
        raise LLMTimeoutError(30)
    except LLMTimeoutError as e:
        print(f"Exception attrapée: {e}")
        print(f"Réessayable: {is_retryable(e)}")
        print(f"Délai de retry: {get_retry_delay(e, 2)}s")
    
    try:
        raise MultipleValidationError([
            ValidationError("BP001", "Missing license"),
            ValidationError("BP002", "Missing pragma")
        ])
    except MultipleValidationError as e:
        response = exception_to_response(e)
        print(f"Réponse HTTP: {response}")