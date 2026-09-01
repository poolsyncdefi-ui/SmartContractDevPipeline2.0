# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - WebSocket Notifier
# ==============================================================================
# Fichier: src/api/websockets/notifier.py
# Description: Gestionnaire WebSocket pour les notifications en temps réel.
#              Diffusion des événements du pipeline.
#              Support des groupes, des filtres, de la persistance et des métriques.
# ==============================================================================

from fastapi import WebSocket, WebSocketDisconnect, APIRouter, HTTPException, status
from typing import Dict, Set, List, Optional, Any, Callable, Awaitable
from datetime import datetime, timedelta
import json
import logging
import asyncio
import uuid
from enum import Enum
from dataclasses import dataclass, field

from src.core.models import EventType

# ==============================================================================
# CONFIGURATION
# ==============================================================================

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


# ==============================================================================
# ENUMS
# ==============================================================================

class MessageType(str, Enum):
    """Types de messages WebSocket."""
    CONNECTION = "connection"
    SUBSCRIPTION = "subscription"
    EVENT = "event"
    NOTIFICATION = "notification"
    TASK_UPDATE = "task_update"
    PROJECT_UPDATE = "project_update"
    SECURITY_ALERT = "security_alert"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"
    STATUS = "status"


class ConnectionStatus(str, Enum):
    """Statuts de connexion."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class ClientInfo:
    """Informations sur un client connecté."""
    client_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    status: ConnectionStatus = ConnectionStatus.CONNECTED
    metadata: Dict[str, Any] = field(default_factory=dict)
    groups: Set[str] = field(default_factory=set)
    topics: Set[str] = field(default_factory=set)
    message_count: int = 0
    ping_count: int = 0
    pong_count: int = 0


@dataclass
class Message:
    """Message à envoyer."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.NOTIFICATION
    payload: Dict[str, Any] = field(default_factory=dict)
    topic: Optional[str] = None
    group: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl: Optional[int] = None  # Durée de vie en secondes
    persistent: bool = False


# ==============================================================================
# GESTIONNAIRE DE CONNEXIONS
# ==============================================================================

