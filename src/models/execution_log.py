# src/models/execution_log.py

"""
Model for execution logs.
F11 – src/models/execution_log.py

Rôle Fonctionnel : Enregistre l'historique et les traces textuelles des actions des agents.
Cette table est essentielle pour l'audit, le débogage et la transparence du pipeline.
Elle capture le prompt envoyé à l'IA, la réponse brute, et la sortie des outils (compilation, tests, etc.).

La table execution_logs permet de:
- Tracer toutes les actions des agents
- Auditer les décisions prises par l'IA
- Déboguer les erreurs de compilation et d'exécution
- Analyser les performances du pipeline
- Rejouer les scénarios de test
- Assurer la conformité et la traçabilité

Chaque log est associé à une tâche et à un agent, avec un horodatage précis.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, Enum
from sqlalchemy.orm import relationship
from src.db.database import Base
import datetime
import enum
import json
from typing import Optional, Dict, Any, List

# Import explicite de la base pour la déclaration du modèle
# La Base est définie dans src/db/database.py


class LogLevel(str, enum.Enum):
    """
    Niveaux de sévérité des logs.
    """
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogCategory(str, enum.Enum):
    """
    Catégories de logs.
    """
    AGENT = "agent"
    LLM = "llm"
    COMPILATION = "compilation"
    TEST = "test"
    SECURITY = "security"
    DEPLOYMENT = "deployment"
    WORKFLOW = "workflow"
    SYSTEM = "system"
    USER = "user"
    CUSTOM = "custom"


class ExecutionLogModel(Base):
    """
    Modèle ORM pour la table 'execution_logs'.

    Cette table stocke toutes les traces d'exécution du pipeline,
    permettant un audit complet et un débogage efficace.

    Attributes:
        id (int): Identifiant unique et auto-increment de l'entrée de log.
        task_id (str): Identifiant de la tâche (TaskModel) associée à ce log.
                       Clé étrangère vers 'tasks.id'.
        agent_id (str): Identifiant de l'agent (e.g., 'developer_agent_001') qui a produit ce log.
        level (LogLevel): Niveau de sévérité du log (debug, info, warning, error, critical).
        category (LogCategory): Catégorie du log (agent, llm, compilation, test, security, etc.).
        prompt_sent (str): Le prompt exact envoyé au LLM (si applicable).
        raw_response (str): La réponse brute reçue du LLM (si applicable).
        tool_output (str): La sortie de l'outil (e.g., le retour de la compilation forge,
                           le rapport de Slither). Utile pour le debugging.
        metadata (Text): Métadonnées supplémentaires au format JSON (stack trace, contexte, etc.).
        tags (Text): Tags pour la catégorisation et la recherche (format JSON list).
        created_at (datetime): Horodatage de la création de l'entrée (UTC).
        duration_ms (int): Durée de l'opération en millisecondes (optionnel).
        source_file (str): Fichier source de l'appel (optionnel).
        source_line (int): Ligne source de l'appel (optionnel).
    """
    __tablename__ = "execution_logs"

    # Colonnes principales
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    agent_id = Column(String, nullable=False, index=True)
    
    # Niveau et catégorie
    level = Column(Enum(LogLevel), default=LogLevel.INFO, nullable=False)
    category = Column(Enum(LogCategory), default=LogCategory.SYSTEM, nullable=False)
    
    # Contenu
    prompt_sent = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    tool_output = Column(Text, nullable=True)
    
    # Métadonnées
    metadata = Column(Text, nullable=True)  # JSON
    tags = Column(Text, nullable=True)      # JSON list
    
    # Horodatage et métriques
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    duration_ms = Column(Integer, nullable=True)
    
    # Informations de source
    source_file = Column(String, nullable=True)
    source_line = Column(Integer, nullable=True)

    # Index pour les requêtes fréquentes
    __table_args__ = (
        Index('idx_execution_logs_task_id', 'task_id'),
        Index('idx_execution_logs_agent_id', 'agent_id'),
        Index('idx_execution_logs_level', 'level'),
        Index('idx_execution_logs_category', 'category'),
        Index('idx_execution_logs_created_at', 'created_at'),
        Index('idx_execution_logs_task_level', 'task_id', 'level'),
        Index('idx_execution_logs_agent_category', 'agent_id', 'category'),
    )

    # Relations (optionnelles, peuvent être définies dans models_orm.py)
    # task = relationship("TaskModel", back_populates="logs")

    def __repr__(self) -> str:
        """
        Représentation lisible de l'objet pour le débogage.
        """
        return f"<ExecutionLogModel(id={self.id}, task_id='{self.task_id}', agent_id='{self.agent_id}', level='{self.level.value}', created_at={self.created_at})>"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit le log en dictionnaire.
        
        Returns:
            Dict[str, Any]: Dictionnaire représentant le log
        """
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "level": self.level.value if self.level else None,
            "category": self.category.value if self.category else None,
            "prompt_sent": self.prompt_sent,
            "raw_response": self.raw_response,
            "tool_output": self.tool_output,
            "metadata": self.get_metadata(),
            "tags": self.get_tags(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "duration_ms": self.duration_ms,
            "source_file": self.source_file,
            "source_line": self.source_line
        }

    def to_short_dict(self) -> Dict[str, Any]:
        """
        Convertit le log en dictionnaire court (pour les listes).
        
        Returns:
            Dict[str, Any]: Dictionnaire court
        """
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "level": self.level.value if self.level else None,
            "category": self.category.value if self.category else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "duration_ms": self.duration_ms
        }

    def get_metadata(self) -> Dict[str, Any]:
        """
        Récupère les métadonnées sous forme de dictionnaire.
        
        Returns:
            Dict[str, Any]: Métadonnées
        """
        if not self.metadata:
            return {}
        try:
            return json.loads(self.metadata)
        except json.JSONDecodeError:
            return {"_raw": self.metadata}

    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        """
        Définit les métadonnées à partir d'un dictionnaire.
        
        Args:
            metadata (Dict[str, Any]): Métadonnées à stocker
        """
        self.metadata = json.dumps(metadata) if metadata else None

    def get_tags(self) -> List[str]:
        """
        Récupère les tags sous forme de liste.
        
        Returns:
            List[str]: Liste des tags
        """
        if not self.tags:
            return []
        try:
            return json.loads(self.tags)
        except json.JSONDecodeError:
            return []

    def set_tags(self, tags: List[str]) -> None:
        """
        Définit les tags à partir d'une liste.
        
        Args:
            tags (List[str]): Tags à stocker
        """
        self.tags = json.dumps(tags) if tags else None

    def add_tag(self, tag: str) -> None:
        """
        Ajoute un tag.
        
        Args:
            tag (str): Tag à ajouter
        """
        current_tags = self.get_tags()
        if tag not in current_tags:
            current_tags.append(tag)
            self.set_tags(current_tags)

    def remove_tag(self, tag: str) -> None:
        """
        Supprime un tag.
        
        Args:
            tag (str): Tag à supprimer
        """
        current_tags = self.get_tags()
        if tag in current_tags:
            current_tags.remove(tag)
            self.set_tags(current_tags)

    def has_tag(self, tag: str) -> bool:
        """
        Vérifie si un tag est présent.
        
        Args:
            tag (str): Tag à vérifier
            
        Returns:
            bool: True si le tag est présent
        """
        return tag in self.get_tags()

    @classmethod
    def create_log(
        cls,
        agent_id: str,
        task_id: Optional[str] = None,
        level: LogLevel = LogLevel.INFO,
        category: LogCategory = LogCategory.SYSTEM,
        prompt_sent: Optional[str] = None,
        raw_response: Optional[str] = None,
        tool_output: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        duration_ms: Optional[int] = None,
        source_file: Optional[str] = None,
        source_line: Optional[int] = None
    ) -> "ExecutionLogModel":
        """
        Factory method pour créer un nouveau log.
        
        Args:
            agent_id: Identifiant de l'agent
            task_id: Identifiant de la tâche (optionnel)
            level: Niveau de sévérité
            category: Catégorie du log
            prompt_sent: Prompt envoyé (optionnel)
            raw_response: Réponse reçue (optionnel)
            tool_output: Sortie de l'outil (optionnel)
            metadata: Métadonnées (optionnel)
            tags: Tags (optionnel)
            duration_ms: Durée en millisecondes (optionnel)
            source_file: Fichier source (optionnel)
            source_line: Ligne source (optionnel)
            
        Returns:
            ExecutionLogModel: Instance du log
        """
        log = cls(
            agent_id=agent_id,
            task_id=task_id,
            level=level,
            category=category,
            prompt_sent=prompt_sent,
            raw_response=raw_response,
            tool_output=tool_output,
            duration_ms=duration_ms,
            source_file=source_file,
            source_line=source_line
        )
        if metadata:
            log.set_metadata(metadata)
        if tags:
            log.set_tags(tags)
        return log

    @classmethod
    def create_error_log(
        cls,
        agent_id: str,
        error_message: str,
        task_id: Optional[str] = None,
        tool_output: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ) -> "ExecutionLogModel":
        """
        Factory method pour créer un log d'erreur.
        
        Args:
            agent_id: Identifiant de l'agent
            error_message: Message d'erreur
            task_id: Identifiant de la tâche (optionnel)
            tool_output: Sortie de l'outil (optionnel)
            metadata: Métadonnées (optionnel)
            tags: Tags (optionnel)
            
        Returns:
            ExecutionLogModel: Instance du log
        """
        return cls.create_log(
            agent_id=agent_id,
            task_id=task_id,
            level=LogLevel.ERROR,
            category=LogCategory.SYSTEM,
            raw_response=error_message,
            tool_output=tool_output,
            metadata=metadata or {},
            tags=tags or ["error"]
        )

    @classmethod
    def create_llm_log(
        cls,
        agent_id: str,
        prompt: str,
        response: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None
    ) -> "ExecutionLogModel":
        """
        Factory method pour créer un log d'appel LLM.
        
        Args:
            agent_id: Identifiant de l'agent
            prompt: Prompt envoyé
            response: Réponse reçue
            task_id: Identifiant de la tâche (optionnel)
            metadata: Métadonnées (optionnel)
            duration_ms: Durée en millisecondes (optionnel)
            
        Returns:
            ExecutionLogModel: Instance du log
        """
        return cls.create_log(
            agent_id=agent_id,
            task_id=task_id,
            level=LogLevel.DEBUG,
            category=LogCategory.LLM,
            prompt_sent=prompt,
            raw_response=response,
            metadata=metadata or {},
            tags=["llm_call"],
            duration_ms=duration_ms
        )

    @classmethod
    def create_compilation_log(
        cls,
        agent_id: str,
        tool_output: str,
        task_id: Optional[str] = None,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None
    ) -> "ExecutionLogModel":
        """
        Factory method pour créer un log de compilation.
        
        Args:
            agent_id: Identifiant de l'agent
            tool_output: Sortie de la compilation
            task_id: Identifiant de la tâche (optionnel)
            success: Succès de la compilation
            metadata: Métadonnées (optionnel)
            duration_ms: Durée en millisecondes (optionnel)
            
        Returns:
            ExecutionLogModel: Instance du log
        """
        return cls.create_log(
            agent_id=agent_id,
            task_id=task_id,
            level=LogLevel.INFO if success else LogLevel.ERROR,
            category=LogCategory.COMPILATION,
            tool_output=tool_output,
            metadata=metadata or {"success": success},
            tags=["compilation", "success" if success else "failed"],
            duration_ms=duration_ms
        )

    @classmethod
    def create_security_log(
        cls,
        agent_id: str,
        tool_output: str,
        task_id: Optional[str] = None,
        vulnerabilities_found: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None
    ) -> "ExecutionLogModel":
        """
        Factory method pour créer un log de sécurité.
        
        Args:
            agent_id: Identifiant de l'agent
            tool_output: Sortie de l'outil de sécurité
            task_id: Identifiant de la tâche (optionnel)
            vulnerabilities_found: Nombre de vulnérabilités trouvées
            metadata: Métadonnées (optionnel)
            duration_ms: Durée en millisecondes (optionnel)
            
        Returns:
            ExecutionLogModel: Instance du log
        """
        level = LogLevel.ERROR if vulnerabilities_found > 0 else LogLevel.INFO
        return cls.create_log(
            agent_id=agent_id,
            task_id=task_id,
            level=level,
            category=LogCategory.SECURITY,
            tool_output=tool_output,
            metadata=metadata or {"vulnerabilities_found": vulnerabilities_found},
            tags=["security_scan", "critical" if vulnerabilities_found > 0 else "clean"],
            duration_ms=duration_ms
        )


