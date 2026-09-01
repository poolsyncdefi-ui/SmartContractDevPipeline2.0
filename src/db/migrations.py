# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Migrations
# ==============================================================================
# Fichier: src/db/migrations.py
# Description: Gestion des migrations de la base de données.
#              Initialisation, mise à jour et suppression du schéma.
#              Supporte Alembic, le versioning, les rollbacks et les tests.
# ==============================================================================

from src.db.database import engine, Base
from src.core.exceptions import StorageError
from src.config.settings import settings
from sqlalchemy import inspect, text, MetaData, Table
from sqlalchemy.exc import SQLAlchemyError
import logging
from typing import List, Optional, Dict, Any, Set, Tuple
from datetime import datetime
import asyncio

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# CONSTANTES
# ==============================================================================

VERSION_TABLE = "alembic_version"
MIGRATION_HISTORY_TABLE = "migration_history"


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
            
            # Créer la table d'historique des migrations
            await _create_migration_history_table(conn)
        
        # Vérifier que les tables ont été créées
        tables = await get_existing_tables()
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
# TABLE DE VERSION
# ==============================================================================

async def _create_migration_history_table(conn) -> None:
    """
    Crée la table d'historique des migrations.
    
    Args:
        conn: Connexion SQLAlchemy
    """
    try:
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_HISTORY_TABLE} (
                id SERIAL PRIMARY KEY,
                version VARCHAR(50) NOT NULL,
                description VARCHAR(255),
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_by VARCHAR(100),
                success BOOLEAN DEFAULT TRUE,
                migration_script TEXT,
                rollback_script TEXT
            )
        """))
        await conn.commit()
        logger.debug(f"✅ Table {MIGRATION_HISTORY_TABLE} créée/vérifiée")
    except Exception as e:
        logger.warning(f"⚠️ Erreur lors de la création de {MIGRATION_HISTORY_TABLE}: {e}")


async def get_current_version() -> Optional[str]:
    """
    Récupère la version actuelle de la base de données.
    
    Returns:
        Optional[str]: Version actuelle ou None
    """
    try:
        async with engine.begin() as conn:
            # Vérifier si la table alembic_version existe
            result = await conn.execute(text(
                f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{VERSION_TABLE}')"
            ))
            exists = result.scalar()
            
            if exists:
                result = await conn.execute(text(f"SELECT version_num FROM {VERSION_TABLE} LIMIT 1"))
                version = result.scalar()
                return version
            
            # Vérifier si la table migration_history existe
            result = await conn.execute(text(
                f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{MIGRATION_HISTORY_TABLE}')"
            ))
            exists = result.scalar()
            
            if exists:
                result = await conn.execute(text(
                    f"SELECT version FROM {MIGRATION_HISTORY_TABLE} ORDER BY applied_at DESC LIMIT 1"
                ))
                version = result.scalar()
                return version
            
            return None
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération de la version: {e}")
        return None


async def set_current_version(version: str, description: str = "", applied_by: str = "system") -> None:
    """
    Définit la version actuelle de la base de données.
    
    Args:
        version: Version à définir
        description: Description de la migration
        applied_by: Qui a appliqué la migration
    """
    try:
        async with engine.begin() as conn:
            # Créer la table d'historique si elle n'existe pas
            await _create_migration_history_table(conn)
            
            # Insérer l'historique
            await conn.execute(text(f"""
                INSERT INTO {MIGRATION_HISTORY_TABLE} (version, description, applied_by)
                VALUES (:version, :description, :applied_by)
            """), {
                "version": version,
                "description": description,
                "applied_by": applied_by
            })
            await conn.commit()
            
            # Mettre à jour la table alembic_version si elle existe
            result = await conn.execute(text(
                f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{VERSION_TABLE}')"
            ))
            if result.scalar():
                await conn.execute(text(
                    f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:version) "
                    f"ON CONFLICT (version_num) DO UPDATE SET version_num = :version"
                ), {"version": version})
                await conn.commit()
            
            logger.info(f"✅ Version définie: {version}")
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la définition de la version: {e}")
        raise StorageError(
            message=f"Failed to set version: {e}",
            operation="set_version"
        )


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


async def column_exists(table_name: str, column_name: str) -> bool:
    """
    Vérifie si une colonne existe dans une table.
    
    Args:
        table_name: Nom de la table
        column_name: Nom de la colonne
        
    Returns:
        bool: True si la colonne existe
    """
    table_info = await get_table_info(table_name)
    if not table_info:
        return False
    return any(col["name"] == column_name for col in table_info["columns"])


async def index_exists(table_name: str, index_name: str) -> bool:
    """
    Vérifie si un index existe sur une table.
    
    Args:
        table_name: Nom de la table
        index_name: Nom de l'index
        
    Returns:
        bool: True si l'index existe
    """
    table_info = await get_table_info(table_name)
    if not table_info:
        return False
    return any(idx["name"] == index_name for idx in table_info["indexes"])


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
            await conn.commit()
        logger.info(f"✅ Migration exécutée: {sql[:100]}...")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'exécution de la migration: {e}")
        raise StorageError(
            message=f"Migration execution failed: {e}",
            operation="execute_migration"
        )


async def execute_migration_script(script_path: str) -> None:
    """
    Exécute un script de migration depuis un fichier.
    
    Args:
        script_path: Chemin du script SQL
    """
    try:
        with open(script_path, 'r') as f:
            sql = f.read()
        
        # Split par instruction
        statements = sql.split(';')
        async with engine.begin() as conn:
            for stmt in statements:
                if stmt.strip():
                    await conn.execute(text(stmt))
            await conn.commit()
        
        logger.info(f"✅ Script de migration exécuté: {script_path}")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'exécution du script: {e}")
        raise StorageError(
            message=f"Migration script failed: {e}",
            operation="execute_migration_script"
        )


async def add_column(table_name: str, column_name: str, column_type: str, nullable: bool = True) -> None:
    """
    Ajoute une colonne à une table.
    
    Args:
        table_name: Nom de la table
        column_name: Nom de la colonne
        column_type: Type SQL de la colonne
        nullable: Si la colonne peut être NULL
    """
    if await column_exists(table_name, column_name):
        logger.info(f"ℹ️ Colonne {column_name} existe déjà dans {table_name}")
        return
    
    null_str = "" if nullable else "NOT NULL"
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {null_str}"
    await execute_migration(sql)


async def drop_column(table_name: str, column_name: str) -> None:
    """
    Supprime une colonne d'une table.
    
    Args:
        table_name: Nom de la table
        column_name: Nom de la colonne
    """
    if not await column_exists(table_name, column_name):
        logger.info(f"ℹ️ Colonne {column_name} n'existe pas dans {table_name}")
        return
    
    sql = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
    await execute_migration(sql)


async def rename_column(table_name: str, old_name: str, new_name: str) -> None:
    """
    Renomme une colonne.
    
    Args:
        table_name: Nom de la table
        old_name: Ancien nom
        new_name: Nouveau nom
    """
    if not await column_exists(table_name, old_name):
        logger.info(f"ℹ️ Colonne {old_name} n'existe pas dans {table_name}")
        return
    
    if await column_exists(table_name, new_name):
        logger.info(f"ℹ️ Colonne {new_name} existe déjà dans {table_name}")
        return
    
    sql = f"ALTER TABLE {table_name} RENAME COLUMN {old_name} TO {new_name}"
    await execute_migration(sql)


async def add_index(table_name: str, index_name: str, columns: List[str]) -> None:
    """
    Ajoute un index sur une table.
    
    Args:
        table_name: Nom de la table
        index_name: Nom de l'index
        columns: Colonnes à indexer
    """
    if await index_exists(table_name, index_name):
        logger.info(f"ℹ️ Index {index_name} existe déjà")
        return
    
    col_str = ", ".join(columns)
    sql = f"CREATE INDEX {index_name} ON {table_name} ({col_str})"
    await execute_migration(sql)


async def drop_index(table_name: str, index_name: str) -> None:
    """
    Supprime un index.
    
    Args:
        table_name: Nom de la table
        index_name: Nom de l'index
    """
    if not await index_exists(table_name, index_name):
        logger.info(f"ℹ️ Index {index_name} n'existe pas")
        return
    
    sql = f"DROP INDEX {index_name}"
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
    
    # Ajouter les colonnes aux tables
    tables = ["projects", "sprints", "task_results"]
    for table in tables:
        if await table_exists(table):
            await add_column(table, "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            await add_column(table, "metadata", "JSONB DEFAULT '{}'::jsonb")
    
    # Ajouter la colonne priority à sprints
    if await table_exists("sprints"):
        await add_column("sprints", "priority", "INTEGER DEFAULT 5")
    
    # Ajouter la colonne tags à projects
    if await table_exists("projects"):
        await add_column("projects", "tags", "JSONB DEFAULT '[]'::jsonb")
    
    await set_current_version("2.0.0", "Migration v1 -> v2")
    logger.info("✅ Migration v1 -> v2 terminée")


async def migration_v2_to_v3() -> None:
    """
    Migration de la version 2 à la version 3 du schéma.
    Ajoute la table 'artifacts' avec ses index.
    """
    logger.info("📊 Migration v2 -> v3...")
    
    # Créer la table artifacts
    if not await table_exists("artifacts"):
        await execute_migration("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id VARCHAR PRIMARY KEY,
                type VARCHAR NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB DEFAULT '{}'::jsonb,
                vector TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tags JSONB DEFAULT '[]'::jsonb,
                source_task_id VARCHAR,
                version VARCHAR DEFAULT '1.0.0'
            )
        """)
        logger.info("✅ Table 'artifacts' créée")
    
    # Ajouter les index
    await add_index("artifacts", "idx_artifacts_type", ["type"])
    await add_index("artifacts", "idx_artifacts_created_at", ["created_at"])
    await add_index("artifacts", "idx_artifacts_source_task_id", ["source_task_id"])
    
    # Ajouter la colonne duration_ms à execution_logs
    if await table_exists("execution_logs"):
        await add_column("execution_logs", "duration_ms", "INTEGER")
        await add_column("execution_logs", "level", "VARCHAR DEFAULT 'info'")
        await add_column("execution_logs", "category", "VARCHAR DEFAULT 'system'")
    
    await set_current_version("3.0.0", "Migration v2 -> v3")
    logger.info("✅ Migration v2 -> v3 terminée")


