# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Configuration (Settings)
# ==============================================================================
# Fichier: src/config/settings.py
# Description: Gestion centralisée de la configuration avec Pydantic-Settings.
#              Charge automatiquement les variables depuis .env.
# ==============================================================================

from pydantic_settings import BaseSettings
from pydantic import Field, validator, SecretStr
from typing import Optional, List, Dict, Any
from pathlib import Path
import os


# ==============================================================================
# CLASSE SETTINGS
# ==============================================================================

class Settings(BaseSettings):
    """
    Configuration globale du pipeline.
    Les variables sont chargées depuis .env avec validation automatique.
    """
    
    # ==========================================================================
    # GITHUB
    # ==========================================================================
    github_token: SecretStr = Field(..., description="Token GitHub pour les opérations")
    github_username: str = Field(default="octocat", description="Nom d'utilisateur GitHub")
    github_repo: Optional[str] = Field(None, description="Repository GitHub par défaut")
    
    # ==========================================================================
    # BLOCKCHAIN
    # ==========================================================================
    eth_rpc_url: str = Field(default="http://127.0.0.1:8545", description="URL RPC Ethereum")
    polygon_rpc_url: Optional[str] = Field(None, description="URL RPC Polygon")
    arbitrum_rpc_url: Optional[str] = Field(None, description="URL RPC Arbitrum")
    optimism_rpc_url: Optional[str] = Field(None, description="URL RPC Optimism")
    base_rpc_url: Optional[str] = Field(None, description="URL RPC Base")
    solana_rpc_url: Optional[str] = Field(None, description="URL RPC Solana")
    chain_id: int = Field(default=313133, description="ID de la chaîne par défaut")
    
    # ==========================================================================
    # BASE DE DONNÉES
    # ==========================================================================
    database_url: str = Field(
        default="postgresql+asyncpg://pipeline:pipeline@localhost:5432/pipeline",
        description="URL de connexion PostgreSQL"
    )
    database_echo: bool = Field(default=False, description="Activer les logs SQL")
    database_pool_size: int = Field(default=5, ge=1, le=50, description="Taille du pool de connexions")
    database_max_overflow: int = Field(default=10, ge=0, description="Nombre max de connexions overflow")
    
    # ==========================================================================
    # REDIS / CACHE
    # ==========================================================================
    redis_url: str = Field(default="redis://localhost:6379/0", description="URL Redis")
    redis_password: Optional[SecretStr] = Field(None, description="Mot de passe Redis")
    redis_max_connections: int = Field(default=10, ge=1, description="Nombre max de connexions Redis")
    
    # ==========================================================================
    # LLM / OLLAMA
    # ==========================================================================
    ollama_url: str = Field(default="http://localhost:11434", description="URL du serveur Ollama")
    ollama_default_model: str = Field(default="deepseek-coder:6.7b-instruct", description="Modèle par défaut")
    ollama_embedding_model: str = Field(default="nomic-embed-text", description="Modèle d'embedding")
    llm_timeout: int = Field(default=60, gt=0, description="Timeout LLM en secondes")
    llm_temperature: float = Field(default=0.1, ge=0.0, le=1.0, description="Température par défaut")
    
    # ==========================================================================
    # CHROMADB (VECTOR DATABASE)
    # ==========================================================================
    chroma_host: str = Field(default="localhost", description="Hôte ChromaDB")
    chroma_port: int = Field(default=8000, ge=1, le=65535, description="Port ChromaDB")
    chroma_collection: str = Field(default="web3_docs", description="Collection par défaut")
    
    # ==========================================================================
    # PIPELINE
    # ==========================================================================
    max_auto_debug_retries: int = Field(default=3, ge=0, le=10, description="Nombre max de tentatives d'auto-correction")
    verification_timeout: int = Field(default=300, gt=0, description="Timeout de vérification en secondes")
    halmos_max_depth: int = Field(default=10, ge=1, le=50, description="Profondeur max pour Halmos")
    workspace_path: Path = Field(default=Path("./workspace"), description="Répertoire de travail")
    log_level: str = Field(default="INFO", description="Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    
    # ==========================================================================
    # API
    # ==========================================================================
    api_host: str = Field(default="0.0.0.0", description="Hôte de l'API")
    api_port: int = Field(default=8000, ge=1, le=65535, description="Port de l'API")
    api_reload: bool = Field(default=False, description="Activer le rechargement automatique")
    api_cors_origins: List[str] = Field(default=["*"], description="Origines CORS autorisées")
    
    # ==========================================================================
    # CLÉS API EXTERNES
    # ==========================================================================
    infura_api_key: Optional[SecretStr] = Field(None, description="Clé API Infura")
    alchemy_api_key: Optional[SecretStr] = Field(None, description="Clé API Alchemy")
    etherscan_api_key: Optional[SecretStr] = Field(None, description="Clé API Etherscan")
    polygonscan_api_key: Optional[SecretStr] = Field(None, description="Clé API Polygonscan")
    coinmarketcap_api_key: Optional[SecretStr] = Field(None, description="Clé API CoinMarketCap")
    
    # ==========================================================================
    # TEST / DEBUG
    # ==========================================================================
    debug: bool = Field(default=False, description="Mode debug")
    test_mode: bool = Field(default=False, description="Mode test")
    mock_llm: bool = Field(default=False, description="Utiliser un LLM mock")
    mock_blockchain: bool = Field(default=False, description="Utiliser une blockchain mock")
    
    # ==========================================================================
    # VALIDATEURS
    # ==========================================================================
    
    @validator('workspace_path', pre=True)
    def validate_workspace(cls, v: Any) -> Path:
        """Convertit le chemin en Path et crée le dossier si nécessaire."""
        if isinstance(v, str):
            v = Path(v)
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @validator('database_url')
    def validate_database_url(cls, v: str) -> str:
        """Vérifie que l'URL de base de données est valide."""
        if not v.startswith(('postgresql', 'sqlite')):
            raise ValueError(f"Invalid database URL: '{v}'")
        return v
    
    @validator('redis_url')
    def validate_redis_url(cls, v: str) -> str:
        """Vérifie que l'URL Redis est valide."""
        if not v.startswith(('redis://', 'rediss://')):
            raise ValueError(f"Invalid Redis URL: '{v}'")
        return v
    
    @validator('log_level')
    def validate_log_level(cls, v: str) -> str:
        """Vérifie que le niveau de log est valide."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: '{v}'. Must be one of {valid_levels}")
        return v.upper()
    
    @validator('api_cors_origins', pre=True)
    def parse_cors_origins(cls, v: Any) -> List[str]:
        """Convertit une chaîne en liste pour CORS."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v
    
    # ==========================================================================
    # MÉTHODES UTILITAIRES
    # ==========================================================================
    
    def get_database_connection_args(self) -> Dict[str, Any]:
        """Retourne les arguments de connexion à la base de données."""
        return {
            "pool_size": self.database_pool_size,
            "max_overflow": self.database_max_overflow,
            "echo": self.database_echo,
        }
    
    def get_redis_connection_args(self) -> Dict[str, Any]:
        """Retourne les arguments de connexion à Redis."""
        args = {
            "decode_responses": True,
            "max_connections": self.redis_max_connections,
        }
        if self.redis_password:
            args["password"] = self.redis_password.get_secret_value()
        return args
    
    def get_ollama_connection_args(self) -> Dict[str, Any]:
        """Retourne les arguments de connexion à Ollama."""
        return {
            "base_url": self.ollama_url,
            "default_model": self.ollama_default_model,
            "embedding_model": self.ollama_embedding_model,
            "timeout": self.llm_timeout,
            "temperature": self.llm_temperature,
        }
    
    def get_workspace_path(self, subpath: Optional[str] = None) -> Path:
        """
        Retourne le chemin du workspace, éventuellement avec un sous-chemin.
        
        Args:
            subpath: Sous-chemin optionnel
            
        Returns:
            Path absolu du workspace
        """
        if subpath:
            return self.workspace_path / subpath
        return self.workspace_path
    
    def is_production(self) -> bool:
        """Vérifie si l'environnement est en production."""
        return not self.debug and not self.test_mode
    
    def is_development(self) -> bool:
        """Vérifie si l'environnement est en développement."""
        return self.debug and not self.test_mode
    
    def get_chain_rpc_url(self, chain: str) -> Optional[str]:
        """
        Retourne l'URL RPC pour une chaîne donnée.
        
        Args:
            chain: Nom de la chaîne (ethereum, polygon, arbitrum, optimism, base, solana)
            
        Returns:
            URL RPC ou None si non configurée
        """
        mapping = {
            "ethereum": self.eth_rpc_url,
            "polygon": self.polygon_rpc_url,
            "arbitrum": self.arbitrum_rpc_url,
            "optimism": self.optimism_rpc_url,
            "base": self.base_rpc_url,
            "solana": self.solana_rpc_url,
        }
        return mapping.get(chain.lower())
    
    def get_github_auth(self) -> Dict[str, str]:
        """Retourne les informations d'authentification GitHub."""
        return {
            "token": self.github_token.get_secret_value(),
            "username": self.github_username,
        }
    
    def get_api_url(self) -> str:
        """Retourne l'URL complète de l'API."""
        return f"http://{self.api_host}:{self.api_port}"
    
    def to_dict(self, show_secrets: bool = False) -> Dict[str, Any]:
        """
        Convertit la configuration en dictionnaire.
        
        Args:
            show_secrets: Si True, affiche les secrets (à utiliser uniquement en debug)
            
        Returns:
            Dict[str, Any]: Configuration sous forme de dictionnaire
        """
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, SecretStr):
                result[key] = value.get_secret_value() if show_secrets else "***HIDDEN***"
            elif isinstance(value, Path):
                result[key] = str(value)
            else:
                result[key] = value
        return result


