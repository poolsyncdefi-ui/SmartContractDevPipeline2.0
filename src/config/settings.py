# src/config/settings.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Configuration globale du pipeline chargée depuis .env."""
    
    # GitHub
    github_token: str
    github_username: str = "octocat"
    
    # Blockchain
    eth_rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = 313133
    
    # Base de données
    database_url: str = "postgresql+asyncpg://pipeline:pipeline@localhost:5432/pipeline"
    
    # Cache et messaging
    redis_url: str = "redis://localhost:6379/0"
    
    # LLM
    ollama_url: str = "http://localhost:11434"
    
    # Vector database
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    
    # Pipeline
    max_auto_debug_retries: int = 3
    verification_timeout: int = 300
    halmos_max_depth: int = 10
    
    # Workspace
    workspace_path: str = "./workspace"
    log_level: str = "INFO"
    
    # Clés API externes
    infura_api_key: Optional[str] = None
    alchemy_api_key: Optional[str] = None
    etherscan_api_key: Optional[str] = None
    polygonscan_api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Instance unique
settings = Settings()