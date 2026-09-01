# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Core Models (Pydantic)
# ==============================================================================
# Fichier: src/core/models.py
# Description: Modèles de données Pydantic pour l'ensemble du pipeline.
#              Validation automatique, sérialisation JSON.
#              Tous les modèles incluent des validations et des méthodes utilitaires.
# ==============================================================================

from pydantic import BaseModel, Field, validator, root_validator, field_validator
from typing import List, Dict, Optional, Any, Union, Set, Literal
from datetime import datetime, timedelta
from enum import Enum
import re
import uuid


# ==============================================================================
# ENUMS
# ==============================================================================

class Chain(str, Enum):
    """Blockchains supportées."""
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    SOLANA = "solana"
    AVALANCHE = "avalanche"
    BSC = "bsc"
    FANTOM = "fantom"


class Severity(str, Enum):
    """Niveau de sévérité des vulnérabilités."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class TaskStatus(str, Enum):
    """Statut d'une tâche."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    CIRCUIT_BROKEN = "circuit_broken"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    WAITING_VALIDATION = "waiting_validation"


class SprintStatus(str, Enum):
    """Statut d'un sprint."""
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ProxyPattern(str, Enum):
    """Pattern de proxy pour les upgrades."""
    UUPS = "UUPS"
    TRANSPARENT = "Transparent"
    DIAMOND = "Diamond"
    BEACON = "Beacon"


class NotificationLevel(str, Enum):
    """Niveau de notification."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogLevel(str, Enum):
    """Niveau de log."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventType(str, Enum):
    """Type d'événement système."""
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    SPRINT_STARTED = "sprint_started"
    SPRINT_COMPLETED = "sprint_completed"
    SPRINT_FAILED = "sprint_failed"
    SKILL_REGISTERED = "skill_registered"
    SKILL_EXECUTED = "skill_executed"
    AGENT_CREATED = "agent_created"
    AGENT_DESTROYED = "agent_destroyed"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_CLOSED = "circuit_closed"
    VALIDATION_FAILED = "validation_failed"
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETED = "deployment_completed"
    DEPLOYMENT_FAILED = "deployment_failed"


# ==============================================================================
# MODÈLE SKILL (COMPÉTENCE)
# ==============================================================================

