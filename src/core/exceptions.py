# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Core Exceptions
# ==============================================================================
# Fichier: src/core/exceptions.py
# Description: Hiérarchie complète des exceptions personnalisées du pipeline.
#              Chaque exception stocke le contexte nécessaire au débogage.
# ==============================================================================

from typing import Optional, Any, Dict, List
from datetime import datetime


# ==============================================================================
# EXCEPTION DE BASE
# ==============================================================================

class PipelineError(Exception):
    """
    Classe de base pour toutes les exceptions du pipeline.
    Toutes les exceptions personnalisées doivent en hériter.
    """
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Args:
            message: Message d'erreur explicite
            details: Dictionnaire de détails supplémentaires (optionnel)
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()

    def __str__(self) -> str:
        """Retourne une représentation lisible de l'erreur."""
        base = f"[{self.timestamp}] {self.message}"
        if self.details:
            base += f"\n  Détails: {self.details}"
        return base


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
    def __init__(self, message: str, config_file: Optional[str] = None, missing_env: Optional[str] = None):
        details = {}
        if config_file:
            details["config_file"] = config_file
        if missing_env:
            details["missing_env"] = missing_env
        super().__init__(message, details)


# ==============================================================================
# ERREURS DE COMPÉTENCES (SKILLS)
# ==============================================================================

class SkillError(PipelineError):
    """
    Erreur lors de l'exécution d'une compétence.
    """
    def __init__(self, skill_id: str, message: str, cause: Optional[Exception] = None, **kwargs):
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
        super().__init__(message, details)
        self.skill_id = skill_id
        self.cause = cause


