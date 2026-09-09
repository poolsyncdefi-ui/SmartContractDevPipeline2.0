# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Structured Logger
# ==============================================================================
# Fichier: src/core/structured_logger.py
# Description: Logger structuré avec contexte d'exécution pour remplacer
#              les appels hallucinés à _log_execution. Assure la traçabilité
#              complète des événements du pipeline.
# ==============================================================================

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Union, Callable
from enum import Enum
from dataclasses import dataclass, field
import traceback
import uuid


# ==============================================================================
# ÉNUMÉRATIONS
# ==============================================================================

class LogLevel(str, Enum):
    """
    Niveaux de log normalisés.
    """
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogCategory(str, Enum):
    """
    Catégories de logs pour le pipeline.
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


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class LogEvent:
    """
    Représente un événement de log structuré.
    """
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    level: LogLevel = LogLevel.INFO
    category: LogCategory = LogCategory.SYSTEM
    event_type: str = ""
    message: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    error_type: Optional[str] = None
    error_details: Optional[str] = None
    stack_trace: Optional[str] = None
    correlation_id: Optional[str] = None
    source: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'événement en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "category": self.category.value,
            "event_type": self.event_type,
            "message": self.message,
            "context": self.context,
            "error_type": self.error_type,
            "error_details": self.error_details,
            "stack_trace": self.stack_trace,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "metadata": self.metadata,
        }
    
    def to_json(self) -> str:
        """Convertit l'événement en JSON."""
        return json.dumps(self.to_dict(), default=str)


# ==============================================================================
# STRUCTURED LOGGER
# ==============================================================================

