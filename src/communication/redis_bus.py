# src/communication/redis_bus.py
import redis.asyncio as aioredis
import json
from typing import Callable, Awaitable, Dict, List
from src.communication.message_bus import MessageBus
from src.communication.message_models import BaseMessage
from src.config.settings import settings
from src.core.exceptions import CommunicationError

class RedisMessageBus(MessageBus):
    """Implémentation Redis du bus de messages."""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or settings.redis_url
        self._pub = None
        self._sub = None
        self._subscribers: Dict[str, List[Callable]] = {}

    async def connect(self) -> None:
        """Établit la connexion Redis."""
        try:
            self._pub = await aioredis.from_url(self.redis_url, decode_responses=True)
            self._sub = await aioredis.from_url(self.redis_url, decode_responses=True)
        except Exception as e:
            raise CommunicationError(f"Failed to connect to Redis: {e}")

    async def publish(self, topic: str, message: BaseMessage) -> None:
        """Publie un message sur Redis."""
        if not self._pub:
            await self.connect()
        await self._pub.publish(topic, message.model_dump_json())

    async def subscribe(self, topic: str, callback: Callable[[BaseMessage], Awaitable[None]]) -> None:
        """S'abonne à un topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)
        if not hasattr(self, '_listen_task') or self._listen_task.done():
            self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        """Écoute les messages Redis en arrière-plan."""
        if not self._sub:
            await self.connect()
        async with self._sub.pubsub() as pubsub:
            await pubsub.subscribe(*self._subscribers.keys())
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    msg = BaseMessage(**data)
                    for cb in self._subscribers.get(message['channel'], []):
                        await cb(msg)

    async def unsubscribe(self, topic: str, callback: Callable[[BaseMessage], Awaitable[None]]) -> None:
        """Se désabonne d'un topic."""
        if topic in self._subscribers and callback in self._subscribers[topic]:
            self._subscribers[topic].remove(callback)

    async def close(self) -> None:
        """Ferme les connexions Redis."""
        if self._pub:
            await self._pub.close()
        if self._sub:
            await self._sub.close()