# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - API Request Schemas
# ==============================================================================
# Fichier: src/api/schemas/requests.py
# Description: Schémas Pydantic pour les requêtes API.
#              Validation automatique des données entrantes.
#              Support de la pagination, du filtrage, du tri et des relations.
# ==============================================================================

from pydantic import BaseModel, Field, validator, root_validator, field_validator
from typing import Optional, List, Dict, Any, Union, Literal
from datetime import datetime, date
from enum import Enum
import re


# ==============================================================================
# ENUMS
# ==============================================================================

class SortOrder(str, Enum):
    """Ordre de tri."""
    ASC = "asc"
    DESC = "desc"


class SortField(str, Enum):
    """Champs de tri disponibles."""
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"
    STATUS = "status"
    PRIORITY = "priority"
    COMPLETED_AT = "completed_at"
    DURATION = "duration_seconds"


# ==============================================================================
# SCHÉMAS DE BASE
# ==============================================================================

class PaginationParams(BaseModel):
    """Paramètres de pagination."""
    page: int = Field(default=1, ge=1, description="Numéro de page")
    page_size: int = Field(default=20, ge=1, le=100, description="Taille de page")
    
    def get_offset(self) -> int:
        """Retourne l'offset pour la requête SQL."""
        return (self.page - 1) * self.page_size
    
    def get_limit(self) -> int:
        """Retourne la limite pour la requête SQL."""
        return self.page_size


class FilterParams(BaseModel):
    """Paramètres de filtrage."""
    search: Optional[str] = Field(None, description="Recherche textuelle")
    status: Optional[List[str]] = Field(None, description="Filtre par statut")
    from_date: Optional[datetime] = Field(None, description="Date de début")
    to_date: Optional[datetime] = Field(None, description="Date de fin")
    tags: Optional[List[str]] = Field(None, description="Filtre par tags")
    
    @field_validator('search')
    @classmethod
    def validate_search(cls, v: Optional[str]) -> Optional[str]:
        """Valide et nettoie la recherche."""
        if v is not None:
            return v.strip()[:200]
        return v


class SortParams(BaseModel):
    """Paramètres de tri."""
    field: SortField = Field(default=SortField.CREATED_AT, description="Champ de tri")
    order: SortOrder = Field(default=SortOrder.DESC, description="Ordre de tri")


class DateRangeParams(BaseModel):
    """Paramètres de plage de dates."""
    start_date: Optional[datetime] = Field(None, description="Date de début")
    end_date: Optional[datetime] = Field(None, description="Date de fin")
    
    @root_validator
    def validate_date_range(cls, values):
        """Valide que la date de début est avant la date de fin."""
        start = values.get('start_date')
        end = values.get('end_date')
        if start and end and start > end:
            raise ValueError("start_date must be before end_date")
        return values


# ==============================================================================
# SCHÉMAS PROJET
# ==============================================================================

class CreateProjectRequest(BaseModel):
    """Requête de création de projet."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom du projet")
    description: str = Field(default="", max_length=1000, description="Description du projet")
    spec_yaml: str = Field(..., description="Spécification YAML du projet")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Configuration")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags")
    priority: Optional[str] = Field(default="medium", description="Priorité du projet")
    category: Optional[str] = Field(default="other", description="Catégorie du projet")
    chain: Optional[str] = Field(default="ethereum", description="Blockchain cible")
    
    @field_validator('spec_yaml')
    @classmethod
    def validate_spec_yaml(cls, v: str) -> str:
        """Valide que la spécification YAML est valide."""
        if not v or len(v.strip()) < 1:
            raise ValueError("Specification cannot be empty")
        try:
            import yaml
            yaml.safe_load(v)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {str(e)}")
        return v
    
    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Valide la priorité."""
        valid = ["low", "medium", "high", "critical"]
        if v not in valid:
            raise ValueError(f"Invalid priority. Must be one of: {valid}")
        return v
    
    @field_validator('category')
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Valide la catégorie."""
        valid = ["defi", "nft", "gaming", "dao", "infrastructure", "tooling", "bridge", "other"]
        if v not in valid:
            raise ValueError(f"Invalid category. Must be one of: {valid}")
        return v
    
    @field_validator('chain')
    @classmethod
    def validate_chain(cls, v: str) -> str:
        """Valide la blockchain."""
        valid = ["ethereum", "polygon", "arbitrum", "optimism", "base", "solana", "bsc", "avalanche", "fantom"]
        if v not in valid:
            raise ValueError(f"Invalid chain. Must be one of: {valid}")
        return v
    
    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Valide les tags."""
        if v:
            for tag in v:
                if not re.match(r'^[a-zA-Z0-9_\-]+$', tag):
                    raise ValueError(f"Invalid tag: '{tag}'. Use only letters, numbers, underscores and hyphens")
        return v


