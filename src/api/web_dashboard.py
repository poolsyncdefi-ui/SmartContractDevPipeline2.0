# src/api/web_dashboard.py
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from src.api.routers import projects, tasks
from src.api.websockets.notifier import ConnectionManager
from src.db.migrations import init_models
import asyncio
from datetime import datetime

app = FastAPI(
    title="Smart Contract Dev Pipeline 2.0",
    version="2.0.0",
    description="Pipeline de développement de smart contracts avec agents IA"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Routes
app.include_router(projects.router)
app.include_router(tasks.router)

# WebSocket
manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    """Initialise les ressources au démarrage."""
    await init_models()
    asyncio.create_task(background_loop())

@app.on_event("shutdown")
async def shutdown_event():
    """Nettoie les ressources à l'arrêt."""
    await close_db_connection()

async def background_loop():
    """Boucle de fond pour les notifications."""
    while True:
        await asyncio.sleep(5)
        await manager.broadcast_status({
            "event": "heartbeat",
            "timestamp": datetime.utcnow().isoformat()
        })

@app.get("/health")
async def health_check():
    """Vérifie l'état de santé de l'API."""
    return {"status": "healthy", "version": "2.0.0"}

@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint WebSocket pour les événements en temps réel."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except Exception:
        await manager.disconnect(websocket)