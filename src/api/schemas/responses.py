# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - API Response Schemas
# ==============================================================================
# Fichier: src/api/schemas/responses.py
# Description: Schémas Pydantic pour les réponses API.
#              Standardisation des formats de réponse.
#              Support des relations, des métriques et des événements.
# ==============================================================================

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Generic, TypeVar, Union
from datetime import datetime
from enum import Enum


# ==============================================================================
# TYPES GENERIQUES
# ==============================================================================

T = TypeVar('T')


# ==============================================================================
# ENUMS DE RÉPONSE
# ==============================================================================

class ResponseStatus(str, Enum):
    """Statuts de réponse."""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# ==============================================================================
# RÉPONSES DE BASE
# ==============================================================================

class BaseResponse(BaseModel):
    """Réponse de base."""
    success: bool = Field(..., description="Succès de l'opération")
    message: str = Field(..., description="Message")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Horodatage")
    
    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Convertit la réponse en dictionnaire avec timestamp ISO."""
        data = super().model_dump(**kwargs)
        if data.get('timestamp'):
            data['timestamp'] = data['timestamp'].isoformat() if isinstance(data['timestamp'], datetime) else data['timestamp']
        return data


class SuccessResponse(BaseResponse):
    """Réponse de succès."""
    success: bool = True
    message: str = "Operation completed successfully"
    data: Optional[Any] = Field(None, description="Données de la réponse")


class CreatedResponse(SuccessResponse):
    """Réponse de création."""
    message: str = "Resource created successfully"
    id: Optional[str] = Field(None, description="ID de la ressource créée")


class ErrorResponse(BaseResponse):
    """Réponse d'erreur."""
    success: bool = False
    code: str = Field(..., description="Code d'erreur")
    details: Optional[Dict[str, Any]] = Field(None, description="Détails de l'erreur")
    path: Optional[str] = Field(None, description="Chemin de la requête")
    method: Optional[str] = Field(None, description="Méthode HTTP")
    request_id: Optional[str] = Field(None, description="ID de la requête")


class PaginatedResponse(BaseModel, Generic[T]):
    """Réponse paginée."""
    items: List[T] = Field(..., description="Liste des éléments")
    total: int = Field(..., description="Nombre total d'éléments")
    page: int = Field(..., description="Page actuelle")
    page_size: int = Field(..., description="Taille de la page")
    total_pages: int = Field(..., description="Nombre total de pages")
    has_next: bool = Field(..., description="Y a-t-il une page suivante ?")
    has_previous: bool = Field(..., description="Y a-t-il une page précédente ?")


# ==============================================================================
# RÉPONSES PROJET
# ==============================================================================

class ProjectSummaryResponse(BaseModel):
    """Résumé d'un projet."""
    id: str = Field(..., description="ID du projet")
    name: str = Field(..., description="Nom du projet")
    status: str = Field(..., description="Statut du projet")
    priority: str = Field(..., description="Priorité du projet")
    category: str = Field(..., description="Catégorie du projet")
    chain: str = Field(..., description="Blockchain")
    task_count: int = Field(..., description="Nombre de tâches")
    completed_task_count: int = Field(..., description="Tâches terminées")
    failed_task_count: int = Field(..., description="Tâches échouées")
    completion_rate: float = Field(..., description="Taux de complétion")
    security_score: int = Field(..., description="Score de sécurité")
    quality_score: int = Field(..., description="Score de qualité")
    created_at: str = Field(..., description="Date de création")
    tags: List[str] = Field(default_factory=list, description="Tags")
    is_active: bool = Field(..., description="Projet actif")


class ProjectDetailResponse(ProjectSummaryResponse):
    """Détail d'un projet."""
    description: str = Field(..., description="Description")
    version: str = Field(..., description="Version")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")
    sprint_count: int = Field(..., description="Nombre de sprints")
    updated_at: str = Field(..., description="Date de mise à jour")
    started_at: Optional[str] = Field(None, description="Date de début")
    completed_at: Optional[str] = Field(None, description="Date de fin")
    duration_days: Optional[float] = Field(None, description="Durée en jours")
    is_template: bool = Field(..., description="Projet template")
    is_public: bool = Field(..., description="Projet public")


# ==============================================================================
# RÉPONSES TÂCHE
# ==============================================================================

class TaskSummaryResponse(BaseModel):
    """Résumé d'une tâche."""
    id: str = Field(..., description="ID de la tâche")
    name: str = Field(..., description="Nom de la tâche")
    state: str = Field(..., description="État de la tâche")
    priority: str = Field(..., description="Priorité")
    task_type: str = Field(..., description="Type de tâche")
    skill_id: str = Field(..., description="ID de la compétence")
    retry_count: int = Field(..., description="Nombre de tentatives")
    duration_seconds: float = Field(..., description="Durée d'exécution")
    created_at: str = Field(..., description="Date de création")
    is_terminal: bool = Field(..., description="État terminal")
    is_success: bool = Field(..., description="Tâche réussie")


