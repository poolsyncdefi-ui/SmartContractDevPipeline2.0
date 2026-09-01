# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Configuration (Settings)
# ==============================================================================
# Fichier: src/config/settings.py
# Description: Gestion centralisée de la configuration avec Pydantic-Settings.
#              Charge automatiquement les variables depuis .env.
#              Supporte les profils (dev, prod, test) et la validation avancée.
# ==============================================================================

from pydantic_settings import BaseSettings
from pydantic import Field, validator, SecretStr, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal, Union
from pathlib import Path
import os
import logging
from enum import Enum


# ==============================================================================
# ENUMS DE CONFIGURATION
# ==============================================================================

class Environment(str, Enum):
    """Environnements supportés."""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"
    STAGING = "staging"


class LogFormat(str, Enum):
    """Formats de log supportés."""
    JSON = "json"
    TEXT = "text"
    COLORED = "colored"


# ==============================================================================
# SOUS-MODÈLES DE CONFIGURATION
# ==============================================================================

class DatabaseConfig(BaseModel):
    """Configuration de la base de données."""
    url: str = Field(default="postgresql+asyncpg://pipeline:pipeline@localhost:5432/pipeline")
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0)
    echo: bool = Field(default=False)
    echo_pool: bool = Field(default=False)
    pool_pre_ping: bool = Field(default=True)
    pool_recycle: int = Field(default=3600, ge=0)
    ssl_mode: Optional[Literal["disable", "require", "verify-ca", "verify-full"]] = Field(default=None)


class RedisConfig(BaseModel):
    """Configuration Redis."""
    url: str = Field(default="redis://localhost:6379/0")
    password: Optional[SecretStr] = Field(None)
    max_connections: int = Field(default=10, ge=1)
    socket_timeout: float = Field(default=5.0, ge=0.1)
    socket_connect_timeout: float = Field(default=5.0, ge=0.1)
    retry_on_timeout: bool = Field(default=True)
    health_check_interval: int = Field(default=30, ge=0)


class LLMConfig(BaseModel):
    """Configuration LLM."""
    ollama_url: str = Field(default="http://localhost:11434")
    default_model: str = Field(default="deepseek-coder:6.7b-instruct")
    embedding_model: str = Field(default="nomic-embed-text")
    timeout: int = Field(default=60, gt=0)
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, gt=0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    top_k: int = Field(default=40, gt=0)
    repeat_penalty: float = Field(default=1.1, ge=1.0)
    num_ctx: int = Field(default=4096, gt=0)
    num_gpu: int = Field(default=0, ge=0)
    use_mock: bool = Field(default=False)


class ChromaConfig(BaseModel):
    """Configuration ChromaDB."""
    host: str = Field(default="localhost")
    port: int = Field(default=8000, ge=1, le=65535)
    collection: str = Field(default="web3_docs")
    ssl: bool = Field(default=False)
    max_batch_size: int = Field(default=100, gt=0)
    timeout: int = Field(default=30, gt=0)


