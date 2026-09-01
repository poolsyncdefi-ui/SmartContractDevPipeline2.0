# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Base de Données
# ==============================================================================
# Fichier: src/db/database.py
# Description: Gestionnaire de base de données PostgreSQL asynchrone avec SQLAlchemy.
#              Fournit les connexions, sessions et utilitaires.
# ==============================================================================

from typing import AsyncGenerator, Optional, Dict, Any
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import event, inspect
from src.config.settings import settings
from src.core.exceptions import DatabaseConnectionError, StorageError
import logging
import time

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# BASE DE MODÈLES
# ==============================================================================

Base = declarative_base()


# ==============================================================================
# MOTEUR DE BASE DE DONNÉES
# ==============================================================================

def create_engine() -> AsyncEngine:
    """
    Crée le moteur de base de données asynchrone.
    
    Returns:
        AsyncEngine: Moteur SQLAlchemy configuré
    
    Raises:
        DatabaseConnectionError: Si la connexion échoue
    """
    try:
        engine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=30,
        )
        logger.info(f"✅ Moteur de base de données créé: {settings.database_url}")
        return engine
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création du moteur de base de données: {e}")
        raise DatabaseConnectionError(
            url=settings.database_url,
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
        logger.debug("📊 Session de base de données créée")
        yield session
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création de la session: {e}")
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
        logger.debug("📊 Session de base de données créée (context manager)")
        yield session
    except Exception as e:
        logger.error(f"❌ Erreur lors de la session context manager: {e}")
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
        return AsyncSessionLocal()
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'obtention de la session: {e}")
        raise StorageError(
            message=f"Failed to get database session: {e}",
            operation="get_session_direct"
        )


# ==============================================================================
# FONCTIONS DE CONNEXION
# ==============================================================================

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


async def check_db_connection() -> bool:
    """
    Vérifie si la connexion à la base de données est fonctionnelle.
    
    Returns:
        bool: True si la connexion est fonctionnelle, False sinon
    """
    try:
        async with get_async_session() as session:
            # Exécute une requête simple pour vérifier la connexion
            result = await session.execute("SELECT 1")
            await session.commit()
            logger.debug("✅ Vérification de la connexion à la base de données réussie")
            return True
    except Exception as e:
        logger.error(f"❌ Échec de la vérification de la connexion: {e}")
        return False


async def get_db_version() -> Optional[str]:
    """
    Obtient la version de PostgreSQL.
    
    Returns:
        Optional[str]: Version de PostgreSQL ou None en cas d'erreur
    """
    try:
        async with get_async_session() as session:
            result = await session.execute("SELECT version()")
            version = result.scalar()
            logger.debug(f"📊 Version PostgreSQL: {version}")
            return version
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération de la version: {e}")
        return None


# ==============================================================================
# FONCTIONS DE TRANSACTION
# ==============================================================================

async def execute_in_transaction(func, *args, **kwargs) -> Any:
    """
    Exécute une fonction dans une transaction de base de données.
    
    Args:
        func: Fonction asynchrone à exécuter
        *args: Arguments de la fonction
        **kwargs: Arguments nommés de la fonction
        
    Returns:
        Any: Résultat de la fonction
    """
    async with get_async_session() as session:
        try:
            result = await func(session, *args, **kwargs)
            await session.commit()
            logger.debug("✅ Transaction validée avec succès")
            return result
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur dans la transaction, rollback effectué: {e}")
            raise StorageError(
                message=f"Transaction failed: {e}",
                operation="transaction"
            )


async def execute_raw_sql(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Exécute du SQL brut et retourne les résultats.
    
    Args:
        sql: Requête SQL
        params: Paramètres de la requête
        
    Returns:
        List[Dict[str, Any]]: Résultats sous forme de dictionnaires
    """
    async with get_async_session() as session:
        try:
            result = await session.execute(sql, params or {})
            # Convertir les résultats en dictionnaires
            rows = result.fetchall()
            if rows:
                columns = result.keys()
                return [dict(zip(columns, row)) for row in rows]
            return []
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'exécution du SQL brut: {e}")
            raise StorageError(
                message=f"Raw SQL execution failed: {e}",
                operation="raw_sql"
            )


# ==============================================================================
# ÉVÉNEMENTS DE BASE DE DONNÉES
# ==============================================================================

@event.listens_for(engine.sync_engine, "before_execute")
def before_execute(conn, clause, multiparams, params):
    """
    Écouteur d'événement avant l'exécution d'une requête.
    Utile pour le logging.
    """
    if settings.database_echo:
        logger.debug(f"🔍 Requête SQL: {clause}")
        if params:
            logger.debug(f"📋 Paramètres: {params}")


@event.listens_for(engine.sync_engine, "after_execute")
def after_execute(conn, clause, multiparams, params, result):
    """
    Écouteur d'événement après l'exécution d'une requête.
    Utile pour les statistiques.
    """
    if settings.database_echo and result:
        logger.debug(f"📊 Résultats: {result.rowcount} ligne(s) retournée(s)")


# ==============================================================================
# FONCTIONS D'INITIALISATION
# ==============================================================================

async def init_database(create_tables: bool = True) -> None:
    """
    Initialise la base de données.
    
    Args:
        create_tables: Si True, crée les tables automatiquement
    """
    try:
        # Vérifier la connexion
        if not await check_db_connection():
            raise DatabaseConnectionError(
                url=settings.database_url,
                message="Could not connect to database"
            )
        
        logger.info("✅ Connexion à la base de données établie")
        
        # Créer les tables si demandé
        if create_tables:
            from src.db.migrations import init_models
            await init_models()
            logger.info("✅ Tables créées avec succès")
        
        # Récupérer la version
        version = await get_db_version()
        if version:
            logger.info(f"📊 PostgreSQL version: {version}")
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de la base de données: {e}")
        raise


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
                result = await session.execute("SELECT current_database()")
                db_name = result.scalar()
                print(f"✅ Base de données: {db_name}")
                
                result = await session.execute("SELECT current_user")
                user = result.scalar()
                print(f"✅ Utilisateur: {user}")
        except Exception as e:
            print(f"❌ Erreur: {e}")
        
        print("\n✅ Tests terminés.")
    
    # Exécuter les tests
    asyncio.run(test_database())