class Skill(BaseModel):
    """
    Compétence exécutable par un agent.
    Une compétence est un module autonome contenant :
    - Des règles de prompt
    - Un schéma de validation
    - Des métadonnées d'exécution
    
    Attributes:
        skill_id (str): Identifiant unique de la compétence
        name (str): Nom de la compétence
        description (str): Description détaillée
        version (str): Version sémantique
        confidence (float): Niveau de confiance (0-1)
        examples (List[str]): Exemples d'utilisation
        prerequisites (List[str]): Compétences requises
        execution_timeout (int): Timeout en secondes
        required_tools (List[str]): Outils nécessaires
        parameters_schema (Optional[Dict]): JSON Schema des paramètres
        output_schema (Optional[Dict]): JSON Schema de la sortie
        is_dynamic (bool): Générée dynamiquement
        tags (List[str]): Tags pour la recherche
        metadata (Dict): Métadonnées supplémentaires
    """
    skill_id: str = Field(..., min_length=1, max_length=100, alias="id", description="Identifiant unique")
    name: str = Field(..., min_length=1, max_length=100, description="Nom de la compétence")
    description: str = Field(..., description="Description détaillée")
    version: str = Field(default="1.0.0", description="Version sémantique")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Niveau de confiance (0-1)")
    examples: List[str] = Field(default_factory=list, description="Exemples d'utilisation")
    prerequisites: List[str] = Field(default_factory=list, description="Compétences requises")
    execution_timeout: int = Field(default=300, gt=0, description="Timeout en secondes")
    required_tools: List[str] = Field(default_factory=list, description="Outils nécessaires")
    parameters_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema des paramètres")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema de la sortie")
    is_dynamic: bool = Field(default=False, description="Générée dynamiquement")
    tags: List[str] = Field(default_factory=list, description="Tags pour la recherche")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")
    
    @field_validator('skill_id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Vérifie que l'ID ne contient que des caractères valides."""
        if not re.match(r'^[a-zA-Z0-9_\-]+$', v):
            raise ValueError(f"Invalid skill ID: '{v}'. Use only letters, numbers, underscores and hyphens")
        return v
    
    @field_validator('version')
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Vérifie que la version suit le format semver."""
        if not re.match(r'^\d+\.\d+\.\d+$', v):
            raise ValueError(f"Invalid version format: '{v}'. Use semver (X.Y.Z)")
        return v

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Surcharge pour exclure les champs vides optionnels."""
        data = super().model_dump(**kwargs)
        # Supprimer les champs optionnels vides
        if data.get('parameters_schema') is None:
            data.pop('parameters_schema', None)
        if data.get('output_schema') is None:
            data.pop('output_schema', None)
        if not data.get('examples'):
            data.pop('examples', None)
        if not data.get('prerequisites'):
            data.pop('prerequisites', None)
        return data


# ==============================================================================
# MODÈLE BEST PRACTICE (BONNE PRATIQUE)
# ==============================================================================

class BestPractice(BaseModel):
    """
    Bonne pratique de validation.
    Une règle qui peut être appliquée pour vérifier la qualité du code.
    
    Attributes:
        practice_id (str): Identifiant unique de la pratique
        domain (str): Domaine d'application
        rule (str): Règle de validation
        rationale (str): Justification de la règle
        severity (Severity): Niveau de sévérité
        applicable_to (List[str]): IDs des compétences concernées
        references (List[str]): Références externes
        validation_fn (Optional[str]): Nom de la fonction de validation
        enabled (bool): Active ou désactive la pratique
        custom_params (Dict): Paramètres personnalisés
    """
    practice_id: str = Field(..., min_length=1, max_length=100, alias="id")
    domain: str = Field(..., description="Domaine d'application (solidity, react, security, devops, general)")
    rule: str = Field(..., description="Règle de validation")
    rationale: str = Field(..., description="Justification de la règle")
    severity: Severity = Field(..., description="Niveau de sévérité")
    applicable_to: List[str] = Field(default_factory=list, description="IDs des compétences concernées (vide = toutes)")
    references: List[str] = Field(default_factory=list, description="Références externes")
    validation_fn: Optional[str] = Field(None, description="Nom de la fonction de validation dans le code")
    enabled: bool = Field(default=True, description="Active ou désactive la pratique")
    custom_params: Dict[str, Any] = Field(default_factory=dict, description="Paramètres personnalisés")

    @field_validator('domain')
    @classmethod
    def validate_domain(cls, v: str) -> str:
        valid_domains = {"solidity", "react", "security", "devops", "general", "javascript", "typescript", "python"}
        if v not in valid_domains:
            raise ValueError(f"Invalid domain: '{v}'. Must be one of {valid_domains}")
        return v


# ==============================================================================
# MODÈLE TASK (TÂCHE)
# ==============================================================================

class Task(BaseModel):
    """
    Tâche à exécuter par un agent.
    Une tâche est une unité de travail dans le DAG.
    
    Attributes:
        task_id (str): Identifiant unique de la tâche
        name (str): Nom de la tâche
        agent_id (str): ID de l'agent cible
        action (str): Nom de la compétence à exécuter
        parameters (Dict): Paramètres de la tâche
        depends_on (List[str]): IDs des tâches précédentes
        requires_human_validation (bool): Nécessite une validation humaine
        retry_count (int): Nombre de tentatives
        timeout_seconds (int): Timeout en secondes
        priority (int): Priorité (0-10)
        metadata (Dict): Métadonnées supplémentaires
    """
    task_id: str = Field(..., min_length=1, max_length=100, alias="id")
    name: str = Field(..., min_length=1, max_length=100)
    agent_id: str = Field(..., description="ID de l'agent cible")
    action: str = Field(..., description="Nom de la compétence à exécuter")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Paramètres de la tâche")
    depends_on: List[str] = Field(default_factory=list, description="IDs des tâches précédentes")
    requires_human_validation: bool = Field(default=True, description="Nécessite une validation humaine")
    retry_count: int = Field(default=3, ge=0, le=10, description="Nombre de tentatives")
    timeout_seconds: int = Field(default=600, gt=0, le=3600, description="Timeout en secondes")
    priority: int = Field(default=0, ge=0, le=10, description="Priorité (0=bas, 10=élevé)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")

    @root_validator
    def validate_dependencies(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Vérifie qu'une tâche ne dépend pas d'elle-même."""
        task_id = values.get('task_id')
        depends_on = values.get('depends_on', [])
        if task_id and task_id in depends_on:
            raise ValueError(f"Task '{task_id}' cannot depend on itself")
        return values

    def get_dependency_depth(self) -> int:
        """Retourne la profondeur des dépendances (utile pour le DAG)."""
        return len(self.depends_on)


# ==============================================================================
# MODÈLE TASK RESULT (RÉSULTAT DE TÂCHE)
# ==============================================================================

class TaskResult(BaseModel):
    """
    Résultat de l'exécution d'une tâche.
    Stocke toutes les informations de l'exécution.
    
    Attributes:
        task_id (str): ID de la tâche
        sprint_id (Optional[str]): ID du sprint associé
        agent_id (Optional[str]): ID de l'agent exécutant
        status (TaskStatus): Statut final
        output (Optional[Dict]): Résultat de l'exécution
        error (Optional[str]): Message d'erreur si échec
        validation_results (Optional[List[Dict]]): Résultats de validation
        duration_seconds (float): Durée en secondes
        timestamp (datetime): Horodatage
        logs (List[str]): Logs d'exécution
        gist_url (Optional[str]): URL du Gist si publié
        retry_count (int): Nombre de tentatives
        metadata (Dict): Métadonnées supplémentaires
    """
    task_id: str = Field(..., description="ID de la tâche")
    sprint_id: Optional[str] = Field(None, description="ID du sprint associé")
    agent_id: Optional[str] = Field(None, description="ID de l'agent exécutant")
    status: TaskStatus = Field(..., description="Statut final")
    output: Optional[Dict[str, Any]] = Field(None, description="Résultat de l'exécution")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")
    validation_results: Optional[List[Dict[str, Any]]] = Field(None, description="Résultats de validation")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Durée en secondes")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Horodatage")
    logs: List[str] = Field(default_factory=list, description="Logs d'exécution")
    gist_url: Optional[str] = Field(None, description="URL du Gist si publié")
    retry_count: int = Field(default=0, ge=0, description="Nombre de tentatives")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")

    @field_validator('duration_seconds')
    @classmethod
    def validate_duration(cls, v: float) -> float:
        """Arrondit la durée à 3 décimales."""
        return round(v, 3)

    def is_success(self) -> bool:
        """Vérifie si la tâche a réussi."""
        return self.status == TaskStatus.SUCCESS

    def is_failed(self) -> bool:
        """Vérifie si la tâche a échoué."""
        return self.status in {TaskStatus.FAILED, TaskStatus.REJECTED, TaskStatus.CIRCUIT_BROKEN}

    def is_pending(self) -> bool:
        """Vérifie si la tâche est en attente."""
        return self.status == TaskStatus.PENDING