class StructuredLogger:
    """
    Logger structuré avec contexte d'exécution.
    
    Features:
    - Logs au format JSON pour une ingestion facile
    - Contexte persistant pour suivre l'exécution
    - Support des corrélations entre événements
    - Gestion des erreurs avec stack traces
    - Multiples destinations (console, fichier, callback)
    """
    
    def __init__(
        self,
        component_name: str,
        log_level: LogLevel = LogLevel.INFO,
        json_output: bool = True,
        console_output: bool = True,
        file_path: Optional[str] = None,
        callback: Optional[Callable[[LogEvent], None]] = None,
    ):
        """
        Initialise le logger structuré.
        
        Args:
            component_name: Nom du composant (ex: "ArchitectAgent")
            log_level: Niveau de log minimum
            json_output: Sortie en JSON
            console_output: Sortie vers la console
            file_path: Chemin du fichier de log (optionnel)
            callback: Fonction de callback pour les événements
        """
        self.component_name = component_name
        self.log_level = log_level
        self.json_output = json_output
        self.console_output = console_output
        self.file_path = file_path
        self.callback = callback
        
        self.context: Dict[str, Any] = {}
        self.correlation_id: Optional[str] = None
        
        # Logger Python sous-jacent
        self._logger = logging.getLogger(f"pipeline.{component_name}")
        self._logger.setLevel(self._to_python_level(log_level))
        
        # Configuration du handler console
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self._to_python_level(log_level))
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)
        
        # Configuration du handler fichier
        if file_path:
            try:
                file_handler = logging.FileHandler(file_path, encoding='utf-8')
                file_handler.setLevel(self._to_python_level(log_level))
                file_handler.setFormatter(logging.Formatter('%(message)s'))
                self._logger.addHandler(file_handler)
            except Exception as e:
                self._logger.warning(f"Failed to create file handler: {e}")
        
        self._event_count = 0
        self._error_count = 0
        
        # Génération d'un ID de corrélation initial
        self._correlation_id = str(uuid.uuid4())[:8]
    
    # ==========================================================================
    # GESTION DU CONTEXTE
    # ==========================================================================
    
    def set_context(self, **kwargs) -> None:
        """
        Définit le contexte d'exécution.
        
        Args:
            **kwargs: Paires clé/valeur du contexte
        """
        self.context.update(kwargs)
    
    def set_correlation_id(self, correlation_id: str) -> None:
        """
        Définit l'ID de corrélation.
        
        Args:
            correlation_id: ID de corrélation
        """
        self.correlation_id = correlation_id
    
    def clear_context(self) -> None:
        """Efface le contexte d'exécution."""
        self.context.clear()
    
    def get_context(self) -> Dict[str, Any]:
        """
        Retourne le contexte actuel.
        
        Returns:
            Dict[str, Any]: Contexte actuel
        """
        return self.context.copy()
    
    # ==========================================================================
    # MÉTHODES DE LOG
    # ==========================================================================
    
    def log_event(
        self,
        event_type: str,
        message: str,
        level: LogLevel = LogLevel.INFO,
        category: LogCategory = LogCategory.SYSTEM,
        **kwargs
    ) -> None:
        """
        Log un événement structuré.
        
        Args:
            event_type: Type d'événement (ex: "task_started")
            message: Message de l'événement
            level: Niveau de log
            category: Catégorie du log
            **kwargs: Données supplémentaires
        """
        if self._should_log(level):
            event = self._create_event(event_type, message, level, category, **kwargs)
            self._emit(event)
    
    def log_info(self, message: str, event_type: str = "info", **kwargs) -> None:
        """Log un message d'information."""
        self.log_event(event_type, message, LogLevel.INFO, **kwargs)
    
    def log_warning(self, message: str, event_type: str = "warning", **kwargs) -> None:
        """Log un avertissement."""
        self.log_event(event_type, message, LogLevel.WARNING, **kwargs)
    
    def log_error(
        self,
        message: str,
        error: Optional[Exception] = None,
        event_type: str = "error",
        **kwargs
    ) -> None:
        """
        Log une erreur avec sa trace.
        
        Args:
            message: Message d'erreur
            error: Exception capturée
            event_type: Type d'événement
            **kwargs: Données supplémentaires
        """
        error_data = {}
        if error:
            error_data = {
                "error_type": type(error).__name__,
                "error_details": str(error),
                "stack_trace": traceback.format_exc() if error.__traceback__ else None,
            }
            kwargs.update(error_data)
        
        self.log_event(event_type, message, LogLevel.ERROR, **kwargs)
        self._error_count += 1
    
    def log_debug(self, message: str, event_type: str = "debug", **kwargs) -> None:
        """Log un message de débogage."""
        self.log_event(event_type, message, LogLevel.DEBUG, **kwargs)
    
    def log_critical(self, message: str, event_type: str = "critical", **kwargs) -> None:
        """Log un message critique."""
        self.log_event(event_type, message, LogLevel.CRITICAL, **kwargs)
    
    # ==========================================================================
    # LOGS SPÉCIALISÉS
    # ==========================================================================
    
    def log_agent_action(
        self,
        agent_id: str,
        action: str,
        task_id: Optional[str] = None,
        success: bool = True,
        **kwargs
    ) -> None:
        """
        Log une action d'agent.
        
        Args:
            agent_id: ID de l'agent
            action: Action effectuée
            task_id: ID de la tâche associée
            success: Succès de l'action
            **kwargs: Données supplémentaires
        """
        level = LogLevel.INFO if success else LogLevel.ERROR
        self.log_event(
            event_type="agent_action",
            message=f"Agent {agent_id} executed action: {action}",
            level=level,
            category=LogCategory.AGENT,
            agent_id=agent_id,
            task_id=task_id,
            success=success,
            **kwargs
        )
    
    def log_llm_call(
        self,
        prompt: str,
        response: str,
        model: str,
        duration_ms: Optional[float] = None,
        tokens_used: Optional[int] = None,
        **kwargs
    ) -> None:
        """
        Log un appel LLM.
        
        Args:
            prompt: Prompt envoyé
            response: Réponse reçue
            model: Modèle utilisé
            duration_ms: Durée en millisecondes
            tokens_used: Nombre de tokens utilisés
            **kwargs: Données supplémentaires
        """
        self.log_event(
            event_type="llm_call",
            message=f"LLM call to {model}",
            level=LogLevel.DEBUG,
            category=LogCategory.LLM,
            prompt_preview=prompt[:200] + "..." if len(prompt) > 200 else prompt,
            response_preview=response[:200] + "..." if len(response) > 200 else response,
            model=model,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            **kwargs
        )
    
    def log_compilation(
        self,
        success: bool,
        output: str,
        duration_ms: Optional[float] = None,
        **kwargs
    ) -> None:
        """
        Log une compilation.
        
        Args:
            success: Succès de la compilation
            output: Sortie du compilateur
            duration_ms: Durée en millisecondes
            **kwargs: Données supplémentaires
        """
        level = LogLevel.INFO if success else LogLevel.ERROR
        self.log_event(
            event_type="compilation",
            message=f"Compilation {'successful' if success else 'failed'}",
            level=level,
            category=LogCategory.COMPILATION,
            output_preview=output[:500] + "..." if len(output) > 500 else output,
            success=success,
            duration_ms=duration_ms,
            **kwargs
        )
    
    def log_security_scan(
        self,
        vulnerabilities_found: int,
        output: str,
        duration_ms: Optional[float] = None,
        **kwargs
    ) -> None:
        """
        Log un scan de sécurité.
        
        Args:
            vulnerabilities_found: Nombre de vulnérabilités trouvées
            output: Sortie du scan
            duration_ms: Durée en millisecondes
            **kwargs: Données supplémentaires
        """
        level = LogLevel.ERROR if vulnerabilities_found > 0 else LogLevel.INFO
        self.log_event(
            event_type="security_scan",
            message=f"Security scan found {vulnerabilities_found} vulnerabilities",
            level=level,
            category=LogCategory.SECURITY,
            vulnerabilities_found=vulnerabilities_found,
            output_preview=output[:500] + "..." if len(output) > 500 else output,
            duration_ms=duration_ms,
            **kwargs
        )
    
    # ==========================================================================
    # MÉTHODES PRIVÉES
    # ==========================================================================
    
    def _should_log(self, level: LogLevel) -> bool:
        """
        Vérifie si le niveau de log doit être traité.
        
        Args:
            level: Niveau de log
            
        Returns:
            bool: True si le log doit être émis
        """
        levels = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]
        return levels.index(level) >= levels.index(self.log_level)
    
    def _create_event(
        self,
        event_type: str,
        message: str,
        level: LogLevel,
        category: LogCategory,
        **kwargs
    ) -> LogEvent:
        """
        Crée un événement de log.
        
        Args:
            event_type: Type d'événement
            message: Message
            level: Niveau de log
            category: Catégorie
            **kwargs: Données supplémentaires
            
        Returns:
            LogEvent: Événement créé
        """
        self._event_count += 1
        
        # Extraire les données d'erreur si présentes
        error_type = kwargs.pop("error_type", None)
        error_details = kwargs.pop("error_details", None)
        stack_trace = kwargs.pop("stack_trace", None)
        task_id = kwargs.pop("task_id", None)
        agent_id = kwargs.pop("agent_id", None)
        
        return LogEvent(
            level=level,
            category=category,
            event_type=event_type,
            message=message,
            context=self.context.copy(),
            error_type=error_type,
            error_details=error_details,
            stack_trace=stack_trace,
            correlation_id=self.correlation_id or self._correlation_id,
            source=self.component_name,
            task_id=task_id,
            agent_id=agent_id,
            metadata=kwargs,
        )
    
    def _emit(self, event: LogEvent) -> None:
        """
        Émet un événement de log.
        
        Args:
            event: Événement à émettre
        """
        # Émission vers le logger Python
        python_level = self._to_python_level(event.level)
        if self.json_output:
            self._logger.log(python_level, event.to_json())
        else:
            self._logger.log(python_level, event.message)
        
        # Callback
        if self.callback:
            try:
                self.callback(event)
            except Exception as e:
                self._logger.error(f"Callback error: {e}")
    
    def _to_python_level(self, level: LogLevel) -> int:
        """Convertit LogLevel en niveau Python."""
        mapping = {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL,
        }
        return mapping.get(level, logging.INFO)
    
    # ==========================================================================
    # MÉTRIQUES
    # ==========================================================================
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Retourne les métriques du logger.
        
        Returns:
            Dict[str, Any]: Métriques
        """
        return {
            "component_name": self.component_name,
            "event_count": self._event_count,
            "error_count": self._error_count,
            "log_level": self.log_level.value,
            "json_output": self.json_output,
            "console_output": self.console_output,
            "file_path": self.file_path,
            "correlation_id": self.correlation_id or self._correlation_id,
            "context_size": len(self.context),
        }
    
    def reset_counters(self) -> None:
        """Réinitialise les compteurs d'événements et d'erreurs."""
        self._event_count = 0
        self._error_count = 0


# ==============================================================================
# FONCTION DE CONVENANCE - LOGGER FACTORY
# ==============================================================================

def create_logger(
    component_name: str,
    log_level: LogLevel = LogLevel.INFO,
    **kwargs
) -> StructuredLogger:
    """
    Crée un logger structuré avec les paramètres par défaut.
    
    Args:
        component_name: Nom du composant
        log_level: Niveau de log
        **kwargs: Arguments supplémentaires pour StructuredLogger
        
    Returns:
        StructuredLogger: Logger configuré
    """
    return StructuredLogger(
        component_name=component_name,
        log_level=log_level,
        **kwargs
    )


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Structured Logger")
    print("=" * 60)
    
    # Création du logger
    logger = StructuredLogger(
        component_name="TestComponent",
        log_level=LogLevel.DEBUG,
        json_output=False
    )
    
    # Test du contexte
    print("\n📋 Test du contexte:")
    logger.set_context(project_id="proj_123", sprint_id="sprint_001")
    print(f"  Contexte: {logger.get_context()}")
    
    # Test des logs
    print("\n📋 Test des logs:")
    logger.log_info("Test d'information", event_type="test_info", extra_data="value")
    logger.log_warning("Test d'avertissement", event_type="test_warning")
    logger.log_debug("Test de débogage", event_type="test_debug")
    
    # Test des logs d'erreur
    print("\n📋 Test des logs d'erreur:")
    try:
        raise ValueError("Test d'erreur")
    except ValueError as e:
        logger.log_error("Erreur capturée", error=e, event_type="test_error", task_id="task_001")
    
    # Test des logs spécialisés
    print("\n📋 Test des logs spécialisés:")
    logger.log_agent_action(
        agent_id="agent_001",
        action="execute_task",
        task_id="task_001",
        success=True,
        details="Action exécutée avec succès"
    )
    
    logger.log_llm_call(
        prompt="Génère un contrat ERC20",
        response="contract MyToken { ... }",
        model="deepseek-coder:6.7b-instruct",
        duration_ms=1500.5,
        tokens_used=256
    )
    
    logger.log_compilation(
        success=True,
        output="Compilation successful: 5 contracts compiled",
        duration_ms=250.0
    )
    
    logger.log_security_scan(
        vulnerabilities_found=2,
        output="Found 2 vulnerabilities: 1 critical, 1 high",
        duration_ms=3000.0
    )
    
    # Test des métriques
    print("\n📋 Test des métriques:")
    metrics = logger.get_metrics()
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    
    print("\n✅ Tests terminés.")