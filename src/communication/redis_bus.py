# src/communication/redis_bus.py

"""
Redis implementation of the message bus.
F25 – src/communication/redis_bus.py

Rôle Fonctionnel : Implementation Redis Pub/Sub pour le routage des messages.
Cette classe implemente l'interface MessageBus en utilisant Redis comme
transport pour la communication inter-agents. Elle supporte:
- La publication de messages sur des topics
- L'abonnement a des topics avec callback
- Les patterns d'abonnement (wildcards)
- La reconnexion automatique
- La gestion des erreurs et des timeouts
- Les métriques de performance
- Le support des messages TTL

Redis est utilise pour sa performance et sa simplicite d'utilisation
dans les architectures de microservices.
"""
import redis.asyncio as aioredis
import json
import asyncio
import inspect
from typing import Callable, Awaitable, Dict, List, Optional, Set, Any
from datetime import datetime
import logging
import re

# Import des modules du pipeline
from src.communication.message_bus import (
    MessageBus,
    SubscriptionType,
    Subscription
)
from src.communication.message_models import BaseMessage
from src.core.exceptions import CommunicationError

# Tentative d'import des settings avec fallback
try:
    from src.config.settings import settings
except ImportError:
    # Fallback pour les tests
    class _Settings:
        redis_url = "redis://localhost:6379/0"
    settings = _Settings()

# Configuration du logging
logger = logging.getLogger(__name__)


