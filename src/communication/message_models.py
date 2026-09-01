# src/communication/message_models.py

"""
Message models for inter-agent communication.
F23 – src/communication/message_models.py

Rôle Fonctionnel : Schemas de messages Pydantic pour les echanges inter-agents sur le Bus.
Ce module definit les structures de messages utilisees pour la communication
entre les differents agents du pipeline. Il supporte:
- Différents types de messages (tâche, résultat, erreur, événement, etc.)
- Le routage entre agents (point-à-point et broadcast)
- Les métadonnées et le suivi des messages
- La validation des payloads
- Les niveaux de priorité
- La gestion du cycle de vie des messages

Les messages sont utilisés par le MessageBus pour assurer la communication
découplée entre les composants du pipeline.
"""
from enum import Enum
from pydantic import BaseModel, Field, validator, root_validator
from typing import Optional, Dict, Any, List, Set, Union
from datetime import datetime, timedelta
import uuid
import json
import logging

# Configuration du logging
logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS DES TYPES DE MESSAGES
# =============================================================================

class MessageType(str, Enum):
    """
    Types de messages supportés par le système.
    """
    # Messages de base
    TASK = "task"                    # Tâche à exécuter
    RESULT = "result"                # Résultat d'une tâche
    ERROR = "error"                  # Erreur
    PING = "ping"                    # Ping de santé
    PONG = "pong"                    # Pong de réponse
    STATUS = "status"                # Demande/rapport de statut
    
    # Messages avancés
    NOTIFICATION = "notification"    # Notification
    EVENT = "event"                  # Événement système
    COMMAND = "command"              # Commande
    QUERY = "query"                  # Requête (demande d'information)
    RESPONSE = "response"            # Réponse à une requête
    ACKNOWLEDGMENT = "ack"           # Accusé de réception
    HEARTBEAT = "heartbeat"          # Signal de vie
    METRICS = "metrics"              # Métriques
    LOG = "log"                      # Message de log
    CONFIG = "config"                # Message de configuration
    PROGRESS = "progress"            # Progression d'une tâche
    
    # Messages de coordination
    REGISTER = "register"            # Enregistrement d'un agent
    UNREGISTER = "unregister"        # Désenregistrement
    DISCOVERY = "discovery"          # Découverte de services
    LEADER_ELECTION = "leader_election" # Élection de leader
    CIRCUIT_BREAKER = "circuit_breaker" # État du circuit breaker
    RETRY = "retry"                  # Demande de réessai
    CANCEL = "cancel"                # Annulation
    RESUME = "resume"                # Reprise


class MessagePriority(str, Enum):
    """
    Niveaux de priorité pour les messages.
    """
    CRITICAL = "critical"  # Priorité critique (10)
    HIGH = "high"          # Haute priorité (8-9)
    NORMAL = "normal"      # Priorité normale (5)
    LOW = "low"            # Basse priorité (2-3)
    BACKGROUND = "background"  # Priorité de fond (0-1)


class MessageStatus(str, Enum):
    """
    Statuts possibles pour un message.
    """
    PENDING = "pending"          # En attente d'envoi
    SENT = "sent"                # Envoyé
    DELIVERED = "delivered"      # Livré au destinataire
    PROCESSING = "processing"    # En cours de traitement
    PROCESSED = "processed"      # Traité
    FAILED = "failed"            # Échec de livraison
    EXPIRED = "expired"          # Expiré (TTL dépassé)
    CANCELLED = "cancelled"      # Annulé


class MessageDeliveryMode(str, Enum):
    """
    Modes de livraison.
    """
    POINT_TO_POINT = "point_to_point"  # Point-à-point (1 destinataire)
    PUBLISH_SUBSCRIBE = "publish_subscribe"  # Publication/abonnement
    ROUND_ROBIN = "round_robin"        # Tourniquet
    BROADCAST = "broadcast"            # Diffusion (tous)
    ANYCASTER = "anycaster"            # Un parmi plusieurs


# =============================================================================
# CLASSES DE BASE POUR LES MESSAGES
# =============================================================================

