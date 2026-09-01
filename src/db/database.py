# src/db/database.py
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from src.config.settings import settings

# Moteur de base de données
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

# Fabrique de sessions
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base pour les modèles ORM
Base = declarative_base()

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Fournit une session de base de données asynchrone."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def close_db_connection() -> None:
    """Ferme la connexion à la base de données."""
    await engine.dispose()