# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Migrations
# ==============================================================================
# Fichier: src/db/migrations.py
# Description: Gestion des migrations de la base de données.
#              Initialisation, mise à jour et suppression du schéma.
# ==============================================================================

from src.db.database import engine, Base
from src.core.exceptions import StorageError
from src.config.settings import settings
from sqlalchemy import inspect, text
import logging
from typing import List, Optional, Dict, Any

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# MIGRATIONS PRINCIPALES
# ==============================================================================

async def init_models() -> None:
    """
    Crée toutes les tables en base de données.
    À utiliser pour l'installation initiale.
    
    Raises:
        StorageError: Si la création des tables échoue
    """
    try:
        logger.info("📊 Création des tables de la base de données...")
        async with engine.begin() as conn:
            # Créer toutes les tables
            await conn.run_sync(Base.metadata.create_all)
        
        # Vérifier que les tables ont été créées
        async with engine.begin() as conn:
            def sync_inspect(connection):
                inspector = inspect(connection)
                tables = inspector.get_table_names()
                logger.info(f"✅ Tables créées: {tables}")
                return tables
        
        tables = await conn.run_sync(sync_inspect)
        logger.info(f"✅ {len(tables)} tables créées avec succès")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création des tables: {e}")
        raise StorageError(
            message=f"Failed to create database tables: {e}",
            operation="init_models"
        )


async def drop_models() -> None:
    """
    Supprime toutes les tables (réinitialisation complète).
    À utiliser avec précaution (perte de données).
    
    Raises:
        StorageError: Si la suppression des tables échoue
    """
    try:
        logger.warning("⚠️ Suppression de toutes les tables de la base de données...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        logger.info("✅ Tables supprimées avec succès")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la suppression des tables: {e}")
        raise StorageError(
            message=f"Failed to drop database tables: {e}",
            operation="drop_models"
        )


async def reset_models() -> None:
    """
    Réinitialise complètement la base de données (drop + create).
    Utile pour les tests ou les réinitialisations.
    """
    logger.warning("⚠️ Réinitialisation complète de la base de données...")
    await drop_models()
    await init_models()
    logger.info("✅ Base de données réinitialisée avec succès")


# ==============================================================================
# VÉRIFICATIONS DE SCHÉMA
# ==============================================================================

async def get_existing_tables() -> List[str]:
    """
    Récupère la liste des tables existantes.
    
    Returns:
        List[str]: Noms des tables existantes
    """
    try:
        async with engine.begin() as conn:
            def sync_inspect(connection):
                inspector = inspect(connection)
                return inspector.get_table_names()
            
            tables = await conn.run_sync(sync_inspect)
            return tables
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des tables: {e}")
        return []


async def table_exists(table_name: str) -> bool:
    """
    Vérifie si une table existe.
    
    Args:
        table_name: Nom de la table
        
    Returns:
        bool: True si la table existe
    """
    tables = await get_existing_tables()
    return table_name in tables


async def get_table_info(table_name: str) -> Optional[Dict[str, Any]]:
    """
    Récupère les informations d'une table (colonnes, clés, etc.).
    
    Args:
        table_name: Nom de la table
        
    Returns:
        Optional[Dict[str, Any]]: Informations de la table
    """
    try:
        async with engine.begin() as conn:
            def sync_inspect(connection):
                inspector = inspect(connection)
                columns = inspector.get_columns(table_name)
                foreign_keys = inspector.get_foreign_keys(table_name)
                indexes = inspector.get_indexes(table_name)
                primary_key = inspector.get_pk_constraint(table_name)
                
                return {
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
                    "primary_key": primary_key
                }
            
            return await conn.run_sync(sync_inspect)
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des infos de la table {table_name}: {e}")
        return None


# ==============================================================================
# UTILITAIRES DE MIGRATION
# ==============================================================================