# =============================================================================
# MIXIN POUR L'AJOUT DE LOGS
# =============================================================================

class LoggableMixin:
    """
    Mixin pour ajouter des fonctionnalités de logging aux agents.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._log_callback = None
    
    def set_log_callback(self, callback):
        """
        Définit la fonction de callback pour les logs.
        
        Args:
            callback: Fonction async appelée avec (log_model, session)
        """
        self._log_callback = callback
    
    async def log_info(
        self,
        message: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ) -> None:
        """
        Log un message d'information.
        
        Args:
            message: Message à logger
            task_id: ID de la tâche (optionnel)
            metadata: Métadonnées (optionnel)
            tags: Tags (optionnel)
        """
        await self._create_log(
            level=LogLevel.INFO,
            category=LogCategory.AGENT,
            raw_response=message,
            task_id=task_id,
            metadata=metadata,
            tags=tags
        )
    
    async def log_error(
        self,
        error: str,
        task_id: Optional[str] = None,
        tool_output: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log une erreur.
        
        Args:
            error: Message d'erreur
            task_id: ID de la tâche (optionnel)
            tool_output: Sortie de l'outil (optionnel)
            metadata: Métadonnées (optionnel)
        """
        await self._create_log(
            level=LogLevel.ERROR,
            category=LogCategory.AGENT,
            raw_response=error,
            tool_output=tool_output,
            task_id=task_id,
            metadata=metadata,
            tags=["error"]
        )
    
    async def log_llm_call(
        self,
        prompt: str,
        response: str,
        task_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log un appel LLM.
        
        Args:
            prompt: Prompt envoyé
            response: Réponse reçue
            task_id: ID de la tâche (optionnel)
            duration_ms: Durée en millisecondes
            metadata: Métadonnées (optionnel)
        """
        await self._create_log(
            level=LogLevel.DEBUG,
            category=LogCategory.LLM,
            prompt_sent=prompt,
            raw_response=response,
            task_id=task_id,
            duration_ms=duration_ms,
            metadata=metadata,
            tags=["llm_call"]
        )
    
    async def _create_log(
        self,
        level: LogLevel,
        category: LogCategory,
        prompt_sent: Optional[str] = None,
        raw_response: Optional[str] = None,
        tool_output: Optional[str] = None,
        task_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ) -> None:
        """
        Crée et sauvegarde un log.
        
        Args:
            level: Niveau de sévérité
            category: Catégorie du log
            prompt_sent: Prompt envoyé (optionnel)
            raw_response: Réponse reçue (optionnel)
            tool_output: Sortie de l'outil (optionnel)
            task_id: ID de la tâche (optionnel)
            duration_ms: Durée en millisecondes (optionnel)
            metadata: Métadonnées (optionnel)
            tags: Tags (optionnel)
        """
        if not self._log_callback:
            # Pas de callback, log uniquement en mémoire
            return
        
        log = ExecutionLogModel.create_log(
            agent_id=self.agent_id,
            task_id=task_id,
            level=level,
            category=category,
            prompt_sent=prompt_sent,
            raw_response=raw_response,
            tool_output=tool_output,
            metadata=metadata,
            tags=tags,
            duration_ms=duration_ms
        )
        
        await self._log_callback(log)