class APIConfig(BaseModel):
    """Configuration API."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = Field(default=False)
    cors_origins: List[str] = Field(default=["*"])
    cors_credentials: bool = Field(default=True)
    max_body_size: int = Field(default=10 * 1024 * 1024, gt=0)  # 10MB
    timeout: int = Field(default=60, gt=0)
    workers: int = Field(default=1, ge=1)


class SecurityConfig(BaseModel):
    """Configuration de sécurité."""
    jwt_secret: Optional[SecretStr] = Field(None)
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_minutes: int = Field(default=60 * 24, ge=0)  # 24 hours
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests: int = Field(default=100, gt=0)
    rate_limit_period: int = Field(default=60, gt=0)  # seconds
    require_https: bool = Field(default=False)
    allowed_ips: List[str] = Field(default=[])
    blocked_ips: List[str] = Field(default=[])


class LoggingConfig(BaseModel):
    """Configuration de logging."""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    format: LogFormat = Field(default=LogFormat.COLORED)
    file_path: Optional[Path] = Field(None)
    file_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)  # 10MB
    file_backup_count: int = Field(default=5, ge=0)
    json_indent: Optional[int] = Field(None)
    include_traceback: bool = Field(default=True)


class CircuitBreakerConfig(BaseModel):
    """Configuration du circuit breaker."""
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=60, gt=0)
    half_open_timeout: int = Field(default=10, gt=0)
    failure_threshold: int = Field(default=5, gt=0)
    success_threshold: int = Field(default=2, gt=0)


class PipelineConfig(BaseModel):
    """Configuration du pipeline."""
    max_auto_debug_retries: int = Field(default=3, ge=0, le=10)
    verification_timeout: int = Field(default=300, gt=0)
    halmos_max_depth: int = Field(default=10, ge=1, le=50)
    slither_timeout: int = Field(default=60, gt=0)
    foundry_timeout: int = Field(default=120, gt=0)
    max_parallel_tasks: int = Field(default=4, ge=1, le=20)
    default_workspace: Path = Field(default=Path("./workspace"))
    enable_metrics: bool = Field(default=True)
    enable_tracing: bool = Field(default=False)


# ==============================================================================
# CLASSE SETTINGS PRINCIPALE
# ==============================================================================

class Settings(BaseSettings):
    """
    Configuration globale du pipeline.
    Les variables sont chargées depuis .env avec validation automatique.
    Supporte les profils (dev, prod, test) via le préfixe ENV.
    """
    
    # ==========================================================================
    # ENVIRONNEMENT
    # ==========================================================================
    env: Environment = Field(default=Environment.DEVELOPMENT, description="Environnement actuel")
    env_prefix: str = Field(default="", description="Préfixe des variables d'environnement")
    debug: bool = Field(default=False, description="Mode debug")
    test_mode: bool = Field(default=False, description="Mode test")
    
    # ==========================================================================
    # SOUS-CONFIGURATIONS
    # ==========================================================================
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    chroma: ChromaConfig = Field(default_factory=ChromaConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    
    # ==========================================================================
    # BLOCKCHAIN
    # ==========================================================================
    eth_rpc_url: str = Field(default="http://127.0.0.1:8545")
    polygon_rpc_url: Optional[str] = Field(None)
    arbitrum_rpc_url: Optional[str] = Field(None)
    optimism_rpc_url: Optional[str] = Field(None)
    base_rpc_url: Optional[str] = Field(None)
    solana_rpc_url: Optional[str] = Field(None)
    avalanche_rpc_url: Optional[str] = Field(None)
    bsc_rpc_url: Optional[str] = Field(None)
    fantom_rpc_url: Optional[str] = Field(None)
    chain_id: int = Field(default=313133)
    
    # ==========================================================================
    # GITHUB
    # ==========================================================================
    github_token: SecretStr = Field(..., description="Token GitHub pour les opérations")
    github_username: str = Field(default="octocat")
    github_repo: Optional[str] = Field(None)
    github_enterprise_url: Optional[str] = Field(None)
    
    # ==========================================================================
    # CLÉS API
    # ==========================================================================
    infura_api_key: Optional[SecretStr] = Field(None)
    alchemy_api_key: Optional[SecretStr] = Field(None)
    etherscan_api_key: Optional[SecretStr] = Field(None)
    polygonscan_api_key: Optional[SecretStr] = Field(None)
    coinmarketcap_api_key: Optional[SecretStr] = Field(None)
    
    # ==========================================================================
    # MÉTRIQUES ET MONITORING
    # ==========================================================================
    prometheus_enabled: bool = Field(default=False)
    prometheus_port: int = Field(default=9090, ge=1, le=65535)
    sentry_dsn: Optional[SecretStr] = Field(None)
    opentelemetry_enabled: bool = Field(default=False)
    opentelemetry_endpoint: Optional[str] = Field(None)
    
    # ==========================================================================
    # STOCKAGE
    # ==========================================================================
    storage_type: Literal["local", "s3", "gcs"] = Field(default="local")
    storage_path: Path = Field(default=Path("./storage"))
    s3_bucket: Optional[str] = Field(None)
    s3_region: Optional[str] = Field(None)
    s3_access_key: Optional[SecretStr] = Field(None)
    s3_secret_key: Optional[SecretStr] = Field(None)
    gcs_bucket: Optional[str] = Field(None)
    gcs_credentials: Optional[SecretStr] = Field(None)
    
    # ==========================================================================
    # DIVERS
    # ==========================================================================
    cache_ttl: int = Field(default=300, ge=0, description="Cache TTL en secondes")
    default_timezone: str = Field(default="UTC")
    supported_chains: List[str] = Field(default=["ethereum", "polygon", "arbitrum", "optimism", "base"])
    
    # ==========================================================================
    # VALIDATEURS
    # ==========================================================================
    
    @field_validator('storage_path', mode='before')
    @classmethod
    def validate_storage_path(cls, v: Any) -> Path:
        """Convertit le chemin en Path et crée le dossier si nécessaire."""
        if isinstance(v, str):
            v = Path(v)
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @model_validator(mode='after')
    def validate_environment(self) -> 'Settings':
        """Valide la cohérence de l'environnement."""
        if self.env == Environment.PRODUCTION:
            if self.debug:
                raise ValueError("Production environment cannot have debug=True")
            if self.test_mode:
                raise ValueError("Production environment cannot have test_mode=True")
        return self
    
    @field_validator('supported_chains')
    @classmethod
    def validate_supported_chains(cls, v: List[str]) -> List[str]:
        """Valide les chaînes supportées."""
        valid_chains = {"ethereum", "polygon", "arbitrum", "optimism", "base", "solana", "avalanche", "bsc", "fantom"}
        invalid = set(v) - valid_chains
        if invalid:
            raise ValueError(f"Invalid chains: {invalid}. Must be one of {valid_chains}")
        return v
    
    # ==========================================================================
    # MÉTHODES UTILITAIRES
    # ==========================================================================
    
    def get_database_url(self) -> str:
        """Retourne l'URL de la base de données."""
        return self.database.url
    
    def get_redis_url(self) -> str:
        """Retourne l'URL Redis."""
        return self.redis.url
    
    def get_ollama_url(self) -> str:
        """Retourne l'URL Ollama."""
        return self.llm.ollama_url
    
    def get_chroma_host(self) -> str:
        """Retourne l'hôte ChromaDB."""
        return self.chroma.host
    
    def get_chroma_port(self) -> int:
        """Retourne le port ChromaDB."""
        return self.chroma.port
    
    def get_workspace_path(self, subpath: Optional[str] = None) -> Path:
        """
        Retourne le chemin du workspace, éventuellement avec un sous-chemin.
        
        Args:
            subpath: Sous-chemin optionnel
            
        Returns:
            Path absolu du workspace
        """
        if subpath:
            return self.pipeline.default_workspace / subpath
        return self.pipeline.default_workspace
    
    def get_storage_path(self, subpath: Optional[str] = None) -> Path:
        """
        Retourne le chemin de stockage, éventuellement avec un sous-chemin.
        
        Args:
            subpath: Sous-chemin optionnel
            
        Returns:
            Path absolu du stockage
        """
        if subpath:
            return self.storage_path / subpath
        return self.storage_path
    
    def get_chain_rpc_url(self, chain: str) -> Optional[str]:
        """
        Retourne l'URL RPC pour une chaîne donnée.
        
        Args:
            chain: Nom de la chaîne
            
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
            "avalanche": self.avalanche_rpc_url,
            "bsc": self.bsc_rpc_url,
            "fantom": self.fantom_rpc_url,
        }
        return mapping.get(chain.lower())
    
    def get_github_token(self) -> str:
        """Retourne le token GitHub."""
        return self.github_token.get_secret_value()
    
    def get_github_auth(self) -> Dict[str, str]:
        """Retourne les informations d'authentification GitHub."""
        return {
            "token": self.get_github_token(),
            "username": self.github_username,
        }
    
    def get_api_url(self) -> str:
        """Retourne l'URL complète de l'API."""
        return f"http://{self.api.host}:{self.api.port}"
    
    def get_log_level(self) -> str:
        """Retourne le niveau de log."""
        return self.logging.level
    
    def get_env_prefix(self) -> str:
        """Retourne le préfixe d'environnement."""
        return self.env_prefix
    
    def is_production(self) -> bool:
        """Vérifie si l'environnement est en production."""
        return self.env == Environment.PRODUCTION
    
    def is_development(self) -> bool:
        """Vérifie si l'environnement est en développement."""
        return self.env == Environment.DEVELOPMENT
    
    def is_testing(self) -> bool:
        """Vérifie si l'environnement est en test."""
        return self.env == Environment.TESTING
    
    def is_debug(self) -> bool:
        """Vérifie si le mode debug est activé."""
        return self.debug
    
    def get_max_retries(self) -> int:
        """Retourne le nombre maximum de retries."""
        return self.circuit_breaker.max_retries
    
    def get_verification_timeout(self) -> int:
        """Retourne le timeout de vérification."""
        return self.pipeline.verification_timeout
    
    def to_dict(self, show_secrets: bool = False) -> Dict[str, Any]:
        """
        Convertit la configuration en dictionnaire.
        
        Args:
            show_secrets: Si True, affiche les secrets (à utiliser uniquement en debug)
            
        Returns:
            Dict[str, Any]: Configuration sous forme de dictionnaire
        """
        result = {
            "env": self.env.value,
            "debug": self.debug,
            "test_mode": self.test_mode,
            "database": self.database.model_dump(),
            "redis": {**self.redis.model_dump(), "password": "***HIDDEN***" if not show_secrets else self.redis.password.get_secret_value() if self.redis.password else None},
            "llm": self.llm.model_dump(),
            "chroma": self.chroma.model_dump(),
            "api": self.api.model_dump(),
            "security": {**self.security.model_dump(), "jwt_secret": "***HIDDEN***" if not show_secrets and self.security.jwt_secret else self.security.jwt_secret.get_secret_value() if self.security.jwt_secret else None},
            "logging": self.logging.model_dump(),
            "circuit_breaker": self.circuit_breaker.model_dump(),
            "pipeline": {**self.pipeline.model_dump(), "default_workspace": str(self.pipeline.default_workspace)},
            "storage": {
                "type": self.storage_type,
                "path": str(self.storage_path),
            },
            "github": {
                "username": self.github_username,
                "token": "***HIDDEN***" if not show_secrets else self.get_github_token(),
            },
        }
        return result