async def migration_v3_to_v4() -> None:
    """
    Migration de la version 3 à la version 4 du schéma.
    Ajoute les contraintes de clés étrangères et les index composites.
    """
    logger.info("📊 Migration v3 -> v4...")
    
    # Ajouter les index composites
    if await table_exists("task_results"):
        await add_index("task_results", "idx_task_results_sprint_status", ["sprint_id", "status"])
        await add_index("task_results", "idx_task_results_task_id", ["task_id"])
        await add_index("task_results", "idx_task_results_timestamp", ["timestamp"])
    
    if await table_exists("execution_logs"):
        await add_index("execution_logs", "idx_execution_logs_task_level", ["task_id", "level"])
        await add_index("execution_logs", "idx_execution_logs_agent_category", ["agent_id", "category"])
    
    # Ajouter des contraintes de validation
    if await table_exists("sprints"):
        await execute_migration("""
            ALTER TABLE sprints ADD CONSTRAINT chk_sprint_priority 
            CHECK (priority >= 1 AND priority <= 10)
        """)
    
    await set_current_version("4.0.0", "Migration v3 -> v4")
    logger.info("✅ Migration v3 -> v4 terminée")


# ==============================================================================
# EXÉCUTION DES MIGRATIONS
# ==============================================================================

async def run_migrations(target_version: Optional[str] = None) -> None:
    """
    Exécute toutes les migrations nécessaires.
    
    Args:
        target_version: Version cible (si None, exécute toutes les migrations)
    """
    logger.info(f"📊 Exécution des migrations (version cible: {target_version or 'latest'})...")
    
    # Vérifier l'état actuel
    existing_tables = await get_existing_tables()
    current_version = await get_current_version()
    
    logger.info(f"📊 Version actuelle: {current_version or 'Aucune'}")
    
    if not existing_tables:
        logger.info("📊 Aucune table existante, initialisation...")
        await init_models()
        await set_current_version("1.0.0", "Initial creation")
        return
    
    # Déterminer les migrations à exécuter
    migrations = [
        ("1.0.0", "2.0.0", migration_v1_to_v2),
        ("2.0.0", "3.0.0", migration_v2_to_v3),
        ("3.0.0", "4.0.0", migration_v3_to_v4),
    ]
    
    for from_ver, to_ver, migration_func in migrations:
        if target_version and to_ver > target_version:
            continue
        
        # Vérifier si la migration doit être exécutée
        if current_version is None or current_version == from_ver or current_version < to_ver:
            try:
                logger.info(f"📊 Exécution de la migration {from_ver} -> {to_ver}...")
                await migration_func()
                current_version = to_ver
                logger.info(f"✅ Migration {from_ver} -> {to_ver} terminée")
            except Exception as e:
                logger.error(f"❌ Erreur lors de la migration {from_ver} -> {to_ver}: {e}")
                raise
    
    logger.info("✅ Migrations terminées")