# ==============================================================================
# MODÈLE SPRINT
# ==============================================================================

class Sprint(BaseModel):
    """
    Sprint de développement.
    Un sprint est un ensemble de tâches à exécuter.
    
    Attributes:
        sprint_id (str): Identifiant unique du sprint
        name (str): Nom du sprint
        project_id (str): ID du projet
        tasks (List[Task]): Tâches du sprint
        status (SprintStatus): Statut du sprint
        start_date (Optional[datetime]): Date de début
        end_date (Optional[datetime]): Date de fin
        created_at (datetime): Date de création
        updated_at (datetime): Date de mise à jour
        metadata (Dict): Métadonnées supplémentaires
    """
    sprint_id: str = Field(..., min_length=1, max_length=100, alias="id")
    name: str = Field(..., min_length=1, max_length=100)
    project_id: str = Field(..., description="ID du projet")
    tasks: List[Task] = Field(default_factory=list, description="Tâches du sprint")
    status: SprintStatus = Field(default=SprintStatus.PLANNED, description="Statut du sprint")
    start_date: Optional[datetime] = Field(None, description="Date de début")
    end_date: Optional[datetime] = Field(None, description="Date de fin")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Date de création")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Date de mise à jour")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")

    @field_validator('tasks')
    @classmethod
    def validate_tasks(cls, v: List[Task]) -> List[Task]:
        """Vérifie que les IDs des tâches sont uniques."""
        task_ids = [t.task_id for t in v]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate task IDs found")
        return v

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """Récupère une tâche par son ID."""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """Récupère les tâches par statut."""
        return [t for t in self.tasks if hasattr(t, 'status') and t.status == status]  # type: ignore

    def get_completion_rate(self) -> float:
        """Retourne le taux de complétion du sprint."""
        if not self.tasks:
            return 0.0
        completed = sum(1 for t in self.tasks if hasattr(t, 'status') and t.status == TaskStatus.SUCCESS)  # type: ignore
        return round((completed / len(self.tasks)) * 100, 2)