# ==============================================================================
# INSTANCE UNIQUE
# ==============================================================================

# Création de l'instance unique de configuration
settings = Settings()


# ==============================================================================
# FONCTION DE CHARGEMENT PERSONNALISÉ
# ==============================================================================

def load_settings_from_env(env_file: Optional[Path] = None) -> Settings:
    """
    Charge les paramètres depuis un fichier .env personnalisé.
    
    Args:
        env_file: Chemin vers le fichier .env (optionnel)
        
    Returns:
        Settings: Instance de configuration
    """
    if env_file and env_file.exists():
        # Utiliser un fichier .env personnalisé
        os.environ["ENV_FILE"] = str(env_file)
    
    # Recharger les paramètres
    return Settings()


def reload_settings() -> None:
    """
    Recharge les paramètres depuis .env.
    Utile après une modification du fichier .env.
    """
    global settings
    settings = Settings()


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Configuration")
    print("=" * 60)
    
    print(f"\n🔧 Configuration actuelle:")
    print(f"  🐍 Database: {settings.database_url}")
    print(f"  🔴 Redis: {settings.redis_url}")
    print(f"  🤖 Ollama: {settings.ollama_url}")
    print(f"  📊 ChromaDB: {settings.chroma_host}:{settings.chroma_port}")
    print(f"  🌐 API: {settings.get_api_url()}")
    print(f"  📁 Workspace: {settings.workspace_path}")
    print(f"  📊 Log Level: {settings.log_level}")
    
    print(f"\n📝 Vérifications:")
    print(f"  ✅ Mode production: {settings.is_production()}")
    print(f"  ✅ Mode développement: {settings.is_development()}")
    
    print(f"\n📋 RPC URLs:")
    print(f"  Ethereum: {settings.eth_rpc_url}")
    if settings.polygon_rpc_url:
        print(f"  Polygon: {settings.polygon_rpc_url}")
    if settings.arbitrum_rpc_url:
        print(f"  Arbitrum: {settings.arbitrum_rpc_url}")
    
    print(f"\n🔑 Secrets (masqués):")
    config_dict = settings.to_dict(show_secrets=False)
    for key, value in config_dict.items():
        if "token" in key.lower() or "key" in key.lower() or "secret" in key.lower():
            print(f"  {key}: {value}")
    
    print("\n✅ Configuration chargée avec succès.")