# ==============================================================================
# INSTANCE UNIQUE
# ==============================================================================

# Création de l'instance unique de configuration
settings = Settings()


# ==============================================================================
# FONCTIONS DE CHARGEMENT
# ==============================================================================

def load_settings(env_file: Optional[Path] = None, env_prefix: str = "") -> Settings:
    """
    Charge les paramètres depuis un fichier .env personnalisé.
    
    Args:
        env_file: Chemin vers le fichier .env (optionnel)
        env_prefix: Préfixe des variables d'environnement
        
    Returns:
        Settings: Instance de configuration
    """
    if env_file and env_file.exists():
        # Charger le fichier .env personnalisé
        import dotenv
        dotenv.load_dotenv(env_file)
    
    # Créer une nouvelle instance
    return Settings(env_prefix=env_prefix)


def reload_settings() -> None:
    """
    Recharge les paramètres depuis .env.
    Utile après une modification du fichier .env.
    """
    global settings
    settings = Settings()


def get_settings_for_env(env: Environment) -> Settings:
    """
    Retourne les paramètres pour un environnement spécifique.
    
    Args:
        env: Environnement cible
        
    Returns:
        Settings: Configuration pour l'environnement
    """
    # Changer temporairement l'environnement
    original_env = settings.env
    settings.env = env
    
    # Forcer le rechargement des variables
    reload_settings()
    
    # Restaurer l'environnement
    settings.env = original_env
    
    return settings


