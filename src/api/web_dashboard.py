# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Web Dashboard
# ==============================================================================
# Fichier: src/api/web_dashboard.py
# Description: Serveur FastAPI principal avec routes, WebSockets et documentation.
#              Point d'entrée de l'API REST.
#              Support des middlewares, CORS, rate limiting et monitoring.
# ==============================================================================

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import time
import uvicorn
from typing import Dict, Any
from datetime import datetime

from src.config.settings import settings
from src.api.routers import projects, tasks
from src.api.websockets import notifier
from src.db.database import check_db_connection, close_db_connection
from src.core.exceptions import PipelineError
from src.core.models import PipelineStatus
from src.llm.ollama_client import OllamaClient
from src.persistence.knowledge_base import KnowledgeBase

# ==============================================================================
# CONFIGURATION DU LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# MIDDLEWARE
# ==============================================================================

class RequestLoggingMiddleware:
    """
    Middleware de logging des requêtes avec métriques.
    """
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Logging
        logger.info(
            f"{request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Duration: {duration:.3f}s - "
            f"Client: {request.client.host if request.client else 'unknown'}"
        )
        
        # Ajout des headers de performance
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        
        return response


class RateLimitMiddleware:
    """
    Middleware de rate limiting simple.
    """
    def __init__(self, app, requests_per_minute: int = 60):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self._clients: Dict[str, list] = {}
    
    async def __call__(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        # Nettoyer les anciennes requêtes
        if client_ip in self._clients:
            self._clients[client_ip] = [
                t for t in self._clients[client_ip]
                if now - t < 60
            ]
        else:
            self._clients[client_ip] = []
        
        # Vérifier la limite
        if len(self._clients[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }
            )
        
        # Ajouter la requête
        self._clients[client_ip].append(now)
        
        return await call_next(request)


# ==============================================================================
# LIFECYCLE
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestionnaire de cycle de vie de l'application.
    """
    # Démarrage
    logger.info("🚀 Starting Smart Contract Dev Pipeline API...")
    start_time = time.time()
    
    # Vérifier la connexion à la base de données
    try:
        db_ok = await check_db_connection()
        if db_ok:
            logger.info("✅ Database connection OK")
        else:
            logger.warning("⚠️ Database connection failed")
    except Exception as e:
        logger.error(f"❌ Database connection error: {e}")
    
    # Initialiser les composants
    try:
        # Client Ollama
        if not settings.llm.use_mock:
            ollama_client = OllamaClient()
            if await ollama_client.health_check():
                logger.info("✅ Ollama client OK")
            else:
                logger.warning("⚠️ Ollama client not available")
        
        # Knowledge Base
        kb = KnowledgeBase()
        logger.info("✅ Knowledge Base initialized")
        
    except Exception as e:
        logger.error(f"❌ Component initialization error: {e}")
    
    logger.info(f"🚀 API started in {time.time() - start_time:.2f}s")
    
    yield
    
    # Arrêt
    logger.info("🛑 Shutting down Smart Contract Dev Pipeline API...")
    
    # Fermer les connexions
    try:
        await close_db_connection()
        logger.info("✅ Database connection closed")
    except Exception as e:
        logger.error(f"❌ Error closing database: {e}")
    
    # Fermer le notifier WebSocket
    try:
        await notifier.manager._cleanup()
        logger.info("✅ WebSocket notifier closed")
    except Exception as e:
        logger.error(f"❌ Error closing WebSocket notifier: {e}")
    
    logger.info("✅ Shutdown complete")


# ==============================================================================
# APPLICATION PRINCIPALE
# ==============================================================================

app = FastAPI(
    title="Smart Contract Dev Pipeline API",
    description="API for the Smart Contract Development Pipeline\n\n"
                "Features:\n"
                "- 🚀 Project and task management\n"
                "- 🔒 Security auditing and formal verification\n"
                "- 🔄 Real-time WebSocket notifications\n"
                "- 🤖 LLM integration for code generation\n"
                "- 📊 Metrics and monitoring",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)


# ==============================================================================
# MIDDLEWARES
# ==============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=settings.api.cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trusted Host (production only)
if settings.is_production():
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[settings.api.host, "localhost", "127.0.0.1"]
    )

# GZip Compression
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000
)

# Request Logging
app.add_middleware(RequestLoggingMiddleware)

# Rate Limiting
if settings.security.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.security.rate_limit_requests
    )


# ==============================================================================
# ROUTES DE BASE
# ==============================================================================

@app.get("/", include_in_schema=False)
async def root():
    """Redirection vers la documentation."""
    return RedirectResponse(url="/api/docs")


@app.get("/api/health", response_model=Dict[str, Any])
async def health_check():
    """
    Vérification de santé de l'API.
    """
    start_time = time.time()
    
    # Vérifier la base de données
    db_ok = await check_db_connection()
    
    # Vérifier Redis (si configuré)
    redis_ok = True
    try:
        import redis.asyncio as aioredis
        redis_client = await aioredis.from_url(settings.redis.url)
        await redis_client.ping()
        await redis_client.close()
    except Exception:
        redis_ok = False
    
    # Vérifier Ollama
    ollama_ok = True
    try:
        if not settings.llm.use_mock:
            ollama = OllamaClient()
            ollama_ok = await ollama.health_check()
    except Exception:
        ollama_ok = False
    
    # Vérifier ChromaDB
    chroma_ok = True
    try:
        from chromadb import HttpClient
        client = HttpClient(host=settings.chroma.host, port=settings.chroma.port)
        client.heartbeat()
    except Exception:
        chroma_ok = False
    
    return {
        "status": "healthy" if db_ok else "degraded",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": time.time() - 0,  # TODO: Uptime réel
        "components": {
            "database": "connected" if db_ok else "disconnected",
            "redis": "connected" if redis_ok else "disconnected",
            "ollama": "connected" if ollama_ok else "disconnected",
            "chromadb": "connected" if chroma_ok else "disconnected"
        },
        "connections": {
            "websocket": notifier.manager.get_connection_count()
        },
        "response_time": time.time() - start_time
    }


@app.get("/api/status", response_model=PipelineStatus)
async def get_pipeline_status():
    """
    Statut global du pipeline.
    """
    from src.db.database import get_async_db
    from sqlalchemy import select, func
    from src.models.project import ProjectModel
    from src.models.task import TaskModel, TaskState
    
    try:
        async with get_async_db() as session:
            # Nombre de projets
            project_count = await session.execute(
                select(func.count()).select_from(ProjectModel)
            )
            total_projects = project_count.scalar() or 0
            
            # Nombre de tâches
            task_count = await session.execute(
                select(func.count()).select_from(TaskModel)
            )
            total_tasks = task_count.scalar() or 0
            
            # Tâches terminées
            completed_count = await session.execute(
                select(func.count()).select_from(TaskModel)
                .where(TaskModel.state == TaskState.SUCCESS)
            )
            completed_tasks = completed_count.scalar() or 0
            
            # Tâches échouées
            failed_count = await session.execute(
                select(func.count()).select_from(TaskModel)
                .where(TaskModel.state.in_([TaskState.FAILED, TaskState.CIRCUIT_BROKEN]))
            )
            failed_tasks = failed_count.scalar() or 0
            
            # Vérifier les composants
            db_ok = await check_db_connection()
            
            return PipelineStatus(
                status="healthy" if db_ok else "degraded",
                version="2.0.0",
                uptime_seconds=time.time() - 0,  # TODO: Uptime réel
                active_sprints=0,  # TODO: Récupérer les sprints actifs
                total_tasks=total_tasks,
                completed_tasks=completed_tasks,
                failed_tasks=failed_tasks,
                components={
                    "database": db_ok,
                    "redis": True,  # TODO: Vérifier Redis
                    "ollama": True,  # TODO: Vérifier Ollama
                    "chromadb": True  # TODO: Vérifier ChromaDB
                }
            )
    except Exception as e:
        logger.error(f"Error getting pipeline status: {e}")
        return PipelineStatus(
            status="unhealthy",
            version="2.0.0",
            uptime_seconds=time.time() - 0,
            active_sprints=0,
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            components={
                "database": False,
                "redis": False,
                "ollama": False,
                "chromadb": False
            }
        )


@app.get("/api/metrics", response_model=Dict[str, Any])
async def get_metrics():
    """
    Métriques du pipeline.
    """
    from src.db.database import get_async_db
    from sqlalchemy import select, func
    from src.models.task import TaskModel, TaskState
    
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": time.time() - 0,  # TODO: Uptime réel
        "websocket_connections": notifier.manager.get_connection_count()
    }
    
    try:
        async with get_async_db() as session:
            # Tâches par état
            for state in TaskState:
                count = await session.execute(
                    select(func.count()).select_from(TaskModel)
                    .where(TaskModel.state == state)
                )
                metrics[f"tasks_{state.value.lower()}"] = count.scalar() or 0
            
            # Durée moyenne des tâches
            avg_duration = await session.execute(
                select(func.avg(TaskModel.duration_seconds))
                .where(TaskModel.state == TaskState.SUCCESS)
            )
            metrics["avg_task_duration"] = float(avg_duration.scalar() or 0)
            
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
    
    return metrics


# ==============================================================================
# INCLUSION DES ROUTERS
# ==============================================================================

# Routers API
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])

# WebSocket
app.include_router(notifier.router, tags=["websocket"])


# ==============================================================================
# GESTION DES EXCEPTIONS
# ==============================================================================

@app.exception_handler(PipelineError)
async def pipeline_error_handler(request: Request, exc: PipelineError):
    """
    Gestionnaire d'exceptions du pipeline.
    """
    logger.error(f"Pipeline error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": getattr(exc, 'code', 'PIPELINE_ERROR'),
                "message": str(exc),
                "details": getattr(exc, 'details', None),
                "timestamp": getattr(exc, 'timestamp', datetime.utcnow().isoformat())
            }
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Gestionnaire d'exceptions HTTP.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "details": None,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Gestionnaire d'exceptions générales.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": str(exc) if settings.debug else None,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


# ==============================================================================
# LANCEMENT (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "src.api.web_dashboard:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        log_level=settings.logging.level.lower()
    )