class RedisMessageBus(MessageBus):
    """
    Implementation Redis du bus de messages.

    Cette classe utilise Redis Pub/Sub pour la communication inter-agents.
    Elle supporte les topics, les patterns, les filtres et les métriques.

    Attributes:
        redis_url (str): URL de connexion Redis
        _pub (Optional[aioredis.Redis]): Client Redis pour la publication
        _sub (Optional[aioredis.Redis]): Client Redis pour la souscription
        _pubsub (Optional[aioredis.PubSub]): Objet PubSub pour l'écoute
        _channel_subscriptions (Dict[str, Set[str]]): IDs d'abonnements par canal exact
        _pattern_subscriptions (Dict[str, Set[str]]): IDs d'abonnements par pattern
        _listen_task (Optional[asyncio.Task]): Tâche d'écoute en arrière-plan
        _is_connected (bool): Indique si la connexion est établie
        _reconnect_attempts (int): Nombre de tentatives de reconnexion
        _max_reconnect_attempts (int): Nombre maximum de tentatives
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
        **kwargs
    ):
        """
        Initialise le bus Redis.

        Args:
            redis_url: URL de connexion Redis (utilise settings.redis_url par defaut)
            max_reconnect_attempts: Nombre maximum de tentatives de reconnexion
            reconnect_delay: Délai entre les tentatives de reconnexion (secondes)
            **kwargs: Arguments supplémentaires pour MessageBus
        """
        super().__init__(**kwargs)

        self.redis_url = redis_url or getattr(settings, 'redis_url', "redis://localhost:6379/0")
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self._reconnect_attempts = 0

        # Clients Redis
        self._pub: Optional[aioredis.Redis] = None
        self._sub: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.PubSub] = None

        # Index pour le routage Redis (mappings topic/pattern -> set de subscription_id)
        # self._subscriptions (hérité de MessageBus) gère la table principale des objets Subscription
        self._channel_subscriptions: Dict[str, Set[str]] = {}
        self._pattern_subscriptions: Dict[str, Set[str]] = {}

        # Tâche d'écoute
        self._listen_task: Optional[asyncio.Task] = None
        self._is_connected = False
        self._should_run = False

        # Statistiques Redis
        self._redis_stats = {
            "messages_published": 0,
            "messages_received": 0,
            "errors": 0,
            "reconnections": 0,
            "last_activity": None
        }

        logger.info(f"RedisMessageBus initialized with URL: {self.redis_url[:20]}...")

    # =========================================================================
    # CONNEXION
    # =========================================================================

    async def connect(self) -> None:
        """
        Établit la connexion Redis.

        Raises:
            CommunicationError: Si la connexion échoue
        """
        if self._is_connected:
            logger.debug("Redis already connected")
            return

        try:
            # Client pour la publication
            self._pub = await aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=10,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True
            )

            # Client pour la souscription
            self._sub = await aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=10,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True
            )

            # Test de connexion
            await self._pub.ping()
            await self._sub.ping()

            self._is_connected = True
            self._reconnect_attempts = 0
            self._should_run = True

            # Création du PubSub
            self._pubsub = self._sub.pubsub()

            logger.info("Redis connected successfully")

        except Exception as e:
            self._is_connected = False
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise CommunicationError(f"Failed to connect to Redis: {e}")

    async def disconnect(self) -> None:
        """
        Ferme la connexion Redis.
        """
        self._should_run = False

        # Annulation de la tâche d'écoute
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # Fermeture du PubSub
        if self._pubsub:
            try:
                await self._pubsub.close()
            except Exception as e:
                logger.warning(f"Error closing pubsub: {str(e)}")
            self._pubsub = None

        # Fermeture des clients
        if self._pub:
            try:
                await self._pub.close()
            except Exception as e:
                logger.warning(f"Error closing pub client: {str(e)}")
            self._pub = None

        if self._sub:
            try:
                await self._sub.close()
            except Exception as e:
                logger.warning(f"Error closing sub client: {str(e)}")
            self._sub = None

        self._is_connected = False
        logger.info("Redis disconnected")

    async def _ensure_connected(self) -> None:
        """
        S'assure que la connexion est établie, avec tentatives de reconnexion.

        Raises:
            CommunicationError: Si la connexion échoue après plusieurs tentatives
        """
        if self._is_connected:
            return

        attempts = 0
        while attempts < self.max_reconnect_attempts:
            try:
                await self.connect()
                return
            except CommunicationError as e:
                attempts += 1
                if attempts >= self.max_reconnect_attempts:
                    raise CommunicationError(f"Failed to reconnect after {attempts} attempts: {e}")
                logger.warning(f"Reconnect attempt {attempts}/{self.max_reconnect_attempts} failed, retrying in {self.reconnect_delay}s")
                await asyncio.sleep(self.reconnect_delay * attempts)

    # =========================================================================
    # PUBLICATION
    # =========================================================================

    async def publish(self, topic: str, message: BaseMessage) -> None:
        """
        Publie un message sur Redis.

        Args:
            topic: Topic du message
            message: Message à publier

        Raises:
            CommunicationError: Si la publication échoue
        """
        self._validate_topic(topic)
        self._validate_message(message)

        try:
            # Assurer la connexion
            await self._ensure_connected()

            # Sérialisation du message
            serialized = message.model_dump_json()

            # Publication avec TTL si spécifié
            if message.ttl:
                await self._pub.publish(topic, serialized)
                await self._pub.setex(
                    f"msg:{message.id}",
                    message.ttl,
                    "1"
                )
            else:
                await self._pub.publish(topic, serialized)

            # Mise à jour des statistiques
            self._update_stats(message)
            self._redis_stats["messages_published"] += 1
            self._redis_stats["last_activity"] = datetime.utcnow()

            logger.debug(f"Message published: {message.type.value} on {topic}")

        except Exception as e:
            self._redis_stats["errors"] += 1
            logger.error(f"Failed to publish message: {str(e)}")
            raise CommunicationError(f"Failed to publish message: {e}")

    # =========================================================================
    # SOUSCRIPTION
    # =========================================================================

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[BaseMessage], Any],
        subscription_type: SubscriptionType = SubscriptionType.EXACT,
        filter_criteria: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        S'abonne à un topic sur Redis.

        Args:
            topic: Topic à écouter
            callback: Fonction de callback
            subscription_type: Type d'abonnement
            filter_criteria: Critères de filtrage

        Returns:
            str: ID de l'abonnement

        Raises:
            CommunicationError: Si l'abonnement échoue
        """
        self._validate_topic(topic)

        try:
            # Assurer la connexion
            await self._ensure_connected()

            async with self._lock:
                # Génération de l'ID
                sub_id = self._generate_subscription_id()

                # Création de l'abonnement
                subscription = Subscription(
                    id=sub_id,
                    topic=topic,
                    callback=callback,
                    subscription_type=subscription_type,
                    filter_criteria=filter_criteria
                )

                # Stockage dans la table principale self._subscriptions (héritée de MessageBus)
                self._subscriptions[sub_id] = subscription

                if subscription_type == SubscriptionType.PATTERN:
                    if topic not in self._pattern_subscriptions:
                        self._pattern_subscriptions[topic] = set()
                        await self._pubsub.psubscribe(topic)
                    self._pattern_subscriptions[topic].add(sub_id)
                else:
                    if topic not in self._channel_subscriptions:
                        self._channel_subscriptions[topic] = set()
                        await self._pubsub.subscribe(topic)
                    self._channel_subscriptions[topic].add(sub_id)

                # Mise à jour des statistiques
                if self._stats:
                    self._stats.total_subscriptions = len(self._subscriptions)
                    self._stats.topics_count = len(set(s.topic for s in self._subscriptions.values()))
                    self._stats.active_subscribers = len([s for s in self._subscriptions.values() if s.active])

            # Démarrer l'écoute si pas déjà en cours
            if not self._listen_task or self._listen_task.done():
                self._listen_task = asyncio.create_task(self._listen())

            logger.info(f"Subscribed to {topic} (type={subscription_type.value}, id={sub_id})")
            return sub_id

        except Exception as e:
            logger.error(f"Failed to subscribe: {str(e)}")
            raise CommunicationError(f"Failed to subscribe: {e}")

    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Se désabonne d'un topic.

        Args:
            subscription_id: ID de l'abonnement

        Returns:
            bool: True si désabonné avec succès
        """
        try:
            async with self._lock:
                subscription = self._subscriptions.get(subscription_id)
                if not subscription:
                    logger.warning(f"Subscription {subscription_id} not found")
                    return False

                topic = subscription.topic
                sub_type = subscription.subscription_type

                if sub_type == SubscriptionType.PATTERN:
                    if topic in self._pattern_subscriptions:
                        self._pattern_subscriptions[topic].discard(subscription_id)
                        if not self._pattern_subscriptions[topic]:
                            await self._pubsub.punsubscribe(topic)
                            del self._pattern_subscriptions[topic]
                else:
                    if topic in self._channel_subscriptions:
                        self._channel_subscriptions[topic].discard(subscription_id)
                        if not self._channel_subscriptions[topic]:
                            await self._pubsub.unsubscribe(topic)
                            del self._channel_subscriptions[topic]

                del self._subscriptions[subscription_id]

                if self._stats:
                    self._stats.total_subscriptions = len(self._subscriptions)
                    self._stats.topics_count = len(set(s.topic for s in self._subscriptions.values()))
                    self._stats.active_subscribers = len([s for s in self._subscriptions.values() if s.active])

                logger.info(f"Unsubscribed: {subscription_id} from {topic}")
                return True

        except Exception as e:
            logger.error(f"Failed to unsubscribe: {str(e)}")
            return False

    # =========================================================================
    # ECOUTE DES MESSAGES
    # =========================================================================

    async def _listen(self) -> None:
        """
        Écoute les messages Redis en arrière-plan.
        """
        if not self._pubsub:
            logger.error("PubSub not initialized")
            return

        while self._should_run and self._is_connected:
            try:
                message = await self._pubsub.get_message(
                    timeout=1.0,
                    ignore_subscribe_messages=True
                )

                if message is None:
                    continue

                await self._handle_redis_message(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._redis_stats["errors"] += 1
                logger.error(f"Error in listen loop: {str(e)}")

                if self._should_run:
                    try:
                        await self._reconnect()
                    except CommunicationError:
                        logger.error("Failed to reconnect, stopping listen loop")
                        break

    async def _handle_redis_message(self, message: Dict[str, Any]) -> None:
        """
        Traite un message Redis reçu.

        Args:
            message: Message Redis
        """
        try:
            channel = message.get('channel')
            data = message.get('data')

            if not channel or not data:
                return

            try:
                msg = BaseMessage.model_validate_json(data)
            except Exception as e:
                logger.error(f"Failed to deserialize message: {str(e)}")
                return

            self._redis_stats["messages_received"] += 1
            self._redis_stats["last_activity"] = datetime.utcnow()

            if msg.is_expired():
                logger.debug(f"Message {msg.id} expired, skipping")
                return

            await self._deliver_to_subscribers(channel, msg)

        except Exception as e:
            self._redis_stats["errors"] += 1
            logger.error(f"Error handling Redis message: {str(e)}")

    async def _deliver_to_subscribers(
        self,
        channel: str,
        message: BaseMessage
    ) -> None:
        """
        Délivre un message à ses abonnés en respectant le filtrage et l'état.

        Args:
            channel: Channel Redis
            message: Message à délivrer
        """
        matched_sub_ids = set()

        if channel in self._channel_subscriptions:
            matched_sub_ids.update(self._channel_subscriptions[channel])

        for pattern, sub_ids in self._pattern_subscriptions.items():
            if self._matches_pattern(channel, pattern):
                matched_sub_ids.update(sub_ids)

        for sub_id in matched_sub_ids:
            sub = self._subscriptions.get(sub_id)
            if not sub or not sub.active:
                continue

            if sub.filter_criteria:
                if not self._matches_filter(message, sub.filter_criteria):
                    continue

            try:
                callback = sub.callback
                if inspect.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    res = callback(message)
                    if asyncio.isfuture(res) or inspect.isawaitable(res):
                        await res

                sub.message_count += 1
                sub.last_message_at = datetime.utcnow()

                if self._stats:
                    self._stats.total_delivered += 1

            except Exception as e:
                logger.error(f"Error delivering message to subscription {sub.id}: {str(e)}")
                if self._stats:
                    self._stats.total_errors += 1

    def _matches_pattern(self, channel: str, pattern: str) -> bool:
        """
        Vérifie si un channel correspond à un pattern Redis.

        Args:
            channel: Channel Redis
            pattern: Pattern Redis

        Returns:
            bool: True si correspond
        """
        regex = pattern.replace('*', '.*').replace('?', '.')
        return re.match(regex, channel) is not None

    # =========================================================================
    # RECONNEXION
    # =========================================================================

    async def _reconnect(self) -> None:
        """
        Tente de reconnecter Redis et de relancer l'écoute.

        Raises:
            CommunicationError: Si la reconnexion échoue
        """
        self._reconnect_attempts += 1
        self._redis_stats["reconnections"] += 1

        logger.info(f"Attempting to reconnect (attempt {self._reconnect_attempts})")

        try:
            await self.disconnect()
            await asyncio.sleep(self.reconnect_delay * self._reconnect_attempts)
            await self.connect()
            await self._resubscribe_all()

            if not self._listen_task or self._listen_task.done():
                self._listen_task = asyncio.create_task(self._listen())

            logger.info("Reconnection successful")

        except Exception as e:
            if self._reconnect_attempts >= self.max_reconnect_attempts:
                raise CommunicationError(f"Failed to reconnect: {e}")
            raise

    async def _resubscribe_all(self) -> None:
        """
        Réabonne aux topics existants après reconnexion.
        """
        for sub_id, sub in self._subscriptions.items():
            try:
                if sub.subscription_type == SubscriptionType.PATTERN:
                    await self._pubsub.psubscribe(sub.topic)
                else:
                    await self._pubsub.subscribe(sub.topic)
            except Exception as e:
                logger.warning(f"Failed to resubscribe to {sub.topic}: {str(e)}")

    # =========================================================================
    # GESTION DU CYCLE DE VIE
    # =========================================================================

    async def start(self) -> None:
        """
        Démarre le bus Redis.
        """
        await super().start()
        await self.connect()
        self._listen_task = asyncio.create_task(self._listen())
        logger.info("RedisMessageBus started")

    async def close(self) -> None:
        """
        Ferme les connexions Redis.
        """
        self._should_run = False

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        await self.disconnect()
        await super().close()
        logger.info("RedisMessageBus closed")

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """
        Vérifie la santé du bus Redis.

        Returns:
            Dict: Informations de santé
        """
        status = {
            "connected": self._is_connected,
            "url": self.redis_url[:20] + "...",
            "listening": self._listen_task is not None and not self._listen_task.done(),
            "subscriptions": len(self._subscriptions),
            "stats": self._redis_stats.copy()
        }

        if self._is_connected:
            try:
                await self._pub.ping()
                status["ping"] = "ok"
            except Exception as e:
                status["ping"] = f"error: {str(e)}"
                status["connected"] = False

        return status

    # =========================================================================
    # STATISTIQUES
    # =========================================================================

    async def get_redis_stats(self) -> Dict[str, Any]:
        """
        Récupère les statistiques Redis.

        Returns:
            Dict: Statistiques Redis
        """
        pub_status = False
        sub_status = False
        if self._pub:
            try:
                await self._pub.ping()
                pub_status = True
            except Exception:
                pass
        if self._sub:
            try:
                await self._sub.ping()
                sub_status = True
            except Exception:
                pass

        stats = self._redis_stats.copy()
        stats["connections"] = {
            "pub": pub_status,
            "sub": sub_status
        }
        stats["subscription_count"] = len(self._subscriptions)
        stats["listen_task_running"] = self._listen_task is not None and not self._listen_task.done()

        return stats

    # =========================================================================
    # REPRESENTATION
    # =========================================================================

    def __repr__(self) -> str:
        return f"<RedisMessageBus(connected={self._is_connected}, subscriptions={len(self._subscriptions)}, url={self.redis_url[:20]}...)>"

    def to_dict(self) -> Dict:
        """
        Convertit le bus en dictionnaire.

        Returns:
            Dict: Représentation du bus
        """
        return {
            "type": "redis",
            "url": self.redis_url[:20] + "...",
            "connected": self._is_connected,
            "subscriptions": len(self._subscriptions),
            "exact_topics": len(self._channel_subscriptions),
            "pattern_topics": len(self._pattern_subscriptions),
            "stats": self._redis_stats,
            "reconnect_attempts": self._reconnect_attempts,
            **super().to_dict()
        }