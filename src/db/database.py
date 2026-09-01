# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Base de Données
# ==============================================================================
# Fichier: src/db/database.py
# Description: Gestionnaire de base de données PostgreSQL asynchrone avec SQLAlchemy.
#              Fournit les connexions, sessions et utilitaires.
#              Supporte les migrations, les retries, le monitoring et le cache.
# ==============================================================================

from typing import AsyncGenerator, Optional, Dict, Any, List, Callable, TypeVar, Union
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import event, inspect, text, func
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
from src.config.settings import settings
from src.core.exceptions import DatabaseConnectionError, StorageError
import logging
import time
import asyncio
from functools import wraps
from typing import TypeVar, ParamSpec

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)

# ==============================================================================
# TYPES
# ==============================================================================

T = TypeVar('T')
P = ParamSpec('P')
SessionCallback = Callable[[AsyncSession], T]


# ==============================================================================
# BASE DE MODÈLES
# ==============================================================================

Base = declarative_base()


# ==============================================================================
# MÉTRIQUES DE BASE DE DONNÉES
# ==============================================================================

class DatabaseMetrics:
    """Collecteur de métriques pour la base de données."""
    
    def __init__(self):
        self.query_count = 0
        self.query_time_total = 0.0
        self.query_time_max = 0.0
        self.error_count = 0
        self.connection_count = 0
        self.last_query_time = 0.0
        self._start_time = time.time()
    
    def record_query(self, duration: float):
        self.query_count += 1
        self.query_time_total += duration
        self.query_time_max = max(self.query_time_max, duration)
        self.last_query_time = duration
    
    def record_error(self):
        self.error_count += 1
    
    def record_connection(self):
        self.connection_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        avg_time = self.query_time_total / self.query_count if self.query_count > 0 else 0
        return {
            "query_count": self.query_count,
            "avg_query_time_ms": avg_time * 1000,
            "max_query_time_ms": self.query_time_max * 1000,
            "error_count": self.error_count,
            "connection_count": self.connection_count,
            "uptime_seconds": time.time() - self._start_time,
            "queries_per_second": self.query_count / (time.time() - self._start_time) if self.query_count > 0 else 0,
        }


# Instance globale des métriques
_db_metrics = DatabaseMetrics()


# ==============================================================================
# MOTEUR DE BASE DE DONNÉES
# ==============================================================================

