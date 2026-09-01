# src/db/migrations.py
from src.db.database import engine, Base
import src.models.project
import src.models.task
import src.models.execution_log
import src.models.skill_record

async def init_models() -> None:
    """Crée les tables en base de données."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def drop_models() -> None:
    """Supprime les tables (réinitialisation)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)