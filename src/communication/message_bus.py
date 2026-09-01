# src/communication/message_bus.py

"""
Abstract message bus interface for inter-agent communication.
F24 – src/communication/message_bus.py

Rôle Fonctionnel : Interface abstraite du Message Bus pour le decouplage des agents.
Ce module definit l'interface de base pour le bus de messages,
permettant la communication asynchrone entre les differents composants
du pipeline. L'interface supporte:
- La publication de messages (publish)
- L'abonnement a des topics (subscribe/unsubscribe)
- Le filtrage des messages
- La gestion des erreurs et des retries
- Les métriques de communication
- Le pattern request/response

Cette interface est implementee par RedisBus, mais peut etre etendue
pour d'autres transports (RabbitMQ, Kafka, etc.)
"""
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional, Dict, Any, List, Set, Union
from datetime import datetime
import logging
import asyncio
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.communication.message_models import (
    BaseMessage,
    MessageType,
    MessageStatus,
    MessageDeliveryMode,
    MessagePriority,
    TaskMessage,
    ResultMessage,
    ErrorMessage,
    NotificationMessage,
    EventMessage,
    QueryMessage,
    ResponseMessage,
    AcknowledgmentMessage,
    HeartbeatMessage,
    ProgressMessage,
    CircuitBreakerMessage,
    CommandMessage,
    MetricsMessage,
    ConfigMessage
)

# Configuration du logging
logger = logging.getLogger(__name__)


class SubscriptionType(str, Enum):
    """
    Types d'abonnement.
    """
    EXACT = "exact"          # Correspondance exacte du topic
    PATTERN = "pattern"      # Pattern regex (wildcard)
    PREFIX = "prefix"        # Prefix du topic
    MULTI = "multi"          # Multiples topics


@dataclass
class Subscription:
    """
    Représente un abonnement.
    
    Attributes:
        id (str): Identifiant unique de l'abonnement
        topic (str): Topic du message
        callback (Callable): Fonction de callback
        subscription_type (SubscriptionType): Type d'abonnement
        filter_criteria (Optional[Dict]): Critères de filtrage
        created_at (datetime): Date de création
        active (bool): Abonnement actif
        message_count (int): Nombre de messages reçus
        last_message_at (Optional[datetime]): Dernier message reçu
    """
    id: str
    topic: str
    callback: Callable[[BaseMessage], Awaitable[None]]
    subscription_type: SubscriptionType = SubscriptionType.EXACT
    filter_criteria: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    active: bool = True
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    
    def matches(self, topic: str) -> bool:
        """
        Vérifie si le topic correspond à l'abonnement.
        
        Args:
            topic: Topic à vérifier
            
        Returns:
            bool: True si correspond
        """
        if self.subscription_type == SubscriptionType.EXACT:
            return self.topic == topic
        elif self.subscription_type == SubscriptionType.PREFIX:
            return topic.startswith(self.topic)
        elif self.subscription_type == SubscriptionType.PATTERN:
            import re
            return re.match(self.topic, topic) is not None
        return False


@dataclass
class MessageBusStats:
    """
    Statistiques du bus de messages.
    
    Attributes:
        total_published (int): Nombre total de messages publiés
        total_delivered (int): Nombre total de messages délivrés
        total_errors (int): Nombre total d'erreurs
        total_subscriptions (int): Nombre total d'abonnements
        topics_count (int): Nombre de topics actifs
        active_subscribers (int): Nombre d'abonnés actifs
        last_activity (Optional[datetime]): Dernière activité
        by_type (Dict[str, int]): Messages par type
        by_priority (Dict[str, int]): Messages par priorité
        by_status (Dict[str, int]): Messages par statut
    """
    total_published: int = 0
    total_delivered: int = 0
    total_errors: int = 0
    total_subscriptions: int = 0
    topics_count: int = 0
    active_subscribers: int = 0
    last_activity: Optional[datetime] = None
    by_type: Dict[str, int] = field(default_factory=dict)
    by_priority: Dict[str, int] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)