def create_engine(
    database_url: Optional[str] = None,
    echo: Optional[bool] = None,
    pool_size: Optional[int] = None,
    max_overflow: Optional[int] = None,
    pool_recycle: int = 3600,
    pool_timeout: int = 30,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """
    Crée le moteur de base de données asynchrone.
    
    Args:
        database_url: URL de la base de données (utilise settings par défaut)
        echo: Activer les logs SQL (utilise settings par défaut)
        pool_size: Taille du pool (utilise settings par défaut)
        max_overflow: Nombre max de connexions overflow (utilise settings par défaut)
        pool_recycle: Temps de recyclage des connexions en secondes
        pool_timeout: Timeout d'attente pour une connexion
        pool_pre_ping: Vérifier la connexion avant utilisation
        
    Returns:
        AsyncEngine: Moteur SQLAlchemy configuré
    
    Raises:
        DatabaseConnectionError: Si la connexion échoue
    """
    url = database_url or settings.database.url
    echo = echo if echo is not None else settings.database.echo
    pool_size = pool_size if pool_size is not None else settings.database.pool_size
    max_overflow = max_overflow if max_overflow is not None else settings.database.max_overflow
    
    try:
        engine = create_async_engine(
            url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
        )
        logger.info(f"✅ Moteur de base de données créé: {url}")
        return engine
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création du moteur de base de données: {e}")
        raise DatabaseConnectionError(
            url=url,
            message=f"Failed to create database engine: {e}"
        )


# ==============================================================================
# FABRIQUE DE SESSIONS
# ==============================================================================

def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """
    Crée la fabrique de sessions asynchrones.
    
    Args:
        engine: Moteur de base de données
        
    Returns:
        async_sessionmaker: Fabrique de sessions
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# ==============================================================================
# INSTANCES GLOBALES
# ==============================================================================

# Création du moteur
engine = create_engine()

# Création de la fabrique de sessions
AsyncSessionLocal = create_session_factory(engine)


# ==============================================================================
# DÉCORATEUR DE RETRY
# ==============================================================================

def with_retry(
    max_retries: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
    exceptions: tuple = (OperationalError,)
):
    """
    Décorateur pour réessayer une opération de base de données en cas d'échec.
    
    Args:
        max_retries: Nombre maximum de tentatives
        delay: Délai initial entre les tentatives
        backoff: Facteur de backoff
        exceptions: Exceptions à capturer
        
    Returns:
        Decorator: Décorateur configuré
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"⚠️ Database operation failed (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {current_delay}s..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"❌ Database operation failed after {max_retries} retries: {e}")
                        raise
            
            raise last_exception
        return wrapper
    return decorator


# ==============================================================================
# FONCTIONS DE SESSION
# ==============================================================================

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Fournit une session de base de données asynchrone pour les endpoints FastAPI.
    
    Yields:
        AsyncSession: Session de base de données
    
    Raises:
        StorageError: Si la session ne peut pas être créée
    """
    session = None
    try:
        session = AsyncSessionLocal()
        _db_metrics.record_connection()
        logger.debug("📊 Session de base de données créée")
        yield session
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création de la session: {e}")
        _db_metrics.record_error()
        if session:
            await session.rollback()
        raise StorageError(
            message=f"Failed to create database session: {e}",
            operation="get_session"
        )
    finally:
        if session:
            await session.close()
            logger.debug("📊 Session de base de données fermée")


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager pour une session de base de données asynchrone.
    Utile pour les opérations hors API.
    
    Yields:
        AsyncSession: Session de base de données
    """
    session = None
    try:
        session = AsyncSessionLocal()
        _db_metrics.record_connection()
        logger.debug("📊 Session de base de données créée (context manager)")
        yield session
    except Exception as e:
        logger.error(f"❌ Erreur lors de la session context manager: {e}")
        _db_metrics.record_error()
        if session:
            await session.rollback()
        raise StorageError(
            message=f"Database session error: {e}",
            operation="context_session"
        )
    finally:
        if session:
            await session.close()
            logger.debug("📊 Session de base de données fermée (context manager)")


async def get_session() -> AsyncSession:
    """
    Obtient une session de base de données asynchrone.
    À utiliser avec précaution, préférer get_async_db() pour les endpoints.
    
    Returns:
        AsyncSession: Session de base de données
    """
    try:
        _db_metrics.record_connection()
        return AsyncSessionLocal()
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'obtention de la session: {e}")
        _db_metrics.record_error()
        raise StorageError(
            message=f"Failed to get database session: {e}",
            operation="get_session_direct"
        )


# ==============================================================================
# FONCTIONS DE CONNEXION AVEC RETRY
# ==============================================================================

@with_retry(max_retries=5, delay=1.0)
async def check_db_connection() -> bool:
    """
    Vérifie si la connexion à la base de données est fonctionnelle.
    
    Returns:
        bool: True si la connexion est fonctionnelle, False sinon
    """
    try:
        async with get_async_session() as session:
            # Exécute une requête simple pour vérifier la connexion
            result = await session.execute(text("SELECT 1"))
            await session.commit()
            logger.debug("✅ Vérification de la connexion à la base de données réussie")
            return True
    except Exception as e:
        logger.error(f"❌ Échec de la vérification de la connexion: {e}")
        return False


async def close_db_connection() -> None:
    """
    Ferme la connexion à la base de données.
    À appeler lors de l'arrêt de l'application.
    """
    try:
        await engine.dispose()
        logger.info("✅ Connexion à la base de données fermée")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la fermeture de la connexion: {e}")
        raise StorageError(
            message=f"Failed to close database connection: {e}",
            operation="close_connection"
        )


async def get_db_version() -> Optional[str]:
    """
    Obtient la version de PostgreSQL.
    
    Returns:
        Optional[str]: Version de PostgreSQL ou None en cas d'erreur
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
            logger.debug(f"📊 Version PostgreSQL: {version}")
            return version
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération de la version: {e}")
        return None


async def get_db_stats() -> Dict[str, Any]:
    """
    Obtient les statistiques de la base de données.
    
    Returns:
        Dict[str, Any]: Statistiques de la base de données
    """
    try:
        async with get_async_session() as session:
            # Nombre de tables
            result = await session.execute(
                text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
            )
            table_count = result.scalar()
            
            # Taille de la base de données
            result = await session.execute(
                text("SELECT pg_database_size(current_database())")
            )
            db_size = result.scalar()
            
            return {
                "table_count": table_count,
                "db_size_bytes": db_size,
                "db_size_mb": round(db_size / (1024 * 1024), 2),
                "pool_size": settings.database.pool_size,
                "max_overflow": settings.database.max_overflow,
            }
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des statistiques: {e}")
        return {}


# ==============================================================================
# FONCTIONS DE TRANSACTION
# ==============================================================================

async def execute_in_transaction(
    func: SessionCallback,
    *args,
    commit: bool = True,
    **kwargs
) -> Any:
    """
    Exécute une fonction dans une transaction de base de données.
    
    Args:
        func: Fonction asynchrone prenant une session en premier argument
        *args: Arguments de la fonction
        commit: Si True, valide la transaction
        **kwargs: Arguments nommés de la fonction
        
    Returns:
        Any: Résultat de la fonction
    """
    async with get_async_session() as session:
        try:
            result = await func(session, *args, **kwargs)
            if commit:
                await session.commit()
                logger.debug("✅ Transaction validée avec succès")
            else:
                logger.debug("ℹ️ Transaction en attente (commit=False)")
            return result
        except IntegrityError as e:
            await session.rollback()
            logger.error(f"❌ Erreur d'intégrité dans la transaction: {e}")
            raise StorageError(
                message=f"Integrity error in transaction: {e}",
                operation="transaction"
            )
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur dans la transaction, rollback effectué: {e}")
            raise StorageError(
                message=f"Transaction failed: {e}",
                operation="transaction"
            )


async def execute_raw_sql(
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    commit: bool = True
) -> List[Dict[str, Any]]:
    """
    Exécute du SQL brut et retourne les résultats.
    
    Args:
        sql: Requête SQL
        params: Paramètres de la requête
        commit: Si True, valide la transaction
        
    Returns:
        List[Dict[str, Any]]: Résultats sous forme de dictionnaires
    """
    async with get_async_session() as session:
        try:
            result = await session.execute(text(sql), params or {})
            if commit:
                await session.commit()
            
            # Convertir les résultats en dictionnaires
            if result.returns_rows:
                rows = result.fetchall()
                if rows:
                    columns = result.keys()
                    return [dict(zip(columns, row)) for row in rows]
            return []
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur lors de l'exécution du SQL brut: {e}")
            raise StorageError(
                message=f"Raw SQL execution failed: {e}",
                operation="raw_sql"
            )


async def execute_many(
    sql: str,
    params_list: List[Dict[str, Any]],
    commit: bool = True
) -> int:
    """
    Exécute une requête SQL avec de multiples paramètres.
    
    Args:
        sql: Requête SQL
        params_list: Liste des paramètres
        commit: Si True, valide la transaction
        
    Returns:
        int: Nombre de lignes affectées
    """
    async with get_async_session() as session:
        try:
            total_rows = 0
            for params in params_list:
                result = await session.execute(text(sql), params)
                total_rows += result.rowcount
            if commit:
                await session.commit()
            return total_rows
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur lors de l'exécution multiple: {e}")
            raise StorageError(
                message=f"Batch execution failed: {e}",
                operation="execute_many"
            )


# ==============================================================================
# ÉVÉNEMENTS DE BASE DE DONNÉES
# ==============================================================================

@event.listens_for(engine.sync_engine, "before_execute")
def before_execute(conn, clause, multiparams, params):
    """
    Écouteur d'événement avant l'exécution d'une requête.
    Utile pour le logging et les métriques.
    """
    # Stocker le temps de début
    conn._query_start_time = time.time()
    
    if settings.database.echo:
        logger.debug(f"🔍 Requête SQL: {clause}")
        if params:
            logger.debug(f"📋 Paramètres: {params}")


@event.listens_for(engine.sync_engine, "after_execute")
def after_execute(conn, clause, multiparams, params, result):
    """
    Écouteur d'événement après l'exécution d'une requête.
    Utile pour les statistiques.
    """
    # Calculer la durée
    if hasattr(conn, '_query_start_time'):
        duration = time.time() - conn._query_start_time
        _db_metrics.record_query(duration)
        
        if duration > 1.0:  # Alerter sur les requêtes lentes (> 1s)
            logger.warning(f"⚠️ Requête lente ({duration:.2f}s): {clause}")
    
    if settings.database.echo and result:
        logger.debug(f"📊 Résultats: {result.rowcount} ligne(s) retournée(s)")


@event.listens_for(engine.sync_engine, "engine_connect")
def engine_connect(conn, branch):
    """Écouteur d'événement de connexion."""
    _db_metrics.record_connection()
    logger.debug("🔗 Nouvelle connexion à la base de données")


# ==============================================================================
# FONCTIONS D'INITIALISATION
# ==============================================================================

async def init_database(
    create_tables: bool = True,
    run_migrations: bool = False,
    seed_data: bool = False
) -> None:
    """
    Initialise la base de données.
    
    Args:
        create_tables: Si True, crée les tables automatiquement
        run_migrations: Si True, exécute les migrations Alembic
        seed_data: Si True, charge les données initiales
        
    Raises:
        DatabaseConnectionError: Si la connexion échoue
    """
    try:
        # Vérifier la connexion avec retry
        if not await check_db_connection():
            raise DatabaseConnectionError(
                url=settings.database.url,
                message="Could not connect to database after multiple attempts"
            )
        
        logger.info("✅ Connexion à la base de données établie")
        
        # Créer les tables si demandé
        if create_tables:
            from src.db.migrations import init_models
            await init_models()
            logger.info("✅ Tables créées avec succès")
        
        # Exécuter les migrations Alembic
        if run_migrations:
            from src.db.migrations import run_migrations
            await run_migrations()
            logger.info("✅ Migrations exécutées avec succès")
        
        # Charger les données initiales
        if seed_data:
            await seed_initial_data()
            logger.info("✅ Données initiales chargées")
        
        # Récupérer les statistiques
        stats = await get_db_stats()
        if stats:
            logger.info(f"📊 Statistiques: {stats['table_count']} tables, {stats['db_size_mb']} MB")
        
        # Récupérer la version
        version = await get_db_version()
        if version:
            logger.info(f"📊 PostgreSQL version: {version}")
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de la base de données: {e}")
        raise


async def seed_initial_data() -> None:
    """
    Charge les données initiales dans la base de données.
    """
    try:
        from src.db.seeds import seed_all
        await seed_all()
    except ImportError:
        logger.info("ℹ️ Aucune donnée initiale à charger (seed module not found)")
    except Exception as e:
        logger.error(f"❌ Erreur lors du chargement des données initiales: {e}")
        raise


# ==============================================================================
# FONCTIONS DE MAINTENANCE
# ==============================================================================

async def vacuum_database() -> None:
    """
    Exécute VACUUM sur la base de données.
    """
    try:
        async with get_async_session() as session:
            await session.execute(text("VACUUM ANALYZE"))
            await session.commit()
            logger.info("✅ VACUUM exécuté avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'exécution de VACUUM: {e}")
        raise StorageError(
            message=f"VACUUM failed: {e}",
            operation="vacuum"
        )


async def analyze_database() -> None:
    """
    Exécute ANALYZE sur la base de données.
    """
    try:
        async with get_async_session() as session:
            await session.execute(text("ANALYZE"))
            await session.commit()
            logger.info("✅ ANALYZE exécuté avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'exécution de ANALYZE: {e}")
        raise StorageError(
            message=f"ANALYZE failed: {e}",
            operation="analyze"
        )


# ==============================================================================
# FONCTIONS DE MONITORING
# ==============================================================================

def get_db_metrics() -> Dict[str, Any]:
    """
    Retourne les métriques de la base de données.
    
    Returns:
        Dict[str, Any]: Métriques collectées
    """
    return _db_metrics.get_stats()


def reset_db_metrics() -> None:
    """
    Réinitialise les métriques de la base de données.
    """
    global _db_metrics
    _db_metrics = DatabaseMetrics()
    logger.info("🔄 Métriques de base de données réinitialisées")


async def get_connection_pool_status() -> Dict[str, Any]:
    """
    Retourne le statut du pool de connexions.
    
    Returns:
        Dict[str, Any]: Statut du pool
    """
    pool = engine.pool
    return {
        "size": pool.size(),
        "checked_in": pool.checkedin(),
        "overflow": pool.overflow(),
        "total": pool.total(),
    }


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_database():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Test Base de Données")
        print("=" * 60)
        
        # Test de connexion
        print("\n🔍 Test de connexion...")
        is_connected = await check_db_connection()
        if is_connected:
            print("✅ Connexion réussie")
        else:
            print("❌ Échec de la connexion")
            return
        
        # Test de version
        print("\n📊 Test de version...")
        version = await get_db_version()
        if version:
            print(f"✅ PostgreSQL version: {version}")
        
        # Test de session
        print("\n📋 Test de session...")
        try:
            async with get_async_session() as session:
                # Exécuter une requête simple
                result = await session.execute(text("SELECT current_database()"))
                db_name = result.scalar()
                print(f"✅ Base de données: {db_name}")
                
                result = await session.execute(text("SELECT current_user"))
                user = result.scalar()
                print(f"✅ Utilisateur: {user}")
        except Exception as e:
            print(f"❌ Erreur: {e}")
        
        # Test des métriques
        print("\n📊 Métriques...")
        metrics = get_db_metrics()
        print(f"✅ Requêtes: {metrics['query_count']}")
        print(f"✅ Temps moyen: {metrics['avg_query_time_ms']:.2f}ms")
        print(f"✅ Erreurs: {metrics['error_count']}")
        
        # Test du pool
        print("\n🔗 Pool...")
        pool_status = await get_connection_pool_status()
        print(f"✅ Pool size: {pool_status['size']}")
        print(f"✅ Connections checked in: {pool_status['checked_in']}")
        
        print("\n✅ Tests terminés.")
    
    # Exécuter les tests
    asyncio.run(test_database())