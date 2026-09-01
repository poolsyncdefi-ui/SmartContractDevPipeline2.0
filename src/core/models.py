# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Core Models (Pydantic)
# ==============================================================================
# Fichier: src/core/models.py
# Description: Modèles de données Pydantic pour l'ensemble du pipeline.
#              Validation automatique, sérialisation JSON.
# ==============================================================================

from pydantic import BaseModel, Field, validator, root_validator
from typing import List, Dict, Optional, Any, Union
from datetime import datetime
from enum import Enum
import re


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

class Severity(str, Enum):
    """Niveau de sévérité des vulnérabilités."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class TaskStatus(str, Enum):
    """Statut d'une tâche."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    CIRCUIT_BROKEN = "circuit_broken"

class SprintStatus(str, Enum):
    """Statut d'un sprint."""
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class ProxyPattern(str, Enum):
    """Pattern de proxy pour les upgrades."""
    UUPS = "UUPS"
    TRANSPARENT = "Transparent"
    DIAMOND = "Diamond"


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
    """
    id: str = Field(..., min_length=1, max_length=100, description="Identifiant unique")
    name: str = Field(..., min_length=1, max_length=100, description="Nom de la compétence")
    description: str = Field(..., description="Description détaillée")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Niveau de confiance (0-1)")
    examples: List[str] = Field(default_factory=list, description="Exemples d'utilisation")
    prerequisites: List[str] = Field(default_factory=list, description="Compétences requises")
    execution_timeout: int = Field(default=300, gt=0, description="Timeout en secondes")
    required_tools: List[str] = Field(default_factory=list, description="Outils nécessaires")
    parameters_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema des paramètres")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema de la sortie")
    is_dynamic: bool = Field(default=False, description="Générée dynamiquement")

    @validator('id')
    def validate_id(cls, v: str) -> str:
        """Vérifie que l'ID ne contient que des caractères valides."""
        if not re.match(r'^[a-zA-Z0-9_\-]+$', v):
            raise ValueError(f"Invalid skill ID: '{v}'. Use only letters, numbers, underscores and hyphens")
        return v

    @validator('description')
    def validate_description(cls, v: str) -> str:
        """Vérifie que la description n'est pas vide."""
        if not v or len(v.strip()) < 10:
            raise ValueError("Description must be at least 10 characters long")
        return v.strip()

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Surcharge pour exclure les champs vides optionnels."""
        data = super().model_dump(**kwargs)
        # Supprimer les champs optionnels vides
        if data.get('parameters_schema') is None:
            del data['parameters_schema']
        if data.get('output_schema') is None:
            del data['output_schema']
        if not data.get('examples'):
            del data['examples']
        if not data.get('prerequisites'):
            del data['prerequisites']
        return data


# ==============================================================================
# MODÈLE BEST PRACTICE (BONNE PRATIQUE)
# ==============================================================================

class BestPractice(BaseModel):
    """
    Bonne pratique de validation.
    Une règle qui peut être appliquée pour vérifier la qualité du code.
    """
    id: str = Field(..., min_length=1, max_length=100)
    domain: str = Field(..., description="Domaine d'application (solidity, react, security, devops, general)")
    rule: str = Field(..., description="Règle de validation")
    rationale: str = Field(..., description="Justification de la règle")
    severity: Severity = Field(..., description="Niveau de sévérité")
    applicable_to: List[str] = Field(default_factory=list, description="IDs des compétences concernées (vide = toutes)")
    references: List[str] = Field(default_factory=list, description="Références externes")
    validation_fn: Optional[str] = Field(None, description="Nom de la fonction de validation dans le code")
    enabled: bool = Field(default=True, description="Active ou désactive la pratique")
    custom_params: Dict[str, Any] = Field(default_factory=dict, description="Paramètres personnalisés")

    @validator('id')
    def validate_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_\-]+$', v):
            raise ValueError(f"Invalid practice ID: '{v}'")
        return v

    @validator('domain')
    def validate_domain(cls, v: str) -> str:
        valid_domains = {"solidity", "react", "security", "devops", "general"}
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
    """
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    agent_id: str = Field(..., description="ID de l'agent cible")
    action: str = Field(..., description="Nom de la compétence à exécuter")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Paramètres de la tâche")
    depends_on: List[str] = Field(default_factory=list, description="IDs des tâches précédentes")
    requires_human_validation: bool = Field(True, description="Nécessite une validation humaine")
    retry_count: int = Field(3, ge=0, le=10, description="Nombre de tentatives")
    timeout_seconds: int = Field(600, gt=0, le=3600, description="Timeout en secondes")
    priority: int = Field(0, ge=0, le=10, description="Priorité (0=bas, 10=élevé)")

    @root_validator
    def validate_dependencies(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Vérifie qu'une tâche ne dépend pas d'elle-même."""
        task_id = values.get('id')
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
    """
    task_id: str = Field(..., description="ID de la tâche")
    sprint_id: Optional[str] = Field(None, description="ID du sprint associé")
    agent_id: Optional[str] = Field(None, description="ID de l'agent exécutant")
    status: TaskStatus = Field(..., description="Statut final")
    output: Optional[Dict[str, Any]] = Field(None, description="Résultat de l'exécution")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")
    validation_results: Optional[List[Dict[str, Any]]] = Field(None, description="Résultats de validation")
    duration_seconds: float = Field(0.0, ge=0.0, description="Durée en secondes")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Horodatage")
    logs: List[str] = Field(default_factory=list, description="Logs d'exécution")
    gist_url: Optional[str] = Field(None, description="URL du Gist si publié")

    @validator('duration_seconds')
    def validate_duration(cls, v: float) -> float:
        """Arrondit la durée à 3 décimales."""
        return round(v, 3)

    def is_success(self) -> bool:
        """Vérifie si la tâche a réussi."""
        return self.status == TaskStatus.SUCCESS

    def is_failed(self) -> bool:
        """Vérifie si la tâche a échoué."""
        return self.status in {TaskStatus.FAILED, TaskStatus.REJECTED, TaskStatus.CIRCUIT_BROKEN}


# ==============================================================================
# MODÈLE SPRINT
# ==============================================================================

class Sprint(BaseModel):
    """
    Sprint de développement.
    Un sprint est un ensemble de tâches à exécuter.
    """
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    project_id: str = Field(..., description="ID du projet")
    tasks: List[Task] = Field(default_factory=list, description="Tâches du sprint")
    status: SprintStatus = Field(default=SprintStatus.PLANNED, description="Statut du sprint")
    start_date: Optional[datetime] = Field(None, description="Date de début")
    end_date: Optional[datetime] = Field(None, description="Date de fin")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées supplémentaires")

    @validator('tasks')
    def validate_tasks(cls, v: List[Task]) -> List[Task]:
        """Vérifie que les IDs des tâches sont uniques."""
        task_ids = [t.id for t in v]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate task IDs found")
        return v

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """Récupère une tâche par son ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """Récupère les tâches par statut."""
        return [t for t in self.tasks if t.status == status]  # type: ignore


# ==============================================================================
# MODÈLE PROJECT CONFIG (CONFIGURATION PROJET)
# ==============================================================================

class QualityGates(BaseModel):
    """Seuils de qualité pour le projet."""
    test_coverage: int = Field(80, ge=0, le=100, description="Couverture de tests (%")
    gas_increase_limit: int = Field(10, ge=0, description="Limite d'augmentation du gaz (%)")
    max_cyclomatic_complexity: int = Field(10, ge=1, description="Complexité cyclomatique max")
    slither_severity: Severity = Field(Severity.HIGH, description="Sévérité Slither max")
    formal_verification: bool = Field(False, description="Activer la vérification formelle")

class DeploymentConfig(BaseModel):
    """Configuration de déploiement."""
    safe_address: Optional[str] = Field(None, description="Adresse Safe multi-sig")
    admin_address: Optional[str] = Field(None, description="Adresse admin")
    rpc_endpoints: Dict[str, str] = Field(default_factory=dict, description="Endpoints RPC par chaîne")

class UpgradesConfig(BaseModel):
    """Configuration des upgrades."""
    proxy_pattern: ProxyPattern = Field(ProxyPattern.UUPS, description="Pattern de proxy")
    storage_slots: List[str] = Field(default_factory=list, description="Slots de stockage réservés")

class MonitoringConfig(BaseModel):
    """Configuration du monitoring."""
    prometheus_endpoint: Optional[str] = Field(None, description="Endpoint Prometheus")
    grafana_dashboard: Optional[str] = Field(None, description="Dashboard Grafana")

class TeamRequirement(BaseModel):
    """Exigence d'équipe."""
    skill: str = Field(..., description="ID de la compétence")
    count: int = Field(1, ge=1, description="Nombre d'agents")
    priority: int = Field(2, ge=1, le=3, description="Priorité (1=critique, 2=normal, 3=bonus)")

class ProjectConfig(BaseModel):
    """
    Configuration complète du projet.
    Chargeable depuis project_config.yaml.
    """
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", description="Description du projet")
    chain: Chain = Field(Chain.ETHEREUM, description="Blockchain cible")
    frontend: bool = Field(False, description="Avec frontend")
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
    
    @validator('version')
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
    OTHER = "other"

class Artifact(BaseModel):
    """
    Artefact produit par le pipeline.
    Peut être du code, de la documentation, des fichiers de configuration, etc.
    """
    id: str = Field(..., min_length=1, max_length=100)
    type: ArtifactType = Field(..., description="Type d'artefact")
    content: str = Field(..., description="Contenu textuel")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")
    vector: Optional[List[float]] = Field(None, description="Embedding vectoriel")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tags: List[str] = Field(default_factory=list, description="Tags pour la recherche")
    source_task_id: Optional[str] = Field(None, description="ID de la tâche source")

    @validator('content')
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
            "id": self.id,
            "type": self.type.value,
            "metadata": self.metadata,
            "content_preview": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "tags": self.tags,
            "created_at": self.created_at.isoformat()
        }