class MessageBus(ABC):
    """
    Interface abstraite pour le bus de messages.
    
    Cette interface définit le contrat pour toutes les implémentations
    du bus de messages. Elle permet la communication asynchrone et
    découplée entre les composants du pipeline.
    
    Attributes:
        name (str): Nom du bus
        stats (MessageBusStats): Statistiques du bus
        subscriptions (Dict[str, Subscription]): Abonnements actifs
        message_queue (asyncio.Queue): File d'attente des messages
        is_running (bool): Indique si le bus est en cours d'exécution
        max_queue_size (int): Taille maximale de la file d'attente
        retry_attempts (int): Nombre de tentatives de livraison
    """
    
    def __init__(
        self,
        name: str = "default",
        max_queue_size: int = 10000,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
        enable_stats: bool = True
    ):
        """
        Initialise le bus de messages.
        
        Args:
            name: Nom du bus (defaut: "default")
            max_queue_size: Taille maximale de la file d'attente
            retry_attempts: Nombre de tentatives de livraison
            retry_delay: Délai entre les tentatives (secondes)
            enable_stats: Activer les statistiques (defaut: True)
        """
        self.name = name
        self.max_queue_size = max_queue_size
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.enable_stats = enable_stats
        
        # Gestion des abonnements
        self._subscriptions: Dict[str, Subscription] = {}
        self._subscription_counter = 0
        
        # File d'attente des messages
        self._message_queue: Optional[asyncio.Queue] = None
        self._is_running = False
        self._worker_task: Optional[asyncio.Task] = None
        
        # Statistiques
        self._stats = MessageBusStats() if enable_stats else None
        
        # Verrouillage
        self._lock = asyncio.Lock()
        
        logger.info(f"MessageBus initialized: {name}")
    
    # =========================================================================
    # METHODES ABSTRAITES A IMPLEMENTER
    # =========================================================================
    
    @abstractmethod
    async def publish(self, topic: str, message: BaseMessage) -> None:
        """
        Publie un message sur un topic.
        
        Args:
            topic: Topic du message
            message: Message à publier
            
        Raises:
            ValueError: Si le topic ou le message est invalide
        """
        pass
    
    @abstractmethod
    async def subscribe(
        self,
        topic: str,
        callback: Callable[[BaseMessage], Awaitable[None]],
        subscription_type: SubscriptionType = SubscriptionType.EXACT,
        filter_criteria: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        S'abonne à un topic.
        
        Args:
            topic: Topic à écouter
            callback: Fonction de callback
            subscription_type: Type d'abonnement
            filter_criteria: Critères de filtrage
            
        Returns:
            str: ID de l'abonnement
        """
        pass
    
    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Se désabonne d'un topic.
        
        Args:
            subscription_id: ID de l'abonnement
            
        Returns:
            bool: True si désabonné avec succès
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """
        Ferme la connexion au bus.
        """
        pass
    
    # =========================================================================
    # METHODES AVANCEES
    # =========================================================================
    
    async def request_response(
        self,
        topic: str,
        message: BaseMessage,
        timeout: float = 30.0
    ) -> Optional[BaseMessage]:
        """
        Effectue une requête et attend une réponse (pattern request/response).
        
        Args:
            topic: Topic de la requête
            message: Message de requête
            timeout: Timeout en secondes
            
        Returns:
            Optional[BaseMessage]: Message de réponse ou None
        """
        # Création d'un identifiant de corrélation
        if not message.correlation_id:
            import uuid
            message.correlation_id = str(uuid.uuid4())
        
        # Création d'un événement pour la réponse
        response_event = asyncio.Event()
        response_message = None
        
        # Callback de réponse
        async def response_callback(msg: BaseMessage):
            nonlocal response_message
            if msg.correlation_id == message.correlation_id:
                response_message = msg
                response_event.set()
        
        # Abonnement temporaire
        response_topic = f"{topic}.response"
        subscription_id = await self.subscribe(
            topic=response_topic,
            callback=response_callback,
            filter_criteria={"correlation_id": message.correlation_id}
        )
        
        try:
            # Publication de la requête
            await self.publish(topic, message)
            
            # Attente de la réponse avec timeout
            try:
                await asyncio.wait_for(response_event.wait(), timeout)
                return response_message
            except asyncio.TimeoutError:
                logger.warning(f"Request timed out: {message.correlation_id}")
                return None
        finally:
            # Nettoyage
            await self.unsubscribe(subscription_id)
    
    async def broadcast(self, message: BaseMessage) -> None:
        """
        Diffuse un message à tous les abonnés (broadcast).
        
        Args:
            message: Message à diffuser
        """
        # Utilise le topic spécial 'broadcast'
        await self.publish("broadcast", message)
    
    async def send_to_agent(
        self,
        agent_id: str,
        message: BaseMessage
    ) -> None:
        """
        Envoie un message à un agent spécifique.
        
        Args:
            agent_id: ID de l'agent destinataire
            message: Message à envoyer
        """
        # Utilise le topic 'agent.{agent_id}'
        topic = f"agent.{agent_id}"
        await self.publish(topic, message)
    
    async def get_subscription_info(self, subscription_id: str) -> Optional[Dict]:
        """
        Récupère les informations d'un abonnement.
        
        Args:
            subscription_id: ID de l'abonnement
            
        Returns:
            Optional[Dict]: Informations de l'abonnement
        """
        async with self._lock:
            sub = self._subscriptions.get(subscription_id)
            if not sub:
                return None
            
            return {
                "id": sub.id,
                "topic": sub.topic,
                "subscription_type": sub.subscription_type.value,
                "filter_criteria": sub.filter_criteria,
                "created_at": sub.created_at.isoformat(),
                "active": sub.active,
                "message_count": sub.message_count,
                "last_message_at": sub.last_message_at.isoformat() if sub.last_message_at else None
            }
    
    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """
        Récupère les statistiques du bus.
        
        Returns:
            Optional[Dict]: Statistiques du bus
        """
        if not self._stats:
            return None
        
        return {
            "name": self.name,
            "total_published": self._stats.total_published,
            "total_delivered": self._stats.total_delivered,
            "total_errors": self._stats.total_errors,
            "total_subscriptions": self._stats.total_subscriptions,
            "topics_count": self._stats.topics_count,
            "active_subscribers": self._stats.active_subscribers,
            "last_activity": self._stats.last_activity.isoformat() if self._stats.last_activity else None,
            "by_type": self._stats.by_type,
            "by_priority": self._stats.by_priority,
            "by_status": self._stats.by_status
        }
    
    async def clear_stats(self) -> None:
        """
        Réinitialise les statistiques.
        """
        if self._stats:
            self._stats = MessageBusStats()
            logger.info("Stats cleared")
    
    # =========================================================================
    # GESTION DU CYCLE DE VIE
    # =========================================================================
    
    async def start(self) -> None:
        """
        Démarre le bus de messages.
        """
        if self._is_running:
            logger.warning("MessageBus already running")
            return
        
        self._message_queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._is_running = True
        
        # Démarrage du worker
        self._worker_task = asyncio.create_task(self._process_messages())
        
        logger.info(f"MessageBus {self.name} started")
    
    async def stop(self) -> None:
        """
        Arrête le bus de messages.
        """
        if not self._is_running:
            logger.warning("MessageBus already stopped")
            return
        
        self._is_running = False
        
        # Attente de la fin du worker
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        
        # Fermeture de la connexion
        await self.close()
        
        logger.info(f"MessageBus {self.name} stopped")
    
    async def _process_messages(self) -> None:
        """
        Traite les messages en file d'attente.
        """
        while self._is_running:
            try:
                # Récupération du message
                message = await self._message_queue.get()
                
                # Traitement du message
                await self._deliver_message(message)
                
                # Marquage comme traité
                self._message_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                if self._stats:
                    self._stats.total_errors += 1
    
    async def _deliver_message(self, message: BaseMessage) -> None:
        """
        Délivre un message à ses abonnés.
        
        Args:
            message: Message à délivrer
        """
        # Filtrage des abonnements correspondants
        matched_subs = []
        
        for sub_id, sub in self._subscriptions.items():
            if not sub.active:
                continue
            
            if sub.matches(message.type.value):
                # Vérification des filtres
                if sub.filter_criteria:
                    if not self._matches_filter(message, sub.filter_criteria):
                        continue
                matched_subs.append(sub)
        
        # Livraison du message
        for sub in matched_subs:
            try:
                await sub.callback(message)
                sub.message_count += 1
                sub.last_message_at = datetime.utcnow()
                
                if self._stats:
                    self._stats.total_delivered += 1
                    
            except Exception as e:
                logger.error(f"Error delivering message to {sub.id}: {str(e)}")
                if self._stats:
                    self._stats.total_errors += 1
    
    def _matches_filter(self, message: BaseMessage, filter_criteria: Dict) -> bool:
        """
        Vérifie si un message correspond aux critères de filtrage.
        
        Args:
            message: Message à vérifier
            filter_criteria: Critères de filtrage
            
        Returns:
            bool: True si le message correspond
        """
        for key, value in filter_criteria.items():
            if hasattr(message, key):
                if getattr(message, key) != value:
                    return False
            elif key == "type" and message.type.value != value:
                return False
            elif key == "priority" and message.priority != value:
                return False
            elif key in message.metadata:
                if message.metadata[key] != value:
                    return False
        return True
    
    # =========================================================================
    # UTILITAIRES
    # =========================================================================
    
    def _generate_subscription_id(self) -> str:
        """
        Génère un ID d'abonnement unique.
        
        Returns:
            str: ID d'abonnement
        """
        self._subscription_counter += 1
        return f"sub_{self._subscription_counter}_{id(self)}"
    
    def _update_stats(self, message: BaseMessage) -> None:
        """
        Met à jour les statistiques.
        
        Args:
            message: Message publié
        """
        if not self._stats:
            return
        
        self._stats.total_published += 1
        self._stats.last_activity = datetime.utcnow()
        
        # Par type
        type_key = message.type.value
        self._stats.by_type[type_key] = self._stats.by_type.get(type_key, 0) + 1
        
        # Par priorité
        priority_key = f"p{message.priority}"
        self._stats.by_priority[priority_key] = self._stats.by_priority.get(priority_key, 0) + 1
        
        # Par statut
        status_key = message.status.value
        self._stats.by_status[status_key] = self._stats.by_status.get(status_key, 0) + 1
        
        # Mise à jour des topics
        self._stats.topics_count = len(set(
            sub.topic for sub in self._subscriptions.values()
        ))
        self._stats.active_subscribers = len([
            sub for sub in self._subscriptions.values() if sub.active
        ])
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    
    def _validate_message(self, message: BaseMessage) -> None:
        """
        Valide un message avant publication.
        
        Args:
            message: Message à valider
            
        Raises:
            ValueError: Si le message est invalide
        """
        if not isinstance(message, BaseMessage):
            raise ValueError("Message must be a BaseMessage instance")
        
        if not message.sender:
            raise ValueError("Message must have a sender")
        
        if not message.type:
            raise ValueError("Message must have a type")
    
    def _validate_topic(self, topic: str) -> None:
        """
        Valide un topic.
        
        Args:
            topic: Topic à valider
            
        Raises:
            ValueError: Si le topic est invalide
        """
        if not topic or len(topic.strip()) == 0:
            raise ValueError("Topic cannot be empty")
        
        # Vérification des caractères valides
        import re
        if not re.match(r'^[a-zA-Z0-9._\-*]+$', topic):
            raise ValueError(f"Invalid topic: {topic}")
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        subs_count = len(self._subscriptions)
        return f"<MessageBus(name='{self.name}', subscriptions={subs_count}, running={self._is_running})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le bus en dictionnaire.
        
        Returns:
            Dict: Représentation du bus
        """
        return {
            "name": self.name,
            "running": self._is_running,
            "subscriptions_count": len(self._subscriptions),
            "queue_size": self._message_queue.qsize() if self._message_queue else 0,
            "max_queue_size": self.max_queue_size,
            "retry_attempts": self.retry_attempts,
            "retry_delay": self.retry_delay,
            "stats": self._stats
        }