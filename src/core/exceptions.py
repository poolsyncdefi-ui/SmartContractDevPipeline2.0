# src/core/exceptions.py
from typing import Optional, Any

class PipelineError(Exception):
    """Classe de base pour toutes les exceptions du pipeline."""
    pass

class ConfigurationError(PipelineError):
    """Erreur de configuration (fichier manquant, variable d'env absente, YAML invalide)."""
    pass

class SkillError(PipelineError):
    """Erreur lors de l'exécution d'une compétence."""
    def __init__(self, skill_id: str, message: str, cause: Optional[Exception] = None):
        self.skill_id = skill_id
        self.cause = cause
        super().__init__(message)

class SkillNotFoundError(SkillError):
    """Compétence non trouvée dans le registre."""
    pass

class AgentError(PipelineError):
    """Erreur liée à un agent."""
    pass

class AgentNotFoundError(AgentError):
    """Agent non trouvé."""
    pass

class TaskExecutionError(PipelineError):
    """Erreur lors de l'exécution d'une tâche."""
    def __init__(self, task_id: str, message: str, cause: Optional[Exception] = None):
        self.task_id = task_id
        self.cause = cause
        super().__init__(message)

class ValidationError(PipelineError):
    """Erreur de validation (bonne pratique non respectée)."""
    def __init__(self, rule_id: str, message: str, details: Optional[dict] = None):
        self.rule_id = rule_id
        self.details = details
        super().__init__(message)

class CommunicationError(PipelineError):
    """Erreur de communication (bus, réseau)."""
    pass

class KnowledgeBaseError(PipelineError):
    """Erreur d'accès à la base de connaissances (ChromaDB)."""
    pass

class GitSyncError(PipelineError):
    """Erreur lors des opérations Git/GitHub."""
    pass

class LLMError(PipelineError):
    """Erreur d'appel au LLM (Ollama/OpenAI)."""
    pass