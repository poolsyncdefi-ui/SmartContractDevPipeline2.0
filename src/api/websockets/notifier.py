# src/api/websockets/notifier.py
from fastapi import WebSocket
from typing import List
import asyncio

class ConnectionManager:
    """Gestionnaire de connexions WebSocket."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accepte une connexion WebSocket."""
        await websocket.accept()
        self.active_connections.append(websocket)

    async def broadcast_status(self, message: dict) -> None:
        """Diffuse un message à tous les clients connectés."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

    async def disconnect(self, websocket: WebSocket) -> None:
        """Retire une connexion."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)