# src/communication/message_bus.py
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from src.communication.message_models import BaseMessage

class MessageBus(ABC):
    """Interface abstraite pour le bus de messages."""
    
    @abstractmethod
    async def publish(self, topic: str, message: BaseMessage) -> None:
        """Publie un message sur un topic."""
        pass

    @abstractmethod
    async def subscribe(self, topic: str, callback: Callable[[BaseMessage], Awaitable[None]]) -> None:
        """S'abonne à un topic."""
        pass

    @abstractmethod
    async def unsubscribe(self, topic: str, callback: Callable[[BaseMessage], Awaitable[None]]) -> None:
        """Se désabonne d'un topic."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Ferme la connexion."""
        pass