# ==============================================================================
# ROLLBACK
# ==============================================================================

async def rollback_to_version(target_version: str) -> None:
    """
    Effectue un rollback vers une version spécifique.
    
    Args:
        target_version: Version cible
    """
    logger.warning(f"⚠️ Rollback vers la version {target_version}...")
    
    current_version = await get_current_version()
    if not current_version:
        logger.error("❌ Impossible de déterminer la version actuelle")
        return
    
    # Vérifier les versions disponibles
    versions = ["1.0.0", "2.0.0", "3.0.0", "4.0.0"]
    if target_version not in versions:
        logger.error(f"❌ Version {target_version} non reconnue")
        return
    
    # Exécuter les rollbacks dans l'ordre inverse
    rollbacks = [
        ("4.0.0", "3.0.0", rollback_v4_to_v3),
        ("3.0.0", "2.0.0", rollback_v3_to_v2),
        ("2.0.0", "1.0.0", rollback_v2_to_v1),
    ]
    
    for from_ver, to_ver, rollback_func in rollbacks:
        if current_version == from_ver and from_ver > target_version:
            try:
                logger.info(f"📊 Rollback {from_ver} -> {to_ver}...")
                await rollback_func()
                current_version = to_ver
                logger.info(f"✅ Rollback {from_ver} -> {to_ver} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur lors du rollback {from_ver} -> {to_ver}: {e}")
                raise
    
    await set_current_version(target_version, f"Rollback to {target_version}")
    logger.info(f"✅ Rollback vers {target_version} terminé")