class TaskDetailResponse(TaskSummaryResponse):
    """Détail d'une tâche."""
    description: str = Field(..., description="Description")
    project_id: str = Field(..., description="ID du projet")
    dependencies: List[str] = Field(default_factory=list, description="Dépendances")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Paramètres")
    result: Optional[Dict[str, Any]] = Field(None, description="Résultat")
    error_message: Optional[str] = Field(None, description="Message d'erreur")
    requires_human_validation: bool = Field(..., description="Nécessite validation humaine")
    human_validated: bool = Field(..., description="Validé par un humain")
    human_validation_comments: Optional[str] = Field(None, description="Commentaires de validation")
    timeout_seconds: int = Field(..., description="Timeout en secondes")
    max_retries: int = Field(..., description="Nombre max de tentatives")
    is_timeout: bool = Field(..., description="Timeout dépassé")
    elapsed_time: float = Field(..., description="Temps écoulé")
    remaining_time: float = Field(..., description="Temps restant")
    memory_usage_mb: Optional[float] = Field(None, description="Mémoire utilisée")
    cpu_usage_percent: Optional[float] = Field(None, description="CPU utilisé")
    started_at: Optional[str] = Field(None, description="Date de début")
    completed_at: Optional[str] = Field(None, description="Date de fin")
    updated_at: str = Field(..., description="Date de mise à jour")
    logs_preview: Optional[str] = Field(None, description="Aperçu des logs")


# ==============================================================================
# RÉPONSES SPRINT
# ==============================================================================

class SprintSummaryResponse(BaseModel):
    """Résumé d'un sprint."""
    id: str = Field(..., description="ID du sprint")
    name: str = Field(..., description="Nom du sprint")
    status: str = Field(..., description="Statut du sprint")
    project_id: str = Field(..., description="ID du projet")
    task_count: int = Field(..., description="Nombre de tâches")
    completed_task_count: int = Field(..., description="Tâches terminées")
    failed_task_count: int = Field(..., description="Tâches échouées")
    completion_rate: float = Field(..., description="Taux de complétion")
    priority: int = Field(..., description="Priorité (1-10)")
    created_at: str = Field(..., description="Date de création")


class SprintDetailResponse(SprintSummaryResponse):
    """Détail d'un sprint."""
    description: str = Field(..., description="Description")
    tasks: List[TaskSummaryResponse] = Field(default_factory=list, description="Tâches")
    start_date: Optional[str] = Field(None, description="Date de début")
    end_date: Optional[str] = Field(None, description="Date de fin")
    duration_days: Optional[float] = Field(None, description="Durée en jours")
    updated_at: str = Field(..., description="Date de mise à jour")


# ==============================================================================
# RÉPONSES ARTEFACT
# ==============================================================================

class ArtifactSummaryResponse(BaseModel):
    """Résumé d'un artefact."""
    id: str = Field(..., description="ID de l'artefact")
    type: str = Field(..., description="Type d'artefact")
    name: str = Field(..., description="Nom de l'artefact")
    version: str = Field(..., description="Version")
    created_at: str = Field(..., description="Date de création")
    task_id: Optional[str] = Field(None, description="ID de la tâche source")
    tags: List[str] = Field(default_factory=list, description="Tags")


class ArtifactDetailResponse(ArtifactSummaryResponse):
    """Détail d'un artefact."""
    content_preview: str = Field(..., description="Aperçu du contenu")
    content_length: int = Field(..., description="Longueur du contenu")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")
    vector_dimensions: Optional[int] = Field(None, description="Dimensions du vecteur")


# ==============================================================================
# RÉPONSES SÉCURITÉ
# ==============================================================================

class VulnerabilityResponse(BaseModel):
    """Vulnérabilité de sécurité."""
    id: str = Field(..., description="ID de la vulnérabilité")
    type: str = Field(..., description="Type de vulnérabilité")
    severity: str = Field(..., description="Niveau de sévérité")
    title: str = Field(..., description="Titre")
    description: str = Field(..., description="Description")
    location: str = Field(..., description="Localisation")
    line_start: Optional[int] = Field(None, description="Ligne de début")
    line_end: Optional[int] = Field(None, description="Ligne de fin")
    code_snippet: Optional[str] = Field(None, description="Extrait de code")
    impact: str = Field(..., description="Impact potentiel")
    remediation: str = Field(..., description="Correction proposée")
    remediation_code: Optional[str] = Field(None, description="Code de correction")
    references: List[str] = Field(default_factory=list, description="Références")