# ==============================================================================
# MODÈLE PROJECT CONFIG (CONFIGURATION PROJET)
# ==============================================================================

class QualityGates(BaseModel):
    """Seuils de qualité pour le projet."""
    test_coverage: int = Field(default=80, ge=0, le=100, description="Couverture de tests (%)")
    gas_increase_limit: int = Field(default=10, ge=0, description="Limite d'augmentation du gaz (%)")
    max_cyclomatic_complexity: int = Field(default=10, ge=1, description="Complexité cyclomatique max")
    slither_severity: Severity = Field(default=Severity.HIGH, description="Sévérité Slither max")
    formal_verification: bool = Field(default=False, description="Activer la vérification formelle")
    min_security_score: float = Field(default=80.0, ge=0.0, le=100.0, description="Score de sécurité minimum")


class DeploymentConfig(BaseModel):
    """Configuration de déploiement."""
    safe_address: Optional[str] = Field(None, description="Adresse Safe multi-sig")
    admin_address: Optional[str] = Field(None, description="Adresse admin")
    rpc_endpoints: Dict[str, str] = Field(default_factory=dict, description="Endpoints RPC par chaîne")
    private_key_env: Optional[str] = Field(None, description="Variable d'environnement pour la clé privée")
    gas_limit: int = Field(default=3000000, ge=0, description="Limite de gaz")
    confirmations: int = Field(default=2, ge=0, description="Nombre de confirmations requises")


class UpgradesConfig(BaseModel):
    """Configuration des upgrades."""
    proxy_pattern: ProxyPattern = Field(default=ProxyPattern.UUPS, description="Pattern de proxy")
    storage_slots: List[str] = Field(default_factory=list, description="Slots de stockage réservés")
    upgrade_delay_days: int = Field(default=7, ge=0, description="Délai avant upgrade (jours)")
    timelock_days: int = Field(default=2, ge=0, description="Timelock (jours)")


class MonitoringConfig(BaseModel):
    """Configuration du monitoring."""
    prometheus_endpoint: Optional[str] = Field(None, description="Endpoint Prometheus")
    grafana_dashboard: Optional[str] = Field(None, description="Dashboard Grafana")
    alert_email: Optional[str] = Field(None, description="Email d'alerte")
    slack_webhook: Optional[str] = Field(None, description="Webhook Slack")


class TeamRequirement(BaseModel):
    """Exigence d'équipe."""
    skill: str = Field(..., description="ID de la compétence")
    count: int = Field(default=1, ge=1, description="Nombre d'agents")
    priority: int = Field(default=2, ge=1, le=3, description="Priorité (1=critique, 2=normal, 3=bonus)")


class ProjectConfig(BaseModel):
    """
    Configuration complète du projet.
    Chargeable depuis project_config.yaml.
    
    Attributes:
        name (str): Nom du projet
        description (str): Description du projet
        chain (Chain): Blockchain cible
        frontend (bool): Avec frontend
        version (str): Version du projet
        team_requirements (List[TeamRequirement]): Exigences d'équipe
        quality_gates (QualityGates): Seuils de qualité
        deployment (DeploymentConfig): Configuration de déploiement
        upgrades (UpgradesConfig): Configuration des upgrades
        monitoring (MonitoringConfig): Configuration du monitoring
        metadata (Dict): Métadonnées supplémentaires
    """
    name: str = Field(..., min_length=1, max_length=100, description="Nom du projet")
    description: str = Field(default="", description="Description du projet")
    chain: Chain = Field(default=Chain.ETHEREUM, description="Blockchain cible")
    frontend: bool = Field(default=False, description="Avec frontend")
    version: str = Field(default="1.0.0", description="Version du projet")
    
    # Équipe
    team_requirements: List[TeamRequirement] = Field(default_factory=list)
    
    # Qualité
    quality_gates: QualityGates = Field(default_factory=QualityGates)
    
    # Déploiement
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    
    # Upgrades
    upgrades: UpgradesConfig = Field(default_factory=UpgradesConfig)
    
    # Monitoring
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    
    # Métadonnées
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('version')
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Vérifie que la version suit le format semver."""
        if not re.match(r'^\d+\.\d+\.\d+$', v):
            raise ValueError(f"Invalid version format: '{v}'. Use semver (X.Y.Z)")
        return v


# ==============================================================================
# MODÈLE ARTIFACT (ARTEFACT)
# ==============================================================================

class ArtifactType(str, Enum):
    """Types d'artefacts."""
    SOLIDITY = "solidity"
    TEST = "test"
    DOCUMENTATION = "doc"
    CONFIGURATION = "config"
    SCRIPT = "script"
    ABI = "abi"
    BYTECODE = "bytecode"
    REPORT = "report"
    OTHER = "other"