async def execute_migration(sql: str, params: Optional[Dict[str, Any]] = None) -> None:
    """
    Exécute une requête SQL de migration.
    
    Args:
        sql: Requête SQL
        params: Paramètres de la requête
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
        logger.info(f"✅ Migration exécutée: {sql[:100]}...")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'exécution de la migration: {e}")
        raise StorageError(
            message=f"Migration execution failed: {e}",
            operation="execute_migration"
        )


async def add_column(table_name: str, column_name: str, column_type: str) -> None:
    """
    Ajoute une colonne à une table.
    
    Args:
        table_name: Nom de la table
        column_name: Nom de la colonne
        column_type: Type SQL de la colonne
    """
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
    await execute_migration(sql)


async def drop_column(table_name: str, column_name: str) -> None:
    """
    Supprime une colonne d'une table.
    
    Args:
        table_name: Nom de la table
        column_name: Nom de la colonne
    """
    sql = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
    await execute_migration(sql)


# ==============================================================================
# MIGRATIONS SPÉCIFIQUES
# ==============================================================================

async def migration_v1_to_v2() -> None:
    """
    Migration de la version 1 à la version 2 du schéma.
    Ajoute les colonnes 'updated_at' et 'metadata' aux tables principales.
    """
    logger.info("📊 Migration v1 -> v2...")
    
    # Ajouter la colonne updated_at à la table projects
    if not await table_exists("projects"):
        logger.warning("⚠️ Table 'projects' non trouvée, migration ignorée")
        return
    
    try:
        await add_column("projects", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        await add_column("sprints", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        await add_column("projects", "metadata", "JSONB DEFAULT '{}'::jsonb")
        
        logger.info("✅ Migration v1 -> v2 terminée")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la migration v1 -> v2: {e}")
        raise


async def migration_v2_to_v3() -> None:
    """
    Migration de la version 2 à la version 3 du schéma.
    Ajoute la table 'artifacts' si elle n'existe pas.
    """
    logger.info("📊 Migration v2 -> v3...")
    
    if not await table_exists("artifacts"):
        try:
            # Créer la table artifacts
            await execute_migration("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id VARCHAR PRIMARY KEY,
                    type VARCHAR NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    vector TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tags JSONB DEFAULT '[]'::jsonb,
                    source_task_id VARCHAR
                )
            """)
            logger.info("✅ Table 'artifacts' créée")
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création de la table 'artifacts': {e}")
            raise
    else:
        logger.info("✅ Table 'artifacts' déjà existante")
    
    logger.info("✅ Migration v2 -> v3 terminée")


# ==============================================================================
# EXÉCUTION DES MIGRATIONS
# ==============================================================================

async def run_migrations(version: Optional[str] = None) -> None:
    """
    Exécute toutes les migrations nécessaires.
    
    Args:
        version: Version cible (si None, exécute toutes les migrations)
    """
    logger.info(f"📊 Exécution des migrations (version cible: {version or 'latest'})...")
    
    # Vérifier l'état actuel
    existing_tables = await get_existing_tables()
    
    if not existing_tables:
        logger.info("📊 Aucune table existante, initialisation...")
        await init_models()
        return
    
    # Exécuter les migrations séquentielles
    # v1 -> v2
    if "projects" in existing_tables:
        # Vérifier si la colonne updated_at existe
        table_info = await get_table_info("projects")
        if table_info:
            columns = [col["name"] for col in table_info["columns"]]
            if "updated_at" not in columns:
                await migration_v1_to_v2()
    
    # v2 -> v3
    if "artifacts" not in existing_tables:
        await migration_v2_to_v3()
    
    logger.info("✅ Migrations terminées")


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_migrations():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Test Migrations")
        print("=" * 60)
        
        # Vérifier les tables existantes
        print("\n📊 Vérification des tables existantes...")
        tables = await get_existing_tables()
        print(f"✅ Tables trouvées: {tables if tables else 'Aucune'}")
        
        # Vérifier les informations de la table
        if "projects" in tables:
            print("\n📋 Informations de la table 'projects'...")
            info = await get_table_info("projects")
            if info:
                print(f"✅ Colonnes: {[col['name'] for col in info['columns']]}")
                print(f"✅ Clés primaires: {info['primary_key']['constrained_columns']}")
        
        # Exécuter les migrations
        print("\n📊 Exécution des migrations...")
        await run_migrations()
        print("✅ Migrations terminées")
        
        print("\n✅ Tests terminés.")
    
    # Exécuter les tests
    asyncio.run(test_migrations())