class SecurityAuditResponse(BaseModel):
    """Réponse d'audit de sécurité."""
    report: Dict[str, Any] = Field(..., description="Rapport d'audit")
    vulnerabilities: List[VulnerabilityResponse] = Field(..., description="Vulnérabilités")
    secure: bool = Field(..., description="Le code est-il sécurisé ?")
    score: float = Field(..., description="Score de sécurité")
    level: str = Field(..., description="Niveau d'audit")
    passed: bool = Field(..., description="Audit passé")
    total_vulnerabilities: int = Field(..., description="Nombre total de vulnérabilités")
    critical_count: int = Field(..., description="Vulnérabilités critiques")
    high_count: int = Field(..., description="Vulnérabilités hautes")
    medium_count: int = Field(..., description="Vulnérabilités moyennes")
    low_count: int = Field(..., description="Vulnérabilités faibles")


class ThreatSimulationResponse(BaseModel):
    """Réponse de simulation de menace."""
    attack_type: str = Field(..., description="Type d'attaque")
    vulnerable: bool = Field(..., description="Vulnérabilité détectée")
    severity: str = Field(..., description="Niveau de sévérité")
    description: str = Field(..., description="Description de l'attaque")
    impact: str = Field(..., description="Impact potentiel")
    remediation: str = Field(..., description="Correction proposée")
    execution_time: float = Field(..., description="Temps d'exécution")
    details: Dict[str, Any] = Field(default_factory=dict, description="Détails")


class FormalVerificationResponse(BaseModel):
    """Réponse de vérification formelle."""
    contract_name: str = Field(..., description="Nom du contrat")
    passed: bool = Field(..., description="Vérification réussie")
    total_properties: int = Field(..., description="Nombre total de propriétés")
    passed_properties: int = Field(..., description="Propriétés vérifiées")
    failed_properties: int = Field(..., description="Propriétés échouées")
    counterexamples: Dict[str, str] = Field(default_factory=dict, description="Contre-exemples")
    execution_time: float = Field(..., description="Temps d'exécution")
    details: Dict[str, Any] = Field(default_factory=dict, description="Détails")


# ==============================================================================
# RÉPONSES WORKFLOW
# ==============================================================================

class WorkflowStatusResponse(BaseModel):
    """Statut du workflow."""
    workflow_id: str = Field(..., description="ID du workflow")
    status: str = Field(..., description="Statut du workflow")
    running: bool = Field(..., description="En cours d'exécution")
    completed_tasks: int = Field(..., description="Tâches terminées")
    total_tasks: int = Field(..., description="Total des tâches")
    progress: float = Field(..., description="Progression (0-100)")
    current_task: Optional[str] = Field(None, description="Tâche en cours")
    current_task_name: Optional[str] = Field(None, description="Nom de la tâche en cours")
    error: Optional[str] = Field(None, description="Message d'erreur")
    started_at: Optional[str] = Field(None, description="Date de début")
    duration: Optional[float] = Field(None, description="Durée écoulée")


class WorkflowResultResponse(BaseModel):
    """Résultat du workflow."""
    workflow_id: str = Field(..., description="ID du workflow")
    status: str = Field(..., description="Statut final")
    tasks: Dict[str, TaskDetailResponse] = Field(default_factory=dict, description="Résultats des tâches")
    duration_seconds: float = Field(..., description="Durée totale")
    total_tasks: int = Field(..., description="Nombre total de tâches")
    completed_tasks: int = Field(..., description="Tâches terminées")
    failed_tasks: int = Field(..., description="Tâches échouées")
    error: Optional[str] = Field(None, description="Message d'erreur")
    started_at: str = Field(..., description="Date de début")
    completed_at: str = Field(..., description="Date de fin")


# ==============================================================================
# RÉPONSES FEEDBACK
# ==============================================================================

class FeedbackResponse(BaseModel):
    """Réponse de feedback."""
    id: str = Field(..., description="ID du feedback")
    task_id: str = Field(..., description="ID de la tâche")
    user_id: str = Field(..., description="ID de l'utilisateur")
    approved: bool = Field(..., description="Approbation")
    comments: str = Field(..., description="Commentaires")
    suggested_changes: Optional[str] = Field(None, description="Changements suggérés")
    rating: Optional[int] = Field(None, description="Note (1-5)")
    created_at: str = Field(..., description="Date de création")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")


# ==============================================================================
# RÉPONSES NOTIFICATION
# ==============================================================================