class Artifact(BaseModel):
    """
    Artefact produit par le pipeline.
    Peut être du code, de la documentation, des fichiers de configuration, etc.
    
    Attributes:
        artifact_id (str): Identifiant unique de l'artefact
        type (ArtifactType): Type d'artefact
        content (str): Contenu textuel
        metadata (Dict): Métadonnées
        vector (Optional[List[float]]): Embedding vectoriel
        created_at (datetime): Date de création
        tags (List[str]): Tags pour la recherche
        source_task_id (Optional[str]): ID de la tâche source
        version (str): Version de l'artefact
    """
    artifact_id: str = Field(..., min_length=1, max_length=100, alias="id")
    type: ArtifactType = Field(..., description="Type d'artefact")
    content: str = Field(..., description="Contenu textuel")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")
    vector: Optional[List[float]] = Field(None, description="Embedding vectoriel")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Date de création")
    tags: List[str] = Field(default_factory=list, description="Tags pour la recherche")
    source_task_id: Optional[str] = Field(None, description="ID de la tâche source")
    version: str = Field(default="1.0.0", description="Version de l'artefact")

    @field_validator('content')
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Vérifie que le contenu n'est pas vide."""
        if not v or len(v.strip()) < 1:
            raise ValueError("Artifact content cannot be empty")
        return v

    def to_text(self) -> str:
        """Retourne le contenu sous forme de texte."""
        return self.content

    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'artefact en dictionnaire."""
        return {
            "id": self.artifact_id,
            "type": self.type.value,
            "metadata": self.metadata,
            "content_preview": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "version": self.version
        }


# ==============================================================================
# MODÈLE FEEDBACK (RETOUR HUMAIN)
# ==============================================================================

class Feedback(BaseModel):
    """
    Retour humain pour le RLHF.
    
    Attributes:
        feedback_id (str): Identifiant unique du feedback
        task_id (str): ID de la tâche concernée
        user_id (str): ID de l'utilisateur
        approved (bool): Approbation ou rejet
        comments (str): Commentaires textuels
        suggested_changes (Optional[str]): Changements suggérés
        created_at (datetime): Date de création
        metadata (Dict): Métadonnées supplémentaires
    """
    feedback_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="id")
    task_id: str = Field(..., description="ID de la tâche concernée")
    user_id: str = Field(..., description="ID de l'utilisateur")
    approved: bool = Field(..., description="Approbation ou rejet")
    comments: str = Field(default="", description="Commentaires textuels")
    suggested_changes: Optional[str] = Field(None, description="Changements suggérés")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Date de création")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")

    @field_validator('comments')
    @classmethod
    def validate_comments(cls, v: str) -> str:
        """Nettoie les commentaires."""
        return v.strip() if v else ""


# ==============================================================================
# MODÈLE NOTIFICATION
# ==============================================================================

class Notification(BaseModel):
    """
    Notification à envoyer aux utilisateurs.
    
    Attributes:
        notification_id (str): Identifiant unique de la notification
        type (NotificationLevel): Niveau de notification
        title (str): Titre de la notification
        message (str): Message de la notification
        user_id (str): ID de l'utilisateur cible
        read (bool): Notification lue
        created_at (datetime): Date de création
        metadata (Dict): Métadonnées supplémentaires
    """
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="id")
    type: NotificationLevel = Field(default=NotificationLevel.INFO, description="Niveau de notification")
    title: str = Field(..., min_length=1, max_length=200, description="Titre de la notification")
    message: str = Field(..., min_length=1, description="Message de la notification")
    user_id: str = Field(..., description="ID de l'utilisateur cible")
    read: bool = Field(default=False, description="Notification lue")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Date de création")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")


# ==============================================================================
# MODÈLE EVENT (ÉVÉNEMENT)
# ==============================================================================