class UpdateProjectRequest(BaseModel):
    """Requête de mise à jour de projet."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Nom du projet")
    description: Optional[str] = Field(None, max_length=1000, description="Description du projet")
    status: Optional[str] = Field(None, description="Nouveau statut")
    config: Optional[Dict[str, Any]] = Field(None, description="Configuration")
    tags: Optional[List[str]] = Field(None, description="Tags")
    priority: Optional[str] = Field(None, description="Priorité du projet")
    category: Optional[str] = Field(None, description="Catégorie du projet")
    chain: Optional[str] = Field(None, description="Blockchain cible")
    spec_yaml: Optional[str] = Field(None, description="Spécification YAML du projet")
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """Valide le statut."""
        if v is not None:
            valid = ["CREATED", "IN_PROGRESS", "COMPLETED", "FAILED", "PAUSED", "ARCHIVED", "CANCELLED", "ON_HOLD"]
            if v not in valid:
                raise ValueError(f"Invalid status. Must be one of: {valid}")
        return v
    
    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        """Valide la priorité."""
        if v is not None:
            valid = ["low", "medium", "high", "critical"]
            if v not in valid:
                raise ValueError(f"Invalid priority. Must be one of: {valid}")
        return v


class ListProjectsRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste de projets."""
    priority: Optional[str] = Field(None, description="Filtrer par priorité")
    category: Optional[str] = Field(None, description="Filtrer par catégorie")
    chain: Optional[str] = Field(None, description="Filtrer par blockchain")
    is_template: Optional[bool] = Field(None, description="Filtrer les templates")
    is_public: Optional[bool] = Field(None, description="Filtrer les projets publics")


# ==============================================================================
# SCHÉMAS TÂCHE
# ==============================================================================

class CreateTaskRequest(BaseModel):
    """Requête de création de tâche."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom de la tâche")
    description: str = Field(default="", max_length=1000, description="Description de la tâche")
    skill_id: str = Field(..., description="ID de la compétence")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Paramètres")
    depends_on: Optional[List[str]] = Field(default_factory=list, description="Dépendances")
    requires_human_validation: bool = Field(default=True, description="Nécessite validation humaine")
    timeout_seconds: int = Field(default=600, ge=1, le=3600, description="Timeout en secondes")
    max_retries: int = Field(default=3, ge=0, le=10, description="Nombre max de tentatives")
    priority: str = Field(default="normal", description="Priorité")
    task_type: str = Field(default="custom", description="Type de tâche")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Métadonnées")
    
    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Valide la priorité."""
        valid = ["low", "normal", "high", "critical"]
        if v not in valid:
            raise ValueError(f"Invalid priority. Must be one of: {valid}")
        return v
    
    @field_validator('task_type')
    @classmethod
    def validate_task_type(cls, v: str) -> str:
        """Valide le type de tâche."""
        valid = ["contract_generation", "test_generation", "security_audit", "formal_verification", 
                 "deployment", "documentation", "review", "analysis", "optimization", "custom"]
        if v not in valid:
            raise ValueError(f"Invalid task type. Must be one of: {valid}")
        return v
    
    @field_validator('depends_on')
    @classmethod
    def validate_depends_on(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Valide les dépendances."""
        if v:
            # Vérifier qu'il n'y a pas de doublons
            if len(v) != len(set(v)):
                raise ValueError("Dependencies contain duplicates")
        return v


class UpdateTaskRequest(BaseModel):
    """Requête de mise à jour de tâche."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Nom de la tâche")
    description: Optional[str] = Field(None, max_length=1000, description="Description de la tâche")
    state: Optional[str] = Field(None, description="Nouvel état")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Paramètres")
    timeout_seconds: Optional[int] = Field(None, ge=1, le=3600, description="Timeout en secondes")
    priority: Optional[str] = Field(None, description="Priorité")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Métadonnées")
    
    @field_validator('state')
    @classmethod
    def validate_state(cls, v: Optional[str]) -> Optional[str]:
        """Valide l'état."""
        if v is not None:
            valid = ["PENDING", "READY", "RUNNING", "AUTO_TESTING", "WAITING_HUMAN_VALIDATION", 
                     "SUCCESS", "FAILED", "CIRCUIT_BROKEN", "CANCELLED", "BLOCKED", "SKIPPED"]
            if v not in valid:
                raise ValueError(f"Invalid state. Must be one of: {valid}")
        return v


