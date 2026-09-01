# src/communication/message_models.py
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

class MessageType(str, Enum):
    TASK = "task"
    RESULT = "result"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    STATUS = "status"

class BaseMessage(BaseModel):
    """Message de base pour la communication inter-agents."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    sender: str
    recipient: Optional[str] = None  # None = broadcast
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None
    priority: int = Field(0, ge=0, le=10)  # 0=bas, 10=élevé

class TaskMessage(BaseMessage):
    """Message de tâche."""
    type: MessageType = MessageType.TASK
    payload: Dict[str, Any]  # contient task_id, action, parameters, context

class ResultMessage(BaseMessage):
    """Message de résultat."""
    type: MessageType = MessageType.RESULT
    payload: Dict[str, Any]  # contient status, result, logs

class ErrorMessage(BaseMessage):
    """Message d'erreur."""
    type: MessageType = MessageType.ERROR
    payload: Dict[str, Any]  # contient code, message, details