class BaseMessage(BaseModel):
    """
    Message de base pour la communication inter-agents.
    
    Cette classe définit la structure commune à tous les messages du système.
    Elle inclut les champs de base tels que l'identifiant, le type, l'expéditeur,
    et les métadonnées de suivi.
    
    Attributes:
        id (str): Identifiant unique du message (UUID)
        type (MessageType): Type de message
        sender (str): ID de l'agent expéditeur
        recipient (Optional[str]): ID du destinataire (None = broadcast)
        delivery_mode (MessageDeliveryMode): Mode de livraison
        timestamp (datetime): Horodatage de création
        correlation_id (Optional[str]): ID de corrélation (pour suivre les conversations)
        parent_id (Optional[str]): ID du message parent
        priority (int): Niveau de priorité (0-10)
        ttl (Optional[int]): Durée de vie en secondes (None = infini)
        status (MessageStatus): Statut du message
        retry_count (int): Nombre de tentatives de livraison
        metadata (Dict[str, Any]): Métadonnées supplémentaires
    """
    # Champs obligatoires
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    sender: str = Field(..., min_length=1, description="ID de l'agent expéditeur")
    
    # Champs optionnels
    recipient: Optional[str] = Field(None, description="ID du destinataire")
    delivery_mode: MessageDeliveryMode = Field(
        default=MessageDeliveryMode.POINT_TO_POINT,
        description="Mode de livraison"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = Field(None, description="ID de corrélation")
    parent_id: Optional[str] = Field(None, description="ID du message parent")
    priority: int = Field(5, ge=0, le=10, description="Priorité (0-10)")
    ttl: Optional[int] = Field(None, ge=1, description="Durée de vie en secondes")
    status: MessageStatus = Field(default=MessageStatus.PENDING)
    retry_count: int = Field(0, ge=0, description="Nombre de tentatives")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées")
    
    @validator('priority')
    def validate_priority(cls, v):
        """Valide le niveau de priorité."""
        if not 0 <= v <= 10:
            raise ValueError(f"Priority must be between 0 and 10, got {v}")
        return v
    
    @validator('ttl')
    def validate_ttl(cls, v):
        """Valide le TTL."""
        if v is not None and v < 1:
            raise ValueError(f"TTL must be at least 1 second, got {v}")
        return v
    
    @validator('sender')
    def validate_sender(cls, v):
        """Valide l'ID de l'expéditeur."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Sender cannot be empty")
        return v.strip()
    
    @root_validator
    def validate_recipient(cls, values):
        """Valide la cohérence des champs."""
        delivery_mode = values.get('delivery_mode')
        recipient = values.get('recipient')
        
        if delivery_mode == MessageDeliveryMode.POINT_TO_POINT and not recipient:
            raise ValueError("Recipient is required for point-to-point delivery")
        
        if delivery_mode == MessageDeliveryMode.BROADCAST and recipient:
            raise ValueError("Recipient must be None for broadcast delivery")
        
        return values
    
    def is_expired(self) -> bool:
        """Vérifie si le message a expiré."""
        if self.ttl is None:
            return False
        if self.status == MessageStatus.PROCESSED:
            return False
        age = (datetime.utcnow() - self.timestamp).total_seconds()
        return age > self.ttl
    
    def to_json(self) -> str:
        """Convertit le message en JSON."""
        return self.model_dump_json()
    
    @classmethod
    def from_json(cls, json_str: str) -> 'BaseMessage':
        """Crée un message depuis JSON."""
        return cls.model_validate_json(json_str)
    
    def copy_with(self, **kwargs) -> 'BaseMessage':
        """Crée une copie du message avec des champs modifiés."""
        data = self.model_dump()
        data.update(kwargs)
        return self.__class__(**data)
    
    def to_dict(self) -> Dict:
        """Convertit le message en dictionnaire."""
        return self.model_dump()
    
    def get_priority_level(self) -> int:
        """Retourne le niveau de priorité numérique."""
        return self.priority
    
    def is_reply_to(self, other: 'BaseMessage') -> bool:
        """Vérifie si ce message est une réponse à un autre."""
        return self.correlation_id == other.id
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id}, type={self.type.value}, sender={self.sender}, status={self.status.value})>"


# =============================================================================
# MESSAGES SPÉCIALISÉS
# =============================================================================

class TaskMessage(BaseMessage):
    """
    Message de tâche.
    
    Représente une tâche à exécuter par un agent.
    
    Attributes:
        type (MessageType): Type de message (TASK)
        payload (Dict[str, Any]): Contenu de la tâche
    """
    type: MessageType = MessageType.TASK
    payload: Dict[str, Any] = Field(..., description="Données de la tâche")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la tâche."""
        required_fields = ['task_id', 'action']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        return v
    
    def get_task_id(self) -> str:
        """Retourne l'ID de la tâche."""
        return self.payload.get('task_id', '')
    
    def get_action(self) -> str:
        """Retourne l'action à exécuter."""
        return self.payload.get('action', '')
    
    def get_parameters(self) -> Dict[str, Any]:
        """Retourne les paramètres de la tâche."""
        return self.payload.get('parameters', {})
    
    def get_context(self) -> Dict[str, Any]:
        """Retourne le contexte de la tâche."""
        return self.payload.get('context', {})


class ResultMessage(BaseMessage):
    """
    Message de résultat.
    
    Représente le résultat d'une tâche exécutée.
    
    Attributes:
        type (MessageType): Type de message (RESULT)
        payload (Dict[str, Any]): Contenu du résultat
    """
    type: MessageType = MessageType.RESULT
    payload: Dict[str, Any] = Field(..., description="Données du résultat")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload du résultat."""
        required_fields = ['task_id', 'status']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        
        if v['status'] not in ['SUCCESS', 'FAILED', 'CIRCUIT_OPEN']:
            raise ValueError(f"Invalid status: {v['status']}")
        
        return v
    
    def is_success(self) -> bool:
        """Vérifie si le résultat est un succès."""
        return self.payload.get('status') == 'SUCCESS'
    
    def is_failure(self) -> bool:
        """Vérifie si le résultat est un échec."""
        return self.payload.get('status') == 'FAILED'
    
    def get_result(self) -> Optional[Dict[str, Any]]:
        """Retourne le résultat si succès."""
        if self.is_success():
            return self.payload.get('result')
        return None
    
    def get_error(self) -> Optional[str]:
        """Retourne l'erreur si échec."""
        if self.is_failure():
            return self.payload.get('error', 'Unknown error')
        return None


class ErrorMessage(BaseMessage):
    """
    Message d'erreur.
    
    Représente une erreur survenue dans le système.
    
    Attributes:
        type (MessageType): Type de message (ERROR)
        payload (Dict[str, Any]): Contenu de l'erreur
    """
    type: MessageType = MessageType.ERROR
    payload: Dict[str, Any] = Field(..., description="Données de l'erreur")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de l'erreur."""
        required_fields = ['code', 'message']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        return v
    
    def get_error_code(self) -> str:
        """Retourne le code d'erreur."""
        return self.payload.get('code', 'UNKNOWN')
    
    def get_error_message(self) -> str:
        """Retourne le message d'erreur."""
        return self.payload.get('message', 'Unknown error')
    
    def get_details(self) -> Optional[Dict[str, Any]]:
        """Retourne les détails de l'erreur."""
        return self.payload.get('details')


class NotificationMessage(BaseMessage):
    """
    Message de notification.
    
    Représente une notification à envoyer aux agents ou à l'interface.
    
    Attributes:
        type (MessageType): Type de message (NOTIFICATION)
        payload (Dict[str, Any]): Contenu de la notification
    """
    type: MessageType = MessageType.NOTIFICATION
    payload: Dict[str, Any] = Field(..., description="Données de la notification")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la notification."""
        required_fields = ['title', 'message']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        return v
    
    def get_title(self) -> str:
        """Retourne le titre de la notification."""
        return self.payload.get('title', '')
    
    def get_message(self) -> str:
        """Retourne le message de la notification."""
        return self.payload.get('message', '')
    
    def get_level(self) -> str:
        """Retourne le niveau de la notification."""
        return self.payload.get('level', 'info')


class EventMessage(BaseMessage):
    """
    Message d'événement.
    
    Représente un événement système.
    
    Attributes:
        type (MessageType): Type de message (EVENT)
        payload (Dict[str, Any]): Contenu de l'événement
    """
    type: MessageType = MessageType.EVENT
    payload: Dict[str, Any] = Field(..., description="Données de l'événement")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de l'événement."""
        required_fields = ['event_type', 'data']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        return v
    
    def get_event_type(self) -> str:
        """Retourne le type d'événement."""
        return self.payload.get('event_type', '')
    
    def get_data(self) -> Any:
        """Retourne les données de l'événement."""
        return self.payload.get('data')


class QueryMessage(BaseMessage):
    """
    Message de requête.
    
    Représente une requête d'information.
    
    Attributes:
        type (MessageType): Type de message (QUERY)
        payload (Dict[str, Any]): Contenu de la requête
    """
    type: MessageType = MessageType.QUERY
    payload: Dict[str, Any] = Field(..., description="Données de la requête")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la requête."""
        if 'query' not in v:
            raise ValueError("Payload missing required field: query")
        return v
    
    def get_query(self) -> str:
        """Retourne la requête."""
        return self.payload.get('query', '')
    
    def get_parameters(self) -> Dict[str, Any]:
        """Retourne les paramètres de la requête."""
        return self.payload.get('parameters', {})
    
    def get_timeout(self) -> Optional[int]:
        """Retourne le timeout en secondes."""
        return self.payload.get('timeout')


class ResponseMessage(BaseMessage):
    """
    Message de réponse.
    
    Représente une réponse à une requête.
    
    Attributes:
        type (MessageType): Type de message (RESPONSE)
        payload (Dict[str, Any]): Contenu de la réponse
    """
    type: MessageType = MessageType.RESPONSE
    payload: Dict[str, Any] = Field(..., description="Données de la réponse")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la réponse."""
        if 'data' not in v:
            raise ValueError("Payload missing required field: data")
        return v
    
    def get_data(self) -> Any:
        """Retourne les données de la réponse."""
        return self.payload.get('data')
    
    def is_error(self) -> bool:
        """Vérifie si la réponse contient une erreur."""
        return 'error' in self.payload
    
    def get_error(self) -> Optional[str]:
        """Retourne l'erreur si présente."""
        return self.payload.get('error')


class AcknowledgmentMessage(BaseMessage):
    """
    Message d'accusé de réception.
    
    Représente une confirmation de réception d'un message.
    
    Attributes:
        type (MessageType): Type de message (ACKNOWLEDGMENT)
        payload (Dict[str, Any]): Contenu de l'accusé
    """
    type: MessageType = MessageType.ACKNOWLEDGMENT
    payload: Dict[str, Any] = Field(..., description="Données de l'accusé")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de l'accusé."""
        if 'message_id' not in v:
            raise ValueError("Payload missing required field: message_id")
        return v
    
    def get_message_id(self) -> str:
        """Retourne l'ID du message accusé."""
        return self.payload.get('message_id', '')
    
    def is_acknowledged(self) -> bool:
        """Vérifie si l'accusé est positif."""
        return self.payload.get('success', True)
    
    def get_error(self) -> Optional[str]:
        """Retourne l'erreur si échec."""
        if not self.is_acknowledged():
            return self.payload.get('error', 'Unknown error')
        return None


class HeartbeatMessage(BaseMessage):
    """
    Message de heartbeat.
    
    Représente un signal de vie d'un agent.
    
    Attributes:
        type (MessageType): Type de message (HEARTBEAT)
        payload (Dict[str, Any]): Contenu du heartbeat
    """
    type: MessageType = MessageType.HEARTBEAT
    payload: Dict[str, Any] = Field(..., description="Données du heartbeat")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload du heartbeat."""
        if 'status' not in v:
            raise ValueError("Payload missing required field: status")
        return v
    
    def get_status(self) -> str:
        """Retourne le statut de l'agent."""
        return self.payload.get('status', 'unknown')
    
    def get_metrics(self) -> Optional[Dict[str, Any]]:
        """Retourne les métriques de l'agent."""
        return self.payload.get('metrics')
    
    def get_capabilities(self) -> List[str]:
        """Retourne les capacités de l'agent."""
        return self.payload.get('capabilities', [])


class ProgressMessage(BaseMessage):
    """
    Message de progression.
    
    Représente la progression d'une tâche.
    
    Attributes:
        type (MessageType): Type de message (PROGRESS)
        payload (Dict[str, Any]): Contenu de la progression
    """
    type: MessageType = MessageType.PROGRESS
    payload: Dict[str, Any] = Field(..., description="Données de la progression")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la progression."""
        required_fields = ['task_id', 'progress']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        
        progress = v['progress']
        if not isinstance(progress, (int, float)):
            raise ValueError("Progress must be a number")
        if not 0 <= progress <= 100:
            raise ValueError(f"Progress must be between 0 and 100, got {progress}")
        
        return v
    
    def get_task_id(self) -> str:
        """Retourne l'ID de la tâche."""
        return self.payload.get('task_id', '')
    
    def get_progress(self) -> float:
        """Retourne la progression (0-100)."""
        return self.payload.get('progress', 0.0)
    
    def get_message(self) -> Optional[str]:
        """Retourne le message de progression."""
        return self.payload.get('message')
    
    def get_remaining(self) -> Optional[str]:
        """Retourne le temps restant estimé."""
        return self.payload.get('remaining')


class CircuitBreakerMessage(BaseMessage):
    """
    Message de circuit breaker.
    
    Représente une notification de changement d'état du circuit breaker.
    
    Attributes:
        type (MessageType): Type de message (CIRCUIT_BREAKER)
        payload (Dict[str, Any]): Contenu du circuit breaker
    """
    type: MessageType = MessageType.CIRCUIT_BREAKER
    payload: Dict[str, Any] = Field(..., description="Données du circuit breaker")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload du circuit breaker."""
        required_fields = ['component', 'state']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Payload missing required field: {field}")
        
        if v['state'] not in ['OPEN', 'CLOSED', 'HALF_OPEN']:
            raise ValueError(f"Invalid circuit breaker state: {v['state']}")
        
        return v
    
    def get_component(self) -> str:
        """Retourne le composant concerné."""
        return self.payload.get('component', '')
    
    def get_state(self) -> str:
        """Retourne l'état du circuit breaker."""
        return self.payload.get('state', 'CLOSED')
    
    def get_error(self) -> Optional[str]:
        """Retourne l'erreur si présente."""
        return self.payload.get('error')
    
    def get_timestamp(self) -> Optional[datetime]:
        """Retourne l'horodatage du changement."""
        return self.payload.get('timestamp')


class CommandMessage(BaseMessage):
    """
    Message de commande.
    
    Représente une commande à exécuter.
    
    Attributes:
        type (MessageType): Type de message (COMMAND)
        payload (Dict[str, Any]): Contenu de la commande
    """
    type: MessageType = MessageType.COMMAND
    payload: Dict[str, Any] = Field(..., description="Données de la commande")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la commande."""
        if 'command' not in v:
            raise ValueError("Payload missing required field: command")
        return v
    
    def get_command(self) -> str:
        """Retourne la commande."""
        return self.payload.get('command', '')
    
    def get_parameters(self) -> Dict[str, Any]:
        """Retourne les paramètres de la commande."""
        return self.payload.get('parameters', {})


class MetricsMessage(BaseMessage):
    """
    Message de métriques.
    
    Représente des métriques système.
    
    Attributes:
        type (MessageType): Type de message (METRICS)
        payload (Dict[str, Any]): Contenu des métriques
    """
    type: MessageType = MessageType.METRICS
    payload: Dict[str, Any] = Field(..., description="Données des métriques")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload des métriques."""
        if 'metrics' not in v:
            raise ValueError("Payload missing required field: metrics")
        return v
    
    def get_metrics(self) -> Dict[str, Any]:
        """Retourne les métriques."""
        return self.payload.get('metrics', {})
    
    def get_type(self) -> str:
        """Retourne le type de métriques."""
        return self.payload.get('type', 'generic')
    
    def get_tags(self) -> Dict[str, str]:
        """Retourne les tags des métriques."""
        return self.payload.get('tags', {})


class ConfigMessage(BaseMessage):
    """
    Message de configuration.
    
    Représente une mise à jour de configuration.
    
    Attributes:
        type (MessageType): Type de message (CONFIG)
        payload (Dict[str, Any]): Contenu de la configuration
    """
    type: MessageType = MessageType.CONFIG
    payload: Dict[str, Any] = Field(..., description="Données de la configuration")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Valide le payload de la configuration."""
        if 'config' not in v:
            raise ValueError("Payload missing required field: config")
        return v
    
    def get_config(self) -> Dict[str, Any]:
        """Retourne la configuration."""
        return self.payload.get('config', {})
    
    def get_version(self) -> Optional[str]:
        """Retourne la version de la configuration."""
        return self.payload.get('version')
    
    def get_component(self) -> Optional[str]:
        """Retourne le composant concerné."""
        return self.payload.get('component')


# =============================================================================
# FACTORY DE MESSAGES
# =============================================================================

class MessageFactory:
    """
    Fabrique de messages.
    
    Centralise la création des messages pour garantir la cohérence.
    """
    
    @staticmethod
    def create_task_message(
        sender: str,
        recipient: str,
        task_id: str,
        action: str,
        parameters: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> TaskMessage:
        """
        Crée un message de tâche.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            task_id: ID de la tâche
            action: Action à exécuter
            parameters: Paramètres de la tâche
            context: Contexte de la tâche
            **kwargs: Champs supplémentaires
            
        Returns:
            TaskMessage: Message de tâche
        """
        payload = {
            'task_id': task_id,
            'action': action,
            'parameters': parameters or {},
            'context': context or {}
        }
        return TaskMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            **kwargs
        )
    
    @staticmethod
    def create_result_message(
        sender: str,
        recipient: str,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        correlation_id: Optional[str] = None,
        **kwargs
    ) -> ResultMessage:
        """
        Crée un message de résultat.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            task_id: ID de la tâche
            status: SUCCESS, FAILED, ou CIRCUIT_OPEN
            result: Résultat (si succès)
            error: Message d'erreur (si échec)
            correlation_id: ID de corrélation
            **kwargs: Champs supplémentaires
            
        Returns:
            ResultMessage: Message de résultat
        """
        payload = {
            'task_id': task_id,
            'status': status
        }
        if result is not None:
            payload['result'] = result
        if error is not None:
            payload['error'] = error
        
        return ResultMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            correlation_id=correlation_id,
            **kwargs
        )
    
    @staticmethod
    def create_error_message(
        sender: str,
        recipient: str,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        **kwargs
    ) -> ErrorMessage:
        """
        Crée un message d'erreur.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            code: Code d'erreur
            message: Message d'erreur
            details: Détails de l'erreur
            correlation_id: ID de corrélation
            **kwargs: Champs supplémentaires
            
        Returns:
            ErrorMessage: Message d'erreur
        """
        payload = {
            'code': code,
            'message': message
        }
        if details is not None:
            payload['details'] = details
        
        return ErrorMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            correlation_id=correlation_id,
            **kwargs
        )
    
    @staticmethod
    def create_notification_message(
        sender: str,
        recipient: Optional[str],
        title: str,
        message: str,
        level: str = 'info',
        **kwargs
    ) -> NotificationMessage:
        """
        Crée un message de notification.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            title: Titre de la notification
            message: Message de la notification
            level: Niveau de la notification
            **kwargs: Champs supplémentaires
            
        Returns:
            NotificationMessage: Message de notification
        """
        payload = {
            'title': title,
            'message': message,
            'level': level
        }
        return NotificationMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            **kwargs
        )
    
    @staticmethod
    def create_event_message(
        sender: str,
        recipient: Optional[str],
        event_type: str,
        data: Any,
        **kwargs
    ) -> EventMessage:
        """
        Crée un message d'événement.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            event_type: Type d'événement
            data: Données de l'événement
            **kwargs: Champs supplémentaires
            
        Returns:
            EventMessage: Message d'événement
        """
        payload = {
            'event_type': event_type,
            'data': data
        }
        return EventMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            **kwargs
        )
    
    @staticmethod
    def create_progress_message(
        sender: str,
        recipient: str,
        task_id: str,
        progress: float,
        message: Optional[str] = None,
        remaining: Optional[str] = None,
        **kwargs
    ) -> ProgressMessage:
        """
        Crée un message de progression.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            task_id: ID de la tâche
            progress: Progression (0-100)
            message: Message de progression
            remaining: Temps restant estimé
            **kwargs: Champs supplémentaires
            
        Returns:
            ProgressMessage: Message de progression
        """
        payload = {
            'task_id': task_id,
            'progress': progress
        }
        if message is not None:
            payload['message'] = message
        if remaining is not None:
            payload['remaining'] = remaining
        
        return ProgressMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            **kwargs
        )
    
    @staticmethod
    def create_response_message(
        sender: str,
        recipient: str,
        data: Any,
        error: Optional[str] = None,
        correlation_id: Optional[str] = None,
        **kwargs
    ) -> ResponseMessage:
        """
        Crée un message de réponse.
        
        Args:
            sender: ID de l'expéditeur
            recipient: ID du destinataire
            data: Données de la réponse
            error: Message d'erreur (optionnel)
            correlation_id: ID de corrélation
            **kwargs: Champs supplémentaires
            
        Returns:
            ResponseMessage: Message de réponse
        """
        payload = {'data': data}
        if error is not None:
            payload['error'] = error
        
        return ResponseMessage(
            sender=sender,
            recipient=recipient,
            payload=payload,
            correlation_id=correlation_id,
            **kwargs
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    'MessageType',
    'MessagePriority',
    'MessageStatus',
    'MessageDeliveryMode',
    
    # Messages de base
    'BaseMessage',
    'TaskMessage',
    'ResultMessage',
    'ErrorMessage',
    
    # Messages avancés
    'NotificationMessage',
    'EventMessage',
    'QueryMessage',
    'ResponseMessage',
    'AcknowledgmentMessage',
    'HeartbeatMessage',
    'ProgressMessage',
    'CircuitBreakerMessage',
    'CommandMessage',
    'MetricsMessage',
    'ConfigMessage',
    
    # Factory
    'MessageFactory'
]