class Event(BaseModel):
    """
    Événement système.
    
    Attributes:
        event_id (str): Identifiant unique de l'événement
        type (EventType): Type d'événement
        source (str): Source de l'événement
        data (Dict): Données de l'événement
        created_at (datetime): Date de création
        metadata (Dict): Métadonnées supplémentaires
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="id")
    type: EventType = Field(..., description="Type d'événement")
    source: str = Field(..., description="Source de l'événement")
    data: Dict[str, Any] = Field(default_factory=dict, description="Données de l'événement")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Date de création")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")


# ==============================================================================
# MODÈLE ERROR RESPONSE (RÉPONSE D'ERREUR API)
# ==============================================================================

class ErrorResponse(BaseModel):
    """
    Réponse d'erreur pour l'API.
    
    Attributes:
        code (str): Code d'erreur
        message (str): Message d'erreur
        details (Optional[Dict]): Détails de l'erreur
        timestamp (datetime): Horodatage
        path (Optional[str]): Chemin de la requête
        method (Optional[str]): Méthode HTTP
        request_id (str): ID de la requête
    """
    code: str = Field(..., description="Code d'erreur")
    message: str = Field(..., description="Message d'erreur")
    details: Optional[Dict[str, Any]] = Field(None, description="Détails de l'erreur")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Horodatage")
    path: Optional[str] = Field(None, description="Chemin de la requête")
    method: Optional[str] = Field(None, description="Méthode HTTP")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID de la requête")


# ==============================================================================
# MODÈLE METRICS (MÉTRIQUES)
# ==============================================================================

class MetricPoint(BaseModel):
    """Point de métrique."""
    name: str = Field(..., description="Nom de la métrique")
    value: float = Field(..., description="Valeur de la métrique")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Horodatage")
    tags: Dict[str, str] = Field(default_factory=dict, description="Tags de la métrique")


class MetricSeries(BaseModel):
    """Série de métriques."""
    name: str = Field(..., description="Nom de la métrique")
    points: List[MetricPoint] = Field(..., description="Points de la métrique")
    unit: str = Field(default="", description="Unité de la métrique")
    description: str = Field(default="", description="Description de la métrique")


# ==============================================================================
# MODÈLE WEBHOOK
# ==============================================================================

class Webhook(BaseModel):
    """
    Configuration d'un webhook.
    
    Attributes:
        webhook_id (str): Identifiant unique du webhook
        url (str): URL du webhook
        events (List[EventType]): Événements déclencheurs
        headers (Dict): Headers HTTP
        secret (Optional[str]): Secret pour la signature
        enabled (bool): Webhook actif
        retry_count (int): Nombre de tentatives
        created_at (datetime): Date de création
    """
    webhook_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="id")
    url: str = Field(..., description="URL du webhook")
    events: List[EventType] = Field(..., description="Événements déclencheurs")
    headers: Dict[str, str] = Field(default_factory=dict, description="Headers HTTP")
    secret: Optional[str] = Field(None, description="Secret pour la signature")
    enabled: bool = Field(default=True, description="Webhook actif")
    retry_count: int = Field(default=3, ge=0, le=10, description="Nombre de tentatives")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Date de création")


# ==============================================================================
# MODÈLE PIPELINE STATUS (STATUT DU PIPELINE)
# ==============================================================================

class PipelineStatus(BaseModel):
    """
    Statut global du pipeline.
    
    Attributes:
        status (str): Statut général
        version (str): Version du pipeline
        uptime_seconds (float): Temps de fonctionnement
        active_sprints (int): Nombre de sprints actifs
        total_tasks (int): Nombre total de tâches
        completed_tasks (int): Tâches terminées
        failed_tasks (int): Tâches échouées
        last_update (datetime): Dernière mise à jour
        components (Dict): État des composants
    """
    status: str = Field(..., description="Statut général (healthy, degraded, unhealthy)")
    version: str = Field(..., description="Version du pipeline")
    uptime_seconds: float = Field(..., description="Temps de fonctionnement en secondes")
    active_sprints: int = Field(default=0, description="Nombre de sprints actifs")
    total_tasks: int = Field(default=0, description="Nombre total de tâches")
    completed_tasks: int = Field(default=0, description="Tâches terminées")
    failed_tasks: int = Field(default=0, description="Tâches échouées")
    last_update: datetime = Field(default_factory=datetime.utcnow, description="Dernière mise à jour")
    components: Dict[str, bool] = Field(default_factory=dict, description="État des composants")

    def is_healthy(self) -> bool:
        """Vérifie si le pipeline est en bonne santé."""
        return self.status == "healthy" and all(self.components.values())

    def get_completion_rate(self) -> float:
        """Retourne le taux de complétion."""
        if self.total_tasks == 0:
            return 0.0
        return round((self.completed_tasks / self.total_tasks) * 100, 2)


# ==============================================================================
# MODÈLE DEPLOYMENT (DÉPLOIEMENT)
# ==============================================================================

class Deployment(BaseModel):
    """
    Informations de déploiement d'un contrat.
    
    Attributes:
        deployment_id (str): Identifiant unique du déploiement
        contract_name (str): Nom du contrat
        contract_address (str): Adresse déployée
        chain_id (int): ID de la chaîne
        tx_hash (str): Hash de la transaction
        block_number (int): Numéro du bloc
        deployed_at (datetime): Date de déploiement
        verified (bool): Vérifié sur Etherscan
        abi (Optional[List[Dict]]): ABI du contrat
        bytecode (Optional[str]): Bytecode déployé
        metadata (Dict): Métadonnées supplémentaires
    """
    deployment_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="id")
    contract_name: str = Field(..., description="Nom du contrat")
    contract_address: str = Field(..., description="Adresse déployée")
    chain_id: int = Field(..., description="ID de la chaîne")
    tx_hash: str = Field(..., description="Hash de la transaction")
    block_number: int = Field(..., description="Numéro du bloc")
    deployed_at: datetime = Field(default_factory=datetime.utcnow, description="Date de déploiement")
    verified: bool = Field(default=False, description="Vérifié sur Etherscan")
    abi: Optional[List[Dict]] = Field(None, description="ABI du contrat")
    bytecode: Optional[str] = Field(None, description="Bytecode déployé")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")

    @field_validator('contract_address')
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Vérifie le format de l'adresse."""
        if not re.match(r'^0x[a-fA-F0-9]{40}$', v):
            raise ValueError(f"Invalid contract address: '{v}'")
        return v


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    # Création d'un skill de test
    skill = Skill(
        skill_id="erc20_generator",
        name="ERC20 Generator",
        description="Generates an ERC20 token contract with minting and burning capabilities",
        confidence=0.95,
        version="2.1.0",
        examples=["Generate a standard ERC20 token", "Create a token with cap"],
        required_tools=["solidity", "forge"],
        tags=["erc20", "token", "solidity"],
        parameters_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "symbol": {"type": "string"},
                "initial_supply": {"type": "integer", "minimum": 0}
            },
            "required": ["name", "symbol"]
        }
    )
    print(f"✅ Skill créé: {skill.name}")
    print(f"   ID: {skill.skill_id}")
    print(f"   Confidence: {skill.confidence}")
    print(f"   Version: {skill.version}")
    
    # Création d'une tâche
    task = Task(
        task_id="task_001",
        name="Generate ERC20",
        agent_id="developer_agent",
        action="erc20_generator",
        parameters={"name": "MyToken", "symbol": "MTK", "initial_supply": 1000000},
        depends_on=[],
        priority=5
    )
    print(f"✅ Tâche créée: {task.name}")
    print(f"   Agent: {task.agent_id}")
    print(f"   Action: {task.action}")
    
    # Création d'un sprint
    sprint = Sprint(
        sprint_id="sprint_001",
        name="Sprint 1",
        project_id="proj_001",
        tasks=[task],
        status=SprintStatus.RUNNING
    )
    print(f"✅ Sprint créé: {sprint.name}")
    print(f"   Tâches: {len(sprint.tasks)}")
    print(f"   Completion rate: {sprint.get_completion_rate()}%")
    
    # Création d'un résultat de tâche
    result = TaskResult(
        task_id="task_001",
        sprint_id="sprint_001",
        agent_id="developer_agent",
        status=TaskStatus.SUCCESS,
        output={"contract": "0x1234..."},
        duration_seconds=2.5,
        retry_count=0
    )
    print(f"✅ Résultat créé: {result.task_id}")
    print(f"   Status: {result.status.value}")
    print(f"   Success: {result.is_success()}")
    
    # Création d'une notification
    notification = Notification(
        type=NotificationLevel.SUCCESS,
        title="Task Completed",
        message="Task T001 has been completed successfully",
        user_id="user_001"
    )
    print(f"✅ Notification créée: {notification.title}")
    
    print("\n✅ Tous les modèles fonctionnent correctement.")