# ==============================================================================
# CONFIGURATION DU LOGGING
# ==============================================================================

def setup_logging(settings: Optional[Settings] = None) -> None:
    """
    Configure le logging selon les paramètres.
    
    Args:
        settings: Configuration (utilise settings par défaut)
    """
    if settings is None:
        settings = globals().get('settings')
        if settings is None:
            settings = Settings()
    
    log_level = getattr(logging, settings.get_log_level().upper())
    log_format = settings.logging.format
    
    # Configuration du format
    if log_format == LogFormat.JSON:
        # Format JSON pour les logs structurés
        import json
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                return json.dumps({
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "module": record.module,
                    "message": record.getMessage(),
                    "extra": getattr(record, "extra", {}),
                })
        formatter = JSONFormatter()
    elif log_format == LogFormat.COLORED:
        # Format coloré pour le développement
        import colorlog
        formatter = colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
    else:
        # Format texte standard
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Configuration du handler
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Supprimer les handlers existants
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Ajouter le handler console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Ajouter un handler fichier si configuré
    if settings.logging.file_path:
        file_path = settings.logging.file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.RotatingFileHandler(
            file_path,
            maxBytes=settings.logging.file_max_bytes,
            backupCount=settings.logging.file_backup_count
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Logging de la configuration
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured with level={settings.logging.level}")


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Configuration")
    print("=" * 60)
    
    print(f"\n🔧 Configuration actuelle:")
    print(f"  🌍 Environnement: {settings.env.value}")
    print(f"  🐍 Database: {settings.database.url}")
    print(f"  🔴 Redis: {settings.redis.url}")
    print(f"  🤖 Ollama: {settings.llm.ollama_url}")
    print(f"  📊 ChromaDB: {settings.chroma.host}:{settings.chroma.port}")
    print(f"  🌐 API: {settings.get_api_url()}")
    print(f"  📁 Workspace: {settings.get_workspace_path()}")
    print(f"  📊 Log Level: {settings.logging.level}")
    
    print(f"\n📝 Vérifications:")
    print(f"  ✅ Mode production: {settings.is_production()}")
    print(f"  ✅ Mode développement: {settings.is_development()}")
    print(f"  ✅ Mode debug: {settings.is_debug()}")
    
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