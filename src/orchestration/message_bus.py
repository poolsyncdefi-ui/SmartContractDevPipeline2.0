# src/orchestration/message_bus.py
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from src.communication.message_models import BaseMessage

class MessageBus(ABC):
    """Interface abstraite pour le bus de messages."""
    
    @abstractmethod
    async def publish_event(self, channel: str, data: Dict[str, Any]) -> None:
        """Publie un événement sur un canal."""
        pass
    
    @abstractmethod
    async def subscribe(self, channel: str, callback: Callable) -> None:
        """S'abonne à un canal."""
        pass
    
    @abstractmethod
    async def unsubscribe(self, channel: str, callback: Callable) -> None:
        """Se désabonne d'un canal."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Ferme la connexion."""
        pass