class NotificationResponse(BaseModel):
    """Réponse de notification."""
    id: str = Field(..., description="ID de la notification")
    type: str = Field(..., description="Type de notification")
    title: str = Field(..., description="Titre")
    message: str = Field(..., description="Message")
    user_id: str = Field(..., description="ID de l'utilisateur")
    read: bool = Field(..., description="Notification lue")
    created_at: str = Field(..., description="Date de création")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")


# ==============================================================================
# RÉPONSES WEBHOOK
# ==============================================================================

class WebhookResponse(BaseModel):
    """Réponse de webhook."""
    id: str = Field(..., description="ID du webhook")
    url: str = Field(..., description="URL du webhook")
    events: List[str] = Field(..., description="Événements déclencheurs")
    enabled: bool = Field(..., description="Webhook actif")
    retry_count: int = Field(..., description="Nombre de tentatives")
    created_at: str = Field(..., description="Date de création")
    last_triggered_at: Optional[str] = Field(None, description="Dernière activation")
    last_success_at: Optional[str] = Field(None, description="Dernier succès")
    last_error: Optional[str] = Field(None, description="Dernière erreur")


# ==============================================================================
# RÉPONSES MÉTRIQUES
# ==============================================================================

class MetricPointResponse(BaseModel):
    """Point de métrique."""
    name: str = Field(..., description="Nom de la métrique")
    value: float = Field(..., description="Valeur")
    timestamp: str = Field(..., description="Horodatage")
    tags: Dict[str, str] = Field(default_factory=dict, description="Tags")


class MetricSeriesResponse(BaseModel):
    """Série de métriques."""
    name: str = Field(..., description="Nom de la série")
    points: List[MetricPointResponse] = Field(..., description="Points de la série")
    unit: str = Field(default="", description="Unité")
    description: str = Field(default="", description="Description")


class MetricsSummaryResponse(BaseModel):
    """Résumé des métriques."""
    total_requests: int = Field(..., description="Nombre total de requêtes")
    total_errors: int = Field(..., description="Nombre total d'erreurs")
    average_response_time: float = Field(..., description="Temps de réponse moyen")
    active_projects: int = Field(..., description="Projets actifs")
    active_tasks: int = Field(..., description="Tâches actives")
    total_tasks_completed: int = Field(..., description="Tâches terminées")
    error_rate: float = Field(..., description="Taux d'erreur")
    uptime_percentage: float = Field(..., description="Disponibilité")
    period: str = Field(..., description="Période")


# ==============================================================================
# RÉPONSES ÉVÉNEMENTS
# ==============================================================================

class EventResponse(BaseModel):
    """Réponse d'événement."""
    id: str = Field(..., description="ID de l'événement")
    type: str = Field(..., description="Type d'événement")
    source: str = Field(..., description="Source de l'événement")
    data: Dict[str, Any] = Field(default_factory=dict, description="Données de l'événement")
    created_at: str = Field(..., description="Date de création")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")


# ==============================================================================
# RÉPONSES STATUT
# ==============================================================================

class StatusResponse(BaseModel):
    """Réponse de statut du pipeline."""
    status: str = Field(..., description="Statut global")
    version: str = Field(..., description="Version du pipeline")
    uptime_seconds: float = Field(..., description="Temps de fonctionnement")
    active_sprints: int = Field(..., description="Sprints actifs")
    total_tasks: int = Field(..., description="Total des tâches")
    completed_tasks: int = Field(..., description="Tâches terminées")
    failed_tasks: int = Field(..., description="Tâches échouées")
    components: Dict[str, bool] = Field(default_factory=dict, description="État des composants")
    is_healthy: bool = Field(..., description="État de santé")
    completion_rate: float = Field(..., description="Taux de complétion global")


# ==============================================================================
# RÉPONSES UTILITAIRE
# ==============================================================================

class HealthCheckResponse(BaseModel):
    """Réponse de health check."""
    status: str = Field(..., description="Statut de santé")
    version: str = Field(..., description="Version")
    timestamp: str = Field(..., description="Horodatage")
    database: str = Field(..., description="Statut de la base de données")
    redis: Optional[str] = Field(None, description="Statut de Redis")
    ollama: Optional[str] = Field(None, description="Statut de Ollama")
    chromadb: Optional[str] = Field(None, description="Statut de ChromaDB")
    uptime_seconds: float = Field(..., description="Temps de fonctionnement")


class ErrorDetailResponse(BaseModel):
    """Détail d'erreur pour les réponses."""
    code: str = Field(..., description="Code d'erreur")
    message: str = Field(..., description="Message d'erreur")
    details: Optional[Dict[str, Any]] = Field(None, description="Détails")
    timestamp: str = Field(..., description="Horodatage")
    path: Optional[str] = Field(None, description="Chemin")
    request_id: Optional[str] = Field(None, description="ID de requête")