# ==============================================================================
# MODÈLE FEEDBACK (RETOUR HUMAIN)
# ==============================================================================

class Feedback(BaseModel):
    """
    Retour humain pour le RLHF.
    """
    task_id: str = Field(..., description="ID de la tâche concernée")
    user_id: str = Field(..., description="ID de l'utilisateur")
    approved: bool = Field(..., description="Approbation ou rejet")
    comments: str = Field(default="", description="Commentaires textuels")
    suggested_changes: Optional[str] = Field(None, description="Changements suggérés")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator('comments')
    def validate_comments(cls, v: str) -> str:
        """Nettoie les commentaires."""
        return v.strip() if v else ""


# ==============================================================================
# MODÈLE PIPELINE STATUS (STATUT DU PIPELINE)
# ==============================================================================

class PipelineStatus(BaseModel):
    """
    Statut global du pipeline.
    """
    status: str = Field(..., description="Statut général")
    version: str = Field(..., description="Version du pipeline")
    uptime_seconds: float = Field(..., description="Temps de fonctionnement")
    active_sprints: int = Field(0, description="Nombre de sprints actifs")
    total_tasks: int = Field(0, description="Nombre total de tâches")
    completed_tasks: int = Field(0, description="Tâches terminées")
    failed_tasks: int = Field(0, description="Tâches échouées")
    last_update: datetime = Field(default_factory=datetime.utcnow)
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
    """
    contract_name: str = Field(..., description="Nom du contrat")
    contract_address: str = Field(..., description="Adresse déployée")
    chain_id: int = Field(..., description="ID de la chaîne")
    tx_hash: str = Field(..., description="Hash de la transaction")
    block_number: int = Field(..., description="Numéro du bloc")
    deployed_at: datetime = Field(default_factory=datetime.utcnow)
    verified: bool = Field(False, description="Vérifié sur Etherscan")
    abi: Optional[List[Dict]] = Field(None, description="ABI du contrat")
    bytecode: Optional[str] = Field(None, description="Bytecode déployé")

    @validator('contract_address')
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
        id="erc20_generator",
        name="ERC20 Generator",
        description="Generates an ERC20 token contract with minting and burning capabilities",
        confidence=0.95,
        examples=["Generate a standard ERC20 token", "Create a token with cap"],
        required_tools=["solidity", "forge"],
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
    print(f"   ID: {skill.id}")
    print(f"   Confidence: {skill.confidence}")
    
    # Création d'une tâche
    task = Task(
        id="task_001",
        name="Generate ERC20",
        agent_id="developer_agent",
        action="erc20_generator",
        parameters={"name": "MyToken", "symbol": "MTK", "initial_supply": 1000000},
        depends_on=[]
    )
    print(f"✅ Tâche créée: {task.name}")
    print(f"   Agent: {task.agent_id}")
    print(f"   Action: {task.action}")
    
    # Création d'un sprint
    sprint = Sprint(
        id="sprint_001",
        name="Sprint 1",
        project_id="proj_001",
        tasks=[task]
    )
    print(f"✅ Sprint créé: {sprint.name}")
    print(f"   Tâches: {len(sprint.tasks)}")
    
    print("\n✅ Tous les modèles fonctionnent correctement.")