class ConnectionManager:
    """
    Gestionnaire des connexions WebSocket.
    Gère les connexions, les abonnements, les groupes et la diffusion des messages.
    """
    
    def __init__(self, max_connections: int = 1000, ping_interval: int = 30, timeout: int = 120):
        """
        Initialise le gestionnaire de connexions.
        
        Args:
            max_connections: Nombre maximum de connexions simultanées
            ping_interval: Intervalle de ping en secondes
            timeout: Timeout d'inactivité en secondes
        """
        self._clients: Dict[str, ClientInfo] = {}
        self._groups: Dict[str, Set[str]] = {}  # group_name -> {client_ids}
        self._topics: Dict[str, Set[str]] = {}  # topic -> {client_ids}
        self._pending_messages: List[Message] = []
        self._message_history: List[Message] = []
        self._max_connections = max_connections
        self._ping_interval = ping_interval
        self._timeout = timeout
        self._ping_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
        
        # Statistiques
        self._stats = {
            "total_connections": 0,
            "total_disconnections": 0,
            "total_messages_sent": 0,
            "total_messages_received": 0,
            "total_errors": 0,
            "peak_connections": 0,
            "started_at": datetime.utcnow()
        }
        
        logger.info(f"ConnectionManager initialized: max_connections={max_connections}")
    
    # ==========================================================================
    # GESTION DES CONNEXIONS
    # ==========================================================================
    
    async def connect(self, websocket: WebSocket, client_id: str, metadata: Optional[Dict] = None) -> ClientInfo:
        """
        Accepte une nouvelle connexion WebSocket.
        
        Args:
            websocket: Instance WebSocket
            client_id: ID unique du client
            metadata: Métadonnées du client (optionnel)
            
        Returns:
            ClientInfo: Informations du client
            
        Raises:
            HTTPException: Si le nombre maximum de connexions est atteint
        """
        # Vérifier la limite de connexions
        if len(self._clients) >= self._max_connections:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Maximum connections reached"
            )
        
        # Vérifier si le client existe déjà
        if client_id in self._clients:
            # Déconnecter l'ancien client
            await self.disconnect(client_id)
        
        # Accepter la connexion
        await websocket.accept()
        
        # Créer les informations du client
        client = ClientInfo(
            client_id=client_id,
            websocket=websocket,
            connected_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
            metadata=metadata or {},
            groups=set(),
            topics=set()
        )
        
        # Ajouter le client
        self._clients[client_id] = client
        
        # Mettre à jour les statistiques
        self._stats["total_connections"] += 1
        self._stats["peak_connections"] = max(
            self._stats["peak_connections"],
            len(self._clients)
        )
        
        # Démarrer les tâches de fond si nécessaire
        if not self._running:
            self._running = True
            self._ping_task = asyncio.create_task(self._ping_loop())
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info(f"WebSocket client connected: {client_id} (total: {len(self._clients)})")
        
        # Envoyer un message de bienvenue
        await self.send_to_client(client_id, {
            "type": MessageType.CONNECTION.value,
            "status": ConnectionStatus.CONNECTED.value,
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "connection_count": len(self._clients)
        })
        
        return client
    
    async def disconnect(self, client_id: str, reason: Optional[str] = None) -> None:
        """
        Déconnecte un client.
        
        Args:
            client_id: ID du client
            reason: Raison de la déconnexion (optionnel)
        """
        if client_id not in self._clients:
            return
        
        client = self._clients[client_id]
        client.status = ConnectionStatus.DISCONNECTED
        
        # Retirer des groupes
        for group in list(client.groups):
            if group in self._groups:
                self._groups[group].discard(client_id)
                if not self._groups[group]:
                    del self._groups[group]
        
        # Retirer des topics
        for topic in list(client.topics):
            if topic in self._topics:
                self._topics[topic].discard(client_id)
                if not self._topics[topic]:
                    del self._topics[topic]
        
        # Fermer le WebSocket
        try:
            if reason:
                await client.websocket.close(code=1000, reason=reason)
            else:
                await client.websocket.close()
        except Exception:
            pass
        
        # Supprimer le client
        del self._clients[client_id]
        
        self._stats["total_disconnections"] += 1
        
        logger.info(f"WebSocket client disconnected: {client_id} (remaining: {len(self._clients)})")
        
        # Arrêter les tâches de fond si plus de connexions
        if len(self._clients) == 0 and self._running:
            self._running = False
            if self._ping_task:
                self._ping_task.cancel()
                self._ping_task = None
            if self._cleanup_task:
                self._cleanup_task.cancel()
                self._cleanup_task = None
    
    # ==========================================================================
    # GROUPES ET ABONNEMENTS
    # ==========================================================================
    
    async def join_group(self, client_id: str, group: str) -> None:
        """
        Ajoute un client à un groupe.
        
        Args:
            client_id: ID du client
            group: Nom du groupe
        """
        if client_id not in self._clients:
            return
        
        client = self._clients[client_id]
        client.groups.add(group)
        
        if group not in self._groups:
            self._groups[group] = set()
        self._groups[group].add(client_id)
        
        logger.debug(f"Client {client_id} joined group: {group}")
    
    async def leave_group(self, client_id: str, group: str) -> None:
        """
        Retire un client d'un groupe.
        
        Args:
            client_id: ID du client
            group: Nom du groupe
        """
        if client_id not in self._clients:
            return
        
        client = self._clients[client_id]
        client.groups.discard(group)
        
        if group in self._groups:
            self._groups[group].discard(client_id)
            if not self._groups[group]:
                del self._groups[group]
        
        logger.debug(f"Client {client_id} left group: {group}")
    
    async def subscribe(self, client_id: str, topics: List[str]) -> None:
        """
        Abonne un client à des topics.
        
        Args:
            client_id: ID du client
            topics: Liste des topics
        """
        if client_id not in self._clients:
            return
        
        client = self._clients[client_id]
        
        for topic in topics:
            client.topics.add(topic)
            if topic not in self._topics:
                self._topics[topic] = set()
            self._topics[topic].add(client_id)
        
        logger.debug(f"Client {client_id} subscribed to: {topics}")
        
        await self.send_to_client(client_id, {
            "type": MessageType.SUBSCRIPTION.value,
            "status": "subscribed",
            "topics": topics,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def unsubscribe(self, client_id: str, topics: Optional[List[str]] = None) -> None:
        """
        Désabonne un client de topics.
        
        Args:
            client_id: ID du client
            topics: Liste des topics (si None, désabonne de tous)
        """
        if client_id not in self._clients:
            return
        
        client = self._clients[client_id]
        
        if topics is None:
            topics_to_remove = list(client.topics)
        else:
            topics_to_remove = topics
        
        for topic in topics_to_remove:
            client.topics.discard(topic)
            if topic in self._topics:
                self._topics[topic].discard(client_id)
                if not self._topics[topic]:
                    del self._topics[topic]
        
        logger.debug(f"Client {client_id} unsubscribed from: {topics or 'all'}")
        
        await self.send_to_client(client_id, {
            "type": MessageType.SUBSCRIPTION.value,
            "status": "unsubscribed",
            "topics": topics or ["all"],
            "timestamp": datetime.utcnow().isoformat()
        })
    
    # ==========================================================================
    # ENVOI DE MESSAGES
    # ==========================================================================
    
    async def broadcast(self, message: Dict[str, Any], topic: Optional[str] = None, group: Optional[str] = None) -> None:
        """
        Diffuse un message à tous les clients abonnés au topic ou au groupe.
        
        Args:
            message: Message à diffuser
            topic: Topic du message (optionnel)
            group: Groupe du message (optionnel)
        """
        # Ajouter les métadonnées
        message["timestamp"] = datetime.utcnow().isoformat()
        
        # Déterminer les destinataires
        recipients = set()
        
        if topic:
            # Envoyer aux clients abonnés au topic
            if topic in self._topics:
                recipients.update(self._topics[topic])
        
        if group:
            # Envoyer aux clients du groupe
            if group in self._groups:
                recipients.update(self._groups[group])
        
        if not topic and not group:
            # Envoyer à tous les clients
            recipients.update(self._clients.keys())
        
        # Envoyer le message
        for client_id in recipients:
            if client_id in self._clients:
                await self.send_to_client(client_id, message)
        
        # Statistiques
        self._stats["total_messages_sent"] += len(recipients)
        
        logger.debug(f"Broadcast to {len(recipients)} clients (topic: {topic}, group: {group})")
    
    async def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        """
        Envoie un message à un client spécifique.
        
        Args:
            client_id: ID du client
            message: Message à envoyer
            
        Returns:
            bool: True si envoyé avec succès
        """
        if client_id not in self._clients:
            return False
        
        client = self._clients[client_id]
        
        try:
            await client.websocket.send_json(message)
            client.message_count += 1
            client.last_activity = datetime.utcnow()
            self._stats["total_messages_sent"] += 1
            return True
        except Exception as e:
            logger.error(f"Error sending message to client {client_id}: {str(e)}")
            self._stats["total_errors"] += 1
            await self.disconnect(client_id, str(e))
            return False
    
    async def send_to_group(self, group: str, message: Dict[str, Any]) -> int:
        """
        Envoie un message à tous les membres d'un groupe.
        
        Args:
            group: Nom du groupe
            message: Message à envoyer
            
        Returns:
            int: Nombre de destinataires
        """
        if group not in self._groups:
            return 0
        
        recipients = self._groups[group]
        success_count = 0
        
        for client_id in recipients:
            if client_id in self._clients:
                if await self.send_to_client(client_id, message):
                    success_count += 1
        
        return success_count
    
    # ==========================================================================
    # MÉTHODES UTILITAIRES
    # ==========================================================================
    
    async def send_event(self, event_type: str, data: Dict[str, Any], topic: Optional[str] = None) -> None:
        """
        Envoie un événement système.
        
        Args:
            event_type: Type d'événement
            data: Données de l'événement
            topic: Topic optionnel
        """
        message = {
            "type": MessageType.EVENT.value,
            "event": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(message, topic)
    
    async def send_notification(self, title: str, message: str, level: str = "info", topic: Optional[str] = None) -> None:
        """
        Envoie une notification.
        
        Args:
            title: Titre de la notification
            message: Message de la notification
            level: Niveau (info, success, warning, error, critical)
            topic: Topic optionnel
        """
        notification = {
            "type": MessageType.NOTIFICATION.value,
            "title": title,
            "message": message,
            "level": level,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(notification, topic)
    
    async def send_task_update(self, task_id: str, state: str, data: Optional[Dict] = None) -> None:
        """
        Envoie une mise à jour de tâche.
        
        Args:
            task_id: ID de la tâche
            state: Nouvel état
            data: Données supplémentaires
        """
        message = {
            "type": MessageType.TASK_UPDATE.value,
            "task_id": task_id,
            "state": state,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(message, f"task.{task_id}")
        await self.broadcast(message, "tasks")
    
    async def send_project_update(self, project_id: str, status: str, data: Optional[Dict] = None) -> None:
        """
        Envoie une mise à jour de projet.
        
        Args:
            project_id: ID du projet
            status: Nouveau statut
            data: Données supplémentaires
        """
        message = {
            "type": MessageType.PROJECT_UPDATE.value,
            "project_id": project_id,
            "status": status,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(message, f"project.{project_id}")
        await self.broadcast(message, "projects")
    
    async def send_security_alert(self, severity: str, title: str, description: str, data: Optional[Dict] = None) -> None:
        """
        Envoie une alerte de sécurité.
        
        Args:
            severity: Niveau de sévérité (critical, high, medium, low)
            title: Titre de l'alerte
            description: Description de l'alerte
            data: Données supplémentaires
        """
        message = {
            "type": MessageType.SECURITY_ALERT.value,
            "severity": severity,
            "title": title,
            "description": description,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(message, "security")
    
    # ==========================================================================
    # BOUCLES DE FOND
    # ==========================================================================
    
    async def _ping_loop(self) -> None:
        """
        Boucle de ping pour maintenir les connexions actives.
        """
        while self._running:
            await asyncio.sleep(self._ping_interval)
            
            if not self._running:
                break
            
            now = datetime.utcnow()
            
            for client_id, client in list(self._clients.items()):
                try:
                    # Envoyer un ping
                    await client.websocket.send_json({
                        "type": MessageType.PING.value,
                        "timestamp": now.isoformat()
                    })
                    client.ping_count += 1
                    client.last_activity = now
                except Exception:
                    # Erreur de ping => déconnecter
                    await self.disconnect(client_id, "Ping failed")
    
    async def _cleanup_loop(self) -> None:
        """
        Boucle de nettoyage pour les connexions inactives.
        """
        while self._running:
            await asyncio.sleep(60)  # Nettoyer toutes les minutes
            
            if not self._running:
                break
            
            now = datetime.utcnow()
            timeout = timedelta(seconds=self._timeout)
            
            for client_id, client in list(self._clients.items()):
                if now - client.last_activity > timeout:
                    logger.warning(f"Client {client_id} timed out (inactive for {self._timeout}s)")
                    await self.disconnect(client_id, "Inactivity timeout")
    
    # ==========================================================================
    # STATISTIQUES
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du gestionnaire.
        
        Returns:
            Dict: Statistiques
        """
        uptime = (datetime.utcnow() - self._stats["started_at"]).total_seconds()
        
        return {
            **self._stats,
            "active_connections": len(self._clients),
            "total_groups": len(self._groups),
            "total_topics": len(self._topics),
            "uptime_seconds": uptime,
            "clients": {
                client_id: {
                    "connected_at": client.connected_at.isoformat(),
                    "last_activity": client.last_activity.isoformat(),
                    "status": client.status.value,
                    "groups": list(client.groups),
                    "topics": list(client.topics),
                    "message_count": client.message_count
                }
                for client_id, client in self._clients.items()
            }
        }
    
    def get_connection_count(self) -> int:
        """Retourne le nombre de connexions actives."""
        return len(self._clients)
    
    def get_client_ids(self) -> List[str]:
        """Retourne la liste des IDs des clients connectés."""
        return list(self._clients.keys())
    
    def get_client_metadata(self, client_id: str) -> Optional[Dict]:
        """Retourne les métadonnées d'un client."""
        if client_id in self._clients:
            return self._clients[client_id].metadata
        return None
    
    def is_connected(self, client_id: str) -> bool:
        """Vérifie si un client est connecté."""
        return client_id in self._clients
    
    # ==========================================================================
    # GESTION DE LA PERSISTANCE
    # ==========================================================================
    
    async def store_message(self, message: Message) -> None:
        """
        Stocke un message pour les clients qui ne sont pas connectés.
        
        Args:
            message: Message à stocker
        """
        async with self._lock:
            self._pending_messages.append(message)
            
            # Limiter la taille de la liste
            if len(self._pending_messages) > 1000:
                self._pending_messages = self._pending_messages[-1000:]
    
    async def deliver_pending_messages(self, client_id: str) -> int:
        """
        Délivre les messages en attente à un client.
        
        Args:
            client_id: ID du client
            
        Returns:
            int: Nombre de messages délivrés
        """
        if client_id not in self._clients:
            return 0
        
        delivered = 0
        
        async with self._lock:
            for message in self._pending_messages[:]:
                if message.topic and message.topic in self._clients[client_id].topics:
                    if await self.send_to_client(client_id, message.payload):
                        self._pending_messages.remove(message)
                        delivered += 1
                elif message.group and message.group in self._clients[client_id].groups:
                    if await self.send_to_client(client_id, message.payload):
                        self._pending_messages.remove(message)
                        delivered += 1
        
        return delivered


# ==============================================================================
# INSTANCE GLOBALE
# ==============================================================================

manager = ConnectionManager(max_connections=1000, ping_interval=30, timeout=120)


# ==============================================================================
# ENDPOINT WEBSOCKET
# ==============================================================================

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Endpoint WebSocket pour les notifications en temps réel.
    """
    # Générer un ID de client
    import uuid
    client_id = f"client_{uuid.uuid4().hex[:8]}"
    
    # Métadonnées du client
    metadata = {
        "connected_at": datetime.utcnow().isoformat(),
        "client_id": client_id,
        "user_agent": websocket.headers.get("user-agent", "unknown"),
        "ip": websocket.headers.get("x-forwarded-for", websocket.client.host if websocket.client else "unknown")
    }
    
    try:
        # Accepter la connexion
        client = await manager.connect(websocket, client_id, metadata)
        
        # Délivrer les messages en attente
        await manager.deliver_pending_messages(client_id)
        
        # Boucle de réception des messages
        while True:
            try:
                data = await websocket.receive_json()
                manager._stats["total_messages_received"] += 1
                client.last_activity = datetime.utcnow()
                
                await _handle_websocket_message(client_id, data)
            except WebSocketDisconnect:
                await manager.disconnect(client_id)
                break
            except json.JSONDecodeError:
                await manager.send_to_client(client_id, {
                    "type": MessageType.ERROR.value,
                    "message": "Invalid JSON received",
                    "timestamp": datetime.utcnow().isoformat()
                })
            except Exception as e:
                logger.error(f"Error in WebSocket loop for {client_id}: {str(e)}")
                manager._stats["total_errors"] += 1
                await manager.send_to_client(client_id, {
                    "type": MessageType.ERROR.value,
                    "message": f"Internal error: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat()
                })
    
    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {str(e)}")
        await manager.disconnect(client_id, str(e))


async def _handle_websocket_message(client_id: str, data: Dict[str, Any]) -> None:
    """
    Traite un message reçu du client.
    
    Args:
        client_id: ID du client
        data: Message reçu
    """
    action = data.get("action")
    
    if action == "subscribe":
        topics = data.get("topics", [])
        await manager.subscribe(client_id, topics)
    
    elif action == "unsubscribe":
        topics = data.get("topics")
        await manager.unsubscribe(client_id, topics)
    
    elif action == "join_group":
        group = data.get("group")
        if group:
            await manager.join_group(client_id, group)
    
    elif action == "leave_group":
        group = data.get("group")
        if group:
            await manager.leave_group(client_id, group)
    
    elif action == "ping":
        await manager.send_to_client(client_id, {
            "type": MessageType.PONG.value,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    elif action == "get_status":
        await manager.send_to_client(client_id, {
            "type": MessageType.STATUS.value,
            "connections": manager.get_connection_count(),
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    elif action == "get_stats":
        if client_id in manager._clients and manager._clients[client_id].metadata.get("admin", False):
            await manager.send_to_client(client_id, {
                "type": MessageType.STATUS.value,
                "stats": manager.get_stats(),
                "timestamp": datetime.utcnow().isoformat()
            })
        else:
            await manager.send_to_client(client_id, {
                "type": MessageType.ERROR.value,
                "message": "Unauthorized",
                "timestamp": datetime.utcnow().isoformat()
            })
    
    else:
        await manager.send_to_client(client_id, {
            "type": MessageType.ERROR.value,
            "message": f"Unknown action: {action}",
            "timestamp": datetime.utcnow().isoformat()
        })