async def rollback_v4_to_v3() -> None:
    """Rollback de v4 à v3."""
    logger.info("📊 Rollback v4 -> v3...")
    # Supprimer les index ajoutés en v4
    await drop_index("task_results", "idx_task_results_sprint_status")
    await drop_index("task_results", "idx_task_results_task_id")
    await drop_index("task_results", "idx_task_results_timestamp")
    await drop_index("execution_logs", "idx_execution_logs_task_level")
    await drop_index("execution_logs", "idx_execution_logs_agent_category")
    logger.info("✅ Rollback v4 -> v3 terminé")


async def rollback_v3_to_v2() -> None:
    """Rollback de v3 à v2."""
    logger.info("📊 Rollback v3 -> v2...")
    # Supprimer les colonnes ajoutées en v3
    await drop_column("execution_logs", "duration_ms")
    await drop_column("execution_logs", "level")
    await drop_column("execution_logs", "category")
    
    # Supprimer la table artifacts
    if await table_exists("artifacts"):
        await execute_migration("DROP TABLE IF EXISTS artifacts")
    logger.info("✅ Rollback v3 -> v2 terminé")


async def rollback_v2_to_v1() -> None:
    """Rollback de v2 à v1."""
    logger.info("📊 Rollback v2 -> v1...")
    # Supprimer les colonnes ajoutées en v2
    tables = ["projects", "sprints", "task_results"]
    for table in tables:
        await drop_column(table, "updated_at")
        await drop_column(table, "metadata")
    
    await drop_column("sprints", "priority")
    await drop_column("projects", "tags")
    logger.info("✅ Rollback v2 -> v1 terminé")


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
        
        # Vérifier la version
        print("\n📊 Vérification de la version...")
        version = await get_current_version()
        print(f"✅ Version actuelle: {version or 'Aucune'}")
        
        # Vérifier les informations de la table
        if "projects" in tables:
            print("\n📋 Informations de la table 'projects'...")
            info = await get_table_info("projects")
            if info:
                columns = [col['name'] for col in info['columns']]
                print(f"✅ Colonnes: {columns}")
                if info['primary_key']:
                    print(f"✅ Clés primaires: {info['primary_key']['constrained_columns']}")
        
        # Exécuter les migrations
        print("\n📊 Exécution des migrations...")
        await run_migrations()
        print("✅ Migrations terminées")
        
        print("\n✅ Tests terminés.")
    
    # Exécuter les tests
    asyncio.run(test_migrations())