class SkillNotFoundError(SkillError):
    """
    Compétence non trouvée dans le registre.
    """
    def __init__(self, skill_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Skill '{skill_id}' not found in registry"
        super().__init__(skill_id, message)


class SkillValidationError(SkillError):
    """
    Erreur de validation des paramètres d'une compétence.
    """
    def __init__(self, skill_id: str, validation_errors: List[Dict[str, Any]], message: Optional[str] = None):
        if message is None:
            message = f"Validation failed for skill '{skill_id}'"
        super().__init__(skill_id, message, validation_errors=validation_errors)


class SkillExecutionTimeoutError(SkillError):
    """
    Timeout lors de l'exécution d'une compétence.
    """
    def __init__(self, skill_id: str, timeout_seconds: int, message: Optional[str] = None):
        if message is None:
            message = f"Skill '{skill_id}' timed out after {timeout_seconds}s"
        super().__init__(skill_id, message, timeout_seconds=timeout_seconds)


# ==============================================================================
# ERREURS D'AGENTS
# ==============================================================================

class AgentError(PipelineError):
    """
    Erreur liée à un agent.
    """
    def __init__(self, agent_id: str, message: str, cause: Optional[Exception] = None, **kwargs):
        details = {"agent_id": agent_id}
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        details.update(kwargs)
        super().__init__(message, details)
        self.agent_id = agent_id
        self.cause = cause


class AgentNotFoundError(AgentError):
    """
    Agent non trouvé.
    """
    def __init__(self, agent_id: str, message: Optional[str] = None):
        if message is None:
            message = f"Agent '{agent_id}' not found"
        super().__init__(agent_id, message)


class AgentInitializationError(AgentError):
    """
    Erreur lors de l'initialisation d'un agent.
    """
    def __init__(self, agent_id: str, message: str, cause: Optional[Exception] = None):
        super().__init__(agent_id, f"Failed to initialize agent: {message}", cause=cause)


# ==============================================================================
# ERREURS DE TÂCHES
# ==============================================================================

class TaskError(PipelineError):
    """
    Erreur liée à l'exécution d'une tâche.
    """
    def __init__(self, task_id: str, message: str, cause: Optional[Exception] = None, **kwargs):
        details = {"task_id": task_id}
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        details.update(kwargs)
        super().__init__(message, details)
        self.task_id = task_id
        self.cause = cause


class TaskExecutionError(TaskError):
    """
    Erreur lors de l'exécution d'une tâche.
    """
    def __init__(self, task_id: str, message: str, cause: Optional[Exception] = None):
        super().__init__(task_id, message, cause)


class TaskDependencyError(TaskError):
    """
    Erreur de dépendance entre tâches (DAG).
    """
    def __init__(self, task_id: str, missing_dependencies: List[str], message: Optional[str] = None):
        if message is None:
            message = f"Task '{task_id}' missing dependencies: {missing_dependencies}"
        super().__init__(task_id, message, missing_dependencies=missing_dependencies)


class TaskCircularDependencyError(TaskError):
    """
    Cycle détecté dans le DAG des tâches.
    """
    def __init__(self, task_ids: List[str], message: Optional[str] = None):
        if message is None:
            message = f"Circular dependency detected: {' -> '.join(task_ids)}"
        super().__init__(task_ids[0] if task_ids else "unknown", message, cycle=task_ids)


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
        super().__init__(message, full_details)
        self.rule_id = rule_id


class MultipleValidationError(PipelineError):
    """
    Erreurs de validation multiples.
    """
    def __init__(self, errors: List[ValidationError], message: Optional[str] = None):
        if message is None:
            message = f"Validation failed with {len(errors)} errors"
        details = {"errors": [{"rule_id": e.rule_id, "message": e.message} for e in errors]}
        super().__init__(message, details)
        self.errors = errors


# ==============================================================================
# ERREURS DE COMMUNICATION
# ==============================================================================

class CommunicationError(PipelineError):
    """
    Erreur de communication (bus, réseau, Redis, etc.).
    """
    def __init__(self, message: str, channel: Optional[str] = None, cause: Optional[Exception] = None):
        details = {}
        if channel:
            details["channel"] = channel
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        super().__init__(message, details)


class MessageBusError(CommunicationError):
    """
    Erreur spécifique au bus de messages.
    """
    def __init__(self, message: str, topic: Optional[str] = None, operation: Optional[str] = None):
        details = {}
        if topic:
            details["topic"] = topic
        if operation:
            details["operation"] = operation
        super().__init__(message, **details)


# ==============================================================================
# ERREURS DE BASE DE CONNAISSANCES
# ==============================================================================

class KnowledgeBaseError(PipelineError):
    """
    Erreur d'accès à la base de connaissances (ChromaDB).
    """
    def __init__(self, message: str, collection: Optional[str] = None, operation: Optional[str] = None):
        details = {}
        if collection:
            details["collection"] = collection
        if operation:
            details["operation"] = operation
        super().__init__(message, details)


class EmbeddingError(KnowledgeBaseError):
    """
    Erreur de génération d'embedding.
    """
    def __init__(self, message: str, text_preview: Optional[str] = None):
        details = {}
        if text_preview:
            details["text_preview"] = text_preview[:100] + "..." if len(text_preview) > 100 else text_preview
        super().__init__(f"Embedding generation failed: {message}", **details)


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
        super().__init__(message, details)


class GitAuthenticationError(GitSyncError):
    """
    Erreur d'authentification Git/GitHub.
    """
    def __init__(self, message: str = "GitHub authentication failed"):
        super().__init__(message, operation="authentication")


class GistPublishError(GitSyncError):
    """
    Erreur de publication de Gist.
    """
    def __init__(self, filename: str, message: str, status_code: Optional[int] = None):
        details = {"filename": filename}
        if status_code:
            details["status_code"] = status_code
        super().__init__(f"Failed to publish gist '{filename}': {message}", **details)


# ==============================================================================
# ERREURS LLM
# ==============================================================================

class LLMError(PipelineError):
    """
    Erreur d'appel au LLM (Ollama/OpenAI).
    """
    def __init__(self, message: str, provider: Optional[str] = None, model: Optional[str] = None):
        details = {}
        if provider:
            details["provider"] = provider
        if model:
            details["model"] = model
        super().__init__(message, details)


class LLMConnectionError(LLMError):
    """
    Erreur de connexion au serveur LLM.
    """
    def __init__(self, url: str, message: Optional[str] = None):
        if message is None:
            message = f"Failed to connect to LLM server at {url}"
        super().__init__(message, provider="ollama", details={"url": url})


class LLMResponseError(LLMError):
    """
    Erreur de réponse du LLM (format invalide, timeout, etc.).
    """
    def __init__(self, message: str, response_preview: Optional[str] = None):
        details = {}
        if response_preview:
            details["response_preview"] = response_preview[:200] + "..." if len(response_preview) > 200 else response_preview
        super().__init__(message, **details)


# ==============================================================================
# ERREURS DE SÉCURITÉ
# ==============================================================================

class SecurityError(PipelineError):
    """
    Erreur liée à la sécurité (audit, analyse, etc.).
    """
    def __init__(self, message: str, tool: Optional[str] = None, contract: Optional[str] = None):
        details = {}
        if tool:
            details["tool"] = tool
        if contract:
            details["contract"] = contract
        super().__init__(message, details)


class SecurityAuditError(SecurityError):
    """
    Erreur lors de l'audit de sécurité.
    """
    def __init__(self, tool: str, message: str, output: Optional[str] = None):
        details = {"output": output[:500] + "..." if output and len(output) > 500 else output}
        super().__init__(f"{tool} audit failed: {message}", tool=tool, **details)


# ==============================================================================
# ERREURS D'ORCHESTRATION
# ==============================================================================

class OrchestrationError(PipelineError):
    """
    Erreur lors de l'orchestration du workflow.
    """
    def __init__(self, message: str, workflow_id: Optional[str] = None, step: Optional[int] = None):
        details = {}
        if workflow_id:
            details["workflow_id"] = workflow_id
        if step is not None:
            details["step"] = step
        super().__init__(message, details)


class CircuitBreakerError(OrchestrationError):
    """
    Erreur du circuit breaker (trop de tentatives).
    """
    def __init__(self, task_id: str, retry_count: int, max_retries: int, last_error: str):
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


# ==============================================================================
# ERREURS DE STOCKAGE
# ==============================================================================

class StorageError(PipelineError):
    """
    Erreur de stockage (base de données, fichiers, etc.).
    """
    def __init__(self, message: str, table: Optional[str] = None, operation: Optional[str] = None):
        details = {}
        if table:
            details["table"] = table
        if operation:
            details["operation"] = operation
        super().__init__(message, details)


class DatabaseConnectionError(StorageError):
    """
    Erreur de connexion à la base de données.
    """
    def __init__(self, url: str, message: Optional[str] = None):
        if message is None:
            message = f"Failed to connect to database at {url}"
        super().__init__(message, operation="connection")


# ==============================================================================
# FONCTION UTILITAIRE
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
        result["timestamp"] = e.timestamp
        result["details"] = e.details
    if isinstance(e, (SkillError, AgentError, TaskError)):
        if hasattr(e, "cause") and e.cause:
            result["cause"] = str(e.cause)
    return result


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