class HumanValidationRequest(BaseModel):
    """Requête de validation humaine."""
    approved: bool = Field(..., description="Approbation ou rejet")
    comments: Optional[str] = Field(None, max_length=2000, description="Commentaires")
    suggested_changes: Optional[str] = Field(None, max_length=5000, description="Changements suggérés")


class ListTasksRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste de tâches."""
    project_id: Optional[str] = Field(None, description="Filtrer par projet")
    skill_id: Optional[str] = Field(None, description="Filtrer par compétence")
    priority: Optional[str] = Field(None, description="Filtrer par priorité")
    task_type: Optional[str] = Field(None, description="Filtrer par type")
    requires_human_validation: Optional[bool] = Field(None, description="Filtrer par validation humaine")
    human_validated: Optional[bool] = Field(None, description="Filtrer par validation humaine effectuée")


class RetryTaskRequest(BaseModel):
    """Requête de réessai de tâche."""
    force: bool = Field(default=False, description="Forcer le réessai même si max_retries atteint")
    reset_retry_count: bool = Field(default=False, description="Réinitialiser le compteur de tentatives")


class BatchTaskRequest(BaseModel):
    """Requête de création en masse de tâches."""
    tasks: List[CreateTaskRequest] = Field(..., min_items=1, max_items=50, description="Liste des tâches")
    project_id: str = Field(..., description="ID du projet")


# ==============================================================================
# SCHÉMAS SPRINT
# ==============================================================================

class CreateSprintRequest(BaseModel):
    """Requête de création de sprint."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom du sprint")
    description: str = Field(default="", max_length=1000, description="Description du sprint")
    tasks: List[CreateTaskRequest] = Field(default_factory=list, description="Tâches du sprint")
    start_date: Optional[datetime] = Field(None, description="Date de début")
    end_date: Optional[datetime] = Field(None, description="Date de fin")
    priority: int = Field(default=5, ge=1, le=10, description="Priorité (1-10)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Métadonnées")
    
    @root_validator
    def validate_dates(cls, values):
        """Valide que les dates sont cohérentes."""
        start = values.get('start_date')
        end = values.get('end_date')
        if start and end and start > end:
            raise ValueError("start_date must be before end_date")
        return values


class UpdateSprintRequest(BaseModel):
    """Requête de mise à jour de sprint."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Nom du sprint")
    description: Optional[str] = Field(None, max_length=1000, description="Description du sprint")
    status: Optional[str] = Field(None, description="Nouveau statut")
    start_date: Optional[datetime] = Field(None, description="Date de début")
    end_date: Optional[datetime] = Field(None, description="Date de fin")
    priority: Optional[int] = Field(None, ge=1, le=10, description="Priorité (1-10)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Métadonnées")
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """Valide le statut."""
        if v is not None:
            valid = ["planned", "active", "completed", "cancelled", "blocked"]
            if v not in valid:
                raise ValueError(f"Invalid status. Must be one of: {valid}")
        return v


class ListSprintsRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste de sprints."""
    project_id: Optional[str] = Field(None, description="Filtrer par projet")


# ==============================================================================
# SCHÉMAS ARTEFACT
# ==============================================================================

class CreateArtifactRequest(BaseModel):
    """Requête de création d'artefact."""
    type: str = Field(..., description="Type d'artefact")
    name: str = Field(..., min_length=1, max_length=100, description="Nom de l'artefact")
    content: str = Field(..., description="Contenu de l'artefact")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Métadonnées")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags")
    task_id: Optional[str] = Field(None, description="ID de la tâche source")
    version: str = Field(default="1.0.0", description="Version de l'artefact")
    
    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Valide le type d'artefact."""
        valid = ["solidity", "test", "doc", "config", "script", "abi", "bytecode", "report", "other"]
        if v not in valid:
            raise ValueError(f"Invalid artifact type. Must be one of: {valid}")
        return v


class UpdateArtifactRequest(BaseModel):
    """Requête de mise à jour d'artefact."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Nom de l'artefact")
    content: Optional[str] = Field(None, description="Contenu de l'artefact")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Métadonnées")
    tags: Optional[List[str]] = Field(None, description="Tags")
    version: Optional[str] = Field(None, description="Version de l'artefact")


class ListArtifactsRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste d'artefacts."""
    type: Optional[str] = Field(None, description="Filtrer par type")
    task_id: Optional[str] = Field(None, description="Filtrer par tâche")
    project_id: Optional[str] = Field(None, description="Filtrer par projet")


# ==============================================================================
# SCHÉMAS WORKFLOW
# ==============================================================================

class ExecuteWorkflowRequest(BaseModel):
    """Requête d'exécution de workflow."""
    project_id: str = Field(..., description="ID du projet")
    sprint_id: Optional[str] = Field(None, description="ID du sprint (optionnel)")
    tasks: Optional[List[str]] = Field(None, description="IDs des tâches à exécuter (optionnel)")
    parallel: bool = Field(default=True, description="Exécution en parallèle")
    max_parallel: int = Field(default=4, ge=1, le=20, description="Nombre max de tâches parallèles")
    timeout: Optional[int] = Field(None, ge=60, description="Timeout global en secondes")
    stop_on_error: bool = Field(default=True, description="Arrêter en cas d'erreur")


class PauseWorkflowRequest(BaseModel):
    """Requête de pause de workflow."""
    workflow_id: str = Field(..., description="ID du workflow")
    reason: Optional[str] = Field(None, description="Raison de la pause")


class ResumeWorkflowRequest(BaseModel):
    """Requête de reprise de workflow."""
    workflow_id: str = Field(..., description="ID du workflow")


# ==============================================================================
# SCHÉMAS SECURITY
# ==============================================================================

class SecurityAuditRequest(BaseModel):
    """Requête d'audit de sécurité."""
    code: str = Field(..., description="Code à auditer")
    contract_name: str = Field(default="unknown", description="Nom du contrat")
    level: str = Field(default="full", description="Niveau d'audit")
    analyze_dependencies: bool = Field(default=True, description="Analyser les dépendances")
    generate_report: bool = Field(default=True, description="Générer un rapport")
    
    @field_validator('level')
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Valide le niveau d'audit."""
        valid = ["level_1", "level_2", "level_3", "level_4", "full"]
        if v not in valid:
            raise ValueError(f"Invalid level. Must be one of: {valid}")
        return v


class ThreatSimulationRequest(BaseModel):
    """Requête de simulation de menace."""
    target_address: str = Field(..., description="Adresse du contrat cible")
    attack_type: str = Field(default="full", description="Type d'attaque")
    amount: Optional[int] = Field(None, description="Montant pour l'attaque")
    token_address: Optional[str] = Field(None, description="Adresse du token pour flash loan")
    pool_address: Optional[str] = Field(None, description="Adresse du pool pour MEV")
    
    @field_validator('attack_type')
    @classmethod
    def validate_attack_type(cls, v: str) -> str:
        """Valide le type d'attaque."""
        valid = ["flash_loan", "oracle_manipulation", "mev", "reentrancy", "full"]
        if v not in valid:
            raise ValueError(f"Invalid attack type. Must be one of: {valid}")
        return v


class FormalVerificationRequest(BaseModel):
    """Requête de vérification formelle."""
    contract_path: str = Field(..., description="Chemin du contrat")
    properties: Optional[List[str]] = Field(None, description="Propriétés à vérifier")
    timeout: Optional[int] = Field(default=300, ge=60, description="Timeout en secondes")
    depth: Optional[int] = Field(default=10, ge=1, le=50, description="Profondeur de vérification")


# ==============================================================================
# SCHÉMAS FEEDBACK
# ==============================================================================

class SubmitFeedbackRequest(BaseModel):
    """Requête de soumission de feedback."""
    task_id: str = Field(..., description="ID de la tâche")
    approved: bool = Field(..., description="Approbation ou rejet")
    comments: str = Field(default="", max_length=2000, description="Commentaires")
    suggested_changes: Optional[str] = Field(None, max_length=5000, description="Changements suggérés")
    rating: Optional[int] = Field(None, ge=1, le=5, description="Note (1-5)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Métadonnées")


class ListFeedbackRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste de feedback."""
    task_id: Optional[str] = Field(None, description="Filtrer par tâche")
    user_id: Optional[str] = Field(None, description="Filtrer par utilisateur")
    approved: Optional[bool] = Field(None, description="Filtrer par approbation")


# ==============================================================================
# SCHÉMAS NOTIFICATION
# ==============================================================================

class CreateNotificationRequest(BaseModel):
    """Requête de création de notification."""
    type: str = Field(..., description="Type de notification")
    title: str = Field(..., min_length=1, max_length=200, description="Titre")
    message: str = Field(..., min_length=1, max_length=5000, description="Message")
    user_id: str = Field(..., description="ID de l'utilisateur cible")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Métadonnées")
    
    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Valide le type de notification."""
        valid = ["info", "success", "warning", "error", "critical"]
        if v not in valid:
            raise ValueError(f"Invalid notification type. Must be one of: {valid}")
        return v


class UpdateNotificationRequest(BaseModel):
    """Requête de mise à jour de notification."""
    read: Optional[bool] = Field(None, description="Marquer comme lue")


class ListNotificationsRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste de notifications."""
    user_id: Optional[str] = Field(None, description="Filtrer par utilisateur")
    type: Optional[str] = Field(None, description="Filtrer par type")
    read: Optional[bool] = Field(None, description="Filtrer par lecture")


# ==============================================================================
# SCHÉMAS WEBHOOK
# ==============================================================================

class CreateWebhookRequest(BaseModel):
    """Requête de création de webhook."""
    url: str = Field(..., description="URL du webhook")
    events: List[str] = Field(..., min_items=1, description="Événements déclencheurs")
    headers: Optional[Dict[str, str]] = Field(default_factory=dict, description="Headers HTTP")
    secret: Optional[str] = Field(None, min_length=16, description="Secret pour la signature")
    enabled: bool = Field(default=True, description="Webhook actif")
    retry_count: int = Field(default=3, ge=0, le=10, description="Nombre de tentatives")
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Valide l'URL."""
        if not re.match(r'^https?://', v):
            raise ValueError("URL must start with http:// or https://")
        return v
    
    @field_validator('events')
    @classmethod
    def validate_events(cls, v: List[str]) -> List[str]:
        """Valide les événements."""
        valid = ["task_started", "task_completed", "task_failed", "sprint_started", 
                 "sprint_completed", "sprint_failed", "deployment_started", "deployment_completed"]
        for event in v:
            if event not in valid:
                raise ValueError(f"Invalid event: {event}")
        return v


class UpdateWebhookRequest(BaseModel):
    """Requête de mise à jour de webhook."""
    url: Optional[str] = Field(None, description="URL du webhook")
    events: Optional[List[str]] = Field(None, description="Événements déclencheurs")
    headers: Optional[Dict[str, str]] = Field(None, description="Headers HTTP")
    secret: Optional[str] = Field(None, min_length=16, description="Secret pour la signature")
    enabled: Optional[bool] = Field(None, description="Webhook actif")
    retry_count: Optional[int] = Field(None, ge=0, le=10, description="Nombre de tentatives")


class ListWebhooksRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste de webhooks."""
    enabled: Optional[bool] = Field(None, description="Filtrer par activation")


# ==============================================================================
# SCHÉMAS MÉTRIQUES
# ==============================================================================

class MetricsRequest(DateRangeParams):
    """Requête de métriques."""
    metric_type: str = Field(default="all", description="Type de métrique")
    aggregation: str = Field(default="sum", description="Agrégation (sum, avg, min, max)")
    group_by: Optional[str] = Field(None, description="Groupement (day, hour, project, task)")
    
    @field_validator('metric_type')
    @classmethod
    def validate_metric_type(cls, v: str) -> str:
        """Valide le type de métrique."""
        valid = ["all", "tasks", "projects", "sprints", "executions", "errors", "duration"]
        if v not in valid:
            raise ValueError(f"Invalid metric type. Must be one of: {valid}")
        return v


# ==============================================================================
# SCHÉMAS ÉVÉNEMENTS
# ==============================================================================

class ListEventsRequest(PaginationParams, FilterParams, SortParams):
    """Requête de liste d'événements."""
    event_type: Optional[str] = Field(None, description="Filtrer par type d'événement")
    source: Optional[str] = Field(None, description="Filtrer par source")
    
    @field_validator('event_type')
    @classmethod
    def validate_event_type(cls, v: Optional[str]) -> Optional[str]:
        """Valide le type d'événement."""
        if v is not None:
            valid = ["task_started", "task_completed", "task_failed", "sprint_started", 
                     "sprint_completed", "sprint_failed", "skill_registered", "skill_executed",
                     "agent_created", "agent_destroyed", "circuit_opened", "circuit_closed",
                     "validation_failed", "deployment_started", "deployment_completed", "deployment_failed"]
            if v not in valid:
                raise ValueError(f"Invalid event type. Must be one of: {valid}")
        return v