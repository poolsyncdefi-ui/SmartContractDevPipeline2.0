# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - CLI Main Entry Point
# ==============================================================================
# Fichier: src/cli/main.py
# Description: Point d'entrée de la CLI avec les commandes principales.
#              Configuration du logging, gestion des erreurs, couleurs,
#              profiles et métriques.
#              Version refactorisée avec logger structuré et horodatages timezone-aware.
# ==============================================================================

import click
import logging
import sys
import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import json
import time

from src.cli.commands import cli as commands_cli
from src.config.settings import settings
from src.core.exceptions import PipelineError
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.status_manager import normalize_status

# ==============================================================================
# CONSTANTES
# ==============================================================================

VERSION = "2.0.0"
CLI_NAME = "pipeline"

# Logger structuré pour la CLI
_cli_logger = StructuredLogger(
    component_name="CLIMain",
    log_level=LogLevel.INFO
)


# ==============================================================================
# CONFIGURATION DU LOGGING
# ==============================================================================

def configure_cli_logging(verbose: bool = False, quiet: bool = False) -> None:
    """
    Configure le logging pour la CLI.
    
    Args:
        verbose: Mode verbose (DEBUG)
        quiet: Mode silencieux (ERROR)
    """
    if quiet:
        log_level = logging.ERROR
        structured_level = LogLevel.ERROR
    elif verbose:
        log_level = logging.DEBUG
        structured_level = LogLevel.DEBUG
    else:
        log_level = logging.INFO
        structured_level = LogLevel.INFO
    
    # Mise à jour du niveau du logger structuré
    _cli_logger.log_level = structured_level
    
    # Configuration du format avec couleurs si disponible
    try:
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
    except ImportError:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Handler console
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    # Logger root
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Supprimer les handlers existants
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    root_logger.addHandler(handler)
    
    # Logger du pipeline
    pipeline_logger = logging.getLogger('src')
    pipeline_logger.setLevel(log_level)


# ==============================================================================
# GESTION DES COULEURS
# ==============================================================================

class Colors:
    """Codes de couleurs ANSI pour la console."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    
    @staticmethod
    def enabled() -> bool:
        """Vérifie si les couleurs sont activées."""
        return sys.stdout.isatty() and not os.environ.get('NO_COLOR')


def color_text(text: str, color: str) -> str:
    """
    Colorie un texte si les couleurs sont activées.
    
    Args:
        text: Texte à colorier
        color: Code de couleur
        
    Returns:
        str: Texte colorié ou non
    """
    if Colors.enabled():
        return f"{color}{text}{Colors.ENDC}"
    return text


def success(text: str) -> str:
    """Texte de succès en vert."""
    return color_text(text, Colors.GREEN)


def error(text: str) -> str:
    """Texte d'erreur en rouge."""
    return color_text(text, Colors.FAIL)


def warning(text: str) -> str:
    """Texte d'avertissement en jaune."""
    return color_text(text, Colors.WARNING)


def info(text: str) -> str:
    """Texte d'information en bleu."""
    return color_text(text, Colors.BLUE)


def header(text: str) -> str:
    """Texte d'en-tête en gras."""
    return color_text(text, Colors.BOLD)


# ==============================================================================
# GESTION DES PROFILES
# ==============================================================================

def load_profile(profile_name: str) -> bool:
    """
    Charge un profile de configuration.
    
    Args:
        profile_name: Nom du profile
        
    Returns:
        bool: True si chargé avec succès
    """
    profile_path = Path.home() / f".{CLI_NAME}" / f"{profile_name}.json"
    
    if not profile_path.exists():
        # Essayer dans le répertoire courant
        profile_path = Path(f".{CLI_NAME}") / f"{profile_name}.json"
    
    if not profile_path.exists():
        _cli_logger.log_error(
            f"Profile '{profile_name}' not found",
            None,
            "profile_not_found",
            profile_name=profile_name
        )
        click.echo(f"❌ Profile '{profile_name}' not found", err=True)
        return False
    
    try:
        with open(profile_path, 'r') as f:
            profile_data = json.load(f)
        
        # Appliquer les paramètres du profile
        for key, value in profile_data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        # Recharger les settings (si la fonction existe)
        try:
            from src.config.settings import reload_settings
            reload_settings()
        except ImportError:
            # Fallback: rien
            pass
        
        _cli_logger.log_info(
            f"Profile '{profile_name}' loaded",
            "profile_loaded",
            profile_name=profile_name
        )
        click.echo(success(f"✅ Profile '{profile_name}' loaded"))
        return True
        
    except Exception as e:
        _cli_logger.log_error(
            f"Failed to load profile: {str(e)}",
            e,
            "profile_load_failed",
            profile_name=profile_name
        )
        click.echo(error(f"❌ Failed to load profile: {e}"), err=True)
        return False


def save_profile(profile_name: str) -> bool:
    """
    Sauvegarde le profile actuel.
    
    Args:
        profile_name: Nom du profile
        
    Returns:
        bool: True si sauvegardé avec succès
    """
    profile_dir = Path.home() / f".{CLI_NAME}"
    profile_dir.mkdir(exist_ok=True)
    
    profile_path = profile_dir / f"{profile_name}.json"
    
    try:
        # Récupérer les settings manuellement de manière robuste
        settings_dict = {}
        attrs = ['env', 'debug', 'database', 'redis', 'llm', 'chroma', 'pipeline', 'api', 'security', 'logging']
        for attr in attrs:
            if hasattr(settings, attr):
                val = getattr(settings, attr)
                if hasattr(val, 'model_dump'):
                    settings_dict[attr] = val.model_dump()
                elif hasattr(val, 'to_dict'):
                    settings_dict[attr] = val.to_dict()
                elif hasattr(val, 'dict'):
                    settings_dict[attr] = val.dict()
                elif hasattr(val, 'value'):
                    settings_dict[attr] = val.value
                elif isinstance(val, (dict, list, str, int, float, bool, type(None))):
                    settings_dict[attr] = val
                else:
                    settings_dict[attr] = str(val)
        
        with open(profile_path, 'w') as f:
            json.dump(settings_dict, f, indent=2, default=str)
        
        _cli_logger.log_info(
            f"Profile '{profile_name}' saved to {profile_path}",
            "profile_saved",
            profile_name=profile_name
        )
        click.echo(success(f"✅ Profile '{profile_name}' saved to {profile_path}"))
        return True
        
    except Exception as e:
        _cli_logger.log_error(
            f"Failed to save profile: {str(e)}",
            e,
            "profile_save_failed",
            profile_name=profile_name
        )
        click.echo(error(f"❌ Failed to save profile: {e}"), err=True)
        return False


# ==============================================================================
# COMMANDES PRINCIPALES
# ==============================================================================

class CliContext:
    """Contexte de la CLI pour partager des données entre les commandes."""
    
    def __init__(self):
        self.start_time = time.time()
        self.commands_executed = 0
        self.errors = 0
        self.metrics: Dict[str, Any] = {}
    
    def get_uptime(self) -> float:
        """Retourne le temps d'exécution de la CLI."""
        return time.time() - self.start_time


pass_context = click.make_pass_decorator(CliContext, ensure=True)


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.option('--quiet', '-q', is_flag=True, help='Quiet output')
@click.option('--profile', '-p', help='Load configuration profile')
@click.option('--no-color', is_flag=True, help='Disable colored output')
@click.option('--json-logs', is_flag=True, help='Output logs in JSON format')
@click.version_option(version=VERSION, prog_name=CLI_NAME)
@pass_context
def cli(ctx: CliContext, verbose: bool, quiet: bool, profile: Optional[str],
        no_color: bool, json_logs: bool):
    """
    Smart Contract Dev Pipeline - CLI Tool
    
    Tools for managing and executing the smart contract development pipeline.
    
    Examples:
    
    \b
    # Initialize the database
    pipeline db-init
    
    \b
    # Create a new project
    pipeline project-create MyProject --spec spec.yaml
    
    \b
    # Run the pipeline
    pipeline run project_123
    
    \b
    # Check status
    pipeline status
    
    \b
    # Load a profile
    pipeline --profile production status
    """
    # Désactiver les couleurs
    if no_color:
        os.environ['NO_COLOR'] = '1'
    
    # Configurer le logging
    configure_cli_logging(verbose, quiet)
    
    # Configurer les logs JSON
    if json_logs:
        _cli_logger.json_output = True
    
    # Charger le profile
    if profile:
        load_profile(profile)
    
    # Stocker les métriques dans le contexte
    ctx.metrics["verbose"] = verbose
    ctx.metrics["quiet"] = quiet
    ctx.metrics["profile"] = profile
    ctx.metrics["no_color"] = no_color
    ctx.metrics["json_logs"] = json_logs
    
    # Logging structuré du démarrage de la CLI
    _cli_logger.log_info(
        "CLI started",
        "cli_start",
        verbose=verbose,
        quiet=quiet,
        profile=profile,
        no_color=no_color
    )


# ==============================================================================
# COMMANDES D'AIDE AVANCÉE
# ==============================================================================

@cli.command()
@pass_context
def help(ctx: CliContext):
    """Affiche l'aide détaillée avec des exemples."""
    click.echo(header("=" * 60))
    click.echo(header(f"Smart Contract Dev Pipeline v{VERSION}"))
    click.echo(header("=" * 60))
    
    click.echo("\n📖 Available Commands:")
    click.echo("  " + "-" * 50)
    
    # Récupérer toutes les commandes
    for cmd_name, cmd in cli.commands.items():
        doc = cmd.help or "No description available"
        click.echo(f"  {cmd_name:20} {doc}")
    
    click.echo("\n📚 Examples:")
    click.echo("  " + "-" * 50)
    click.echo("  # Initialize database")
    click.echo("  pipeline db-init --seed")
    click.echo()
    click.echo("  # Create a project")
    click.echo("  pipeline project-create MyProject --chain ethereum")
    click.echo()
    click.echo("  # Run the pipeline")
    click.echo("  pipeline run project_123 --parallel")
    click.echo()
    click.echo("  # Audit a contract")
    click.echo("  pipeline audit contracts/Token.sol --level full")
    
    click.echo("\n" + "=" * 60)


@cli.command()
@pass_context
def version(ctx: CliContext):
    """Affiche la version détaillée."""
    env_value = getattr(settings, 'env', 'development')
    env_str = env_value.value if hasattr(env_value, 'value') else str(env_value)
    debug_value = getattr(settings, 'debug', False)
    
    click.echo(f"Smart Contract Dev Pipeline v{VERSION}")
    click.echo(f"Python: {sys.version.split()[0]}")
    click.echo(f"Environment: {env_str}")
    click.echo(f"Debug: {debug_value}")
    
    _cli_logger.log_info(
        "Version command executed",
        "cmd_version",
        version=VERSION,
        environment=env_str
    )


# ==============================================================================
# COMMANDES DE PROFILE
# ==============================================================================

@cli.group()
def profile():
    """Gestion des profiles de configuration."""
    pass


@profile.command('list')
@pass_context
def profile_list(ctx: CliContext):
    """Liste les profiles disponibles."""
    click.echo("📋 Available profiles:")
    click.echo("  " + "-" * 40)
    
    found = False
    
    # Profiles globaux
    global_dir = Path.home() / f".{CLI_NAME}"
    if global_dir.exists():
        for profile_file in global_dir.glob("*.json"):
            click.echo(f"  {profile_file.stem} (global)")
            found = True
    
    # Profiles locaux
    local_dir = Path(f".{CLI_NAME}")
    if local_dir.exists():
        for profile_file in local_dir.glob("*.json"):
            click.echo(f"  {profile_file.stem} (local)")
            found = True
    
    if not found:
        click.echo("  No profiles found")
        click.echo(f"  Run 'pipeline profile create <name>' to create one")


@profile.command('create')
@click.argument('name')
@pass_context
def profile_create(ctx: CliContext, name: str):
    """Crée un nouveau profile."""
    _cli_logger.log_info(
        f"Creating profile: {name}",
        "profile_create_start",
        profile_name=name
    )
    
    if save_profile(name):
        _cli_logger.log_info(
            f"Profile '{name}' created successfully",
            "profile_create_completed",
            profile_name=name
        )
        click.echo(f"✅ Profile '{name}' created successfully")
    else:
        click.echo(error("❌ Failed to create profile"), err=True)


@profile.command('load')
@click.argument('name')
@pass_context
def profile_load(ctx: CliContext, name: str):
    """Charge un profile."""
    _cli_logger.log_info(
        f"Loading profile: {name}",
        "profile_load_start",
        profile_name=name
    )
    
    if load_profile(name):
        click.echo(f"✅ Profile '{name}' loaded successfully")
    else:
        click.echo(error(f"❌ Profile '{name}' not found"), err=True)


@profile.command('delete')
@click.argument('name')
@click.option('--yes', is_flag=True, help='Skip confirmation')
@pass_context
def profile_delete(ctx: CliContext, name: str, yes: bool):
    """Supprime un profile."""
    profile_dir = Path.home() / f".{CLI_NAME}"
    profile_path = profile_dir / f"{name}.json"
    
    if not profile_path.exists():
        # Essayer dans le répertoire local
        profile_dir = Path(f".{CLI_NAME}")
        profile_path = profile_dir / f"{name}.json"
    
    if not profile_path.exists():
        _cli_logger.log_warning(
            f"Profile '{name}' not found",
            "profile_not_found",
            profile_name=name
        )
        click.echo(error(f"❌ Profile '{name}' not found"), err=True)
        return
    
    if not yes:
        click.echo(warning(f"⚠️  Delete profile '{name}'?"))
        if not click.confirm("Are you sure?"):
            click.echo("Cancelled.")
            return
    
    profile_path.unlink()
    
    _cli_logger.log_info(
        f"Profile '{name}' deleted",
        "profile_deleted",
        profile_name=name
    )
    click.echo(success(f"✅ Profile '{name}' deleted"))


# ==============================================================================
# COMMANDES DE MÉTRIQUES
# ==============================================================================

@cli.command()
@pass_context
def metrics(ctx: CliContext):
    """Affiche les métriques d'utilisation de la CLI."""
    click.echo("📊 CLI Metrics:")
    click.echo("  " + "-" * 40)
    click.echo(f"  Uptime: {ctx.get_uptime():.2f}s")
    click.echo(f"  Commands executed: {ctx.commands_executed}")
    click.echo(f"  Errors: {ctx.errors}")
    
    if ctx.metrics:
        click.echo("\n  Context:")
        for key, value in ctx.metrics.items():
            click.echo(f"    {key}: {value}")
    
    # Récupérer les métriques du logger structuré
    logger_metrics = _cli_logger.get_metrics()
    click.echo(f"\n  Logger Events: {logger_metrics.get('event_count', 0)}")
    click.echo(f"  Logger Errors: {logger_metrics.get('error_count', 0)}")


# ==============================================================================
# INCLUSION DES COMMANDES
# ==============================================================================

# Ajouter toutes les commandes du module commands
cli.add_command(commands_cli)


# ==============================================================================
# GESTION DES ERREURS
# ==============================================================================

@cli.resultcallback()
def handle_result(result, **kwargs):
    """Callback de gestion des résultats."""
    pass


def handle_exception(exc, ctx: Optional[CliContext] = None):
    """
    Gestionnaire d'exceptions pour la CLI.
    
    Args:
        exc: Exception à gérer
        ctx: Contexte CLI (optionnel)
    """
    if ctx:
        ctx.errors += 1
    
    if isinstance(exc, PipelineError):
        _cli_logger.log_error(
            f"Pipeline Error: {str(exc)}",
            exc,
            "pipeline_error"
        )
        click.echo(error(f"❌ Pipeline Error: {exc}"), err=True)
        if hasattr(exc, 'details') and exc.details:
            import json
            click.echo(f"   Details: {json.dumps(exc.details, indent=2)}", err=True)
    elif isinstance(exc, KeyboardInterrupt):
        _cli_logger.log_warning("Interrupted by user", "keyboard_interrupt")
        click.echo("\n⚠️  Interrupted by user", err=True)
    elif isinstance(exc, click.ClickException):
        # Les exceptions Click sont déjà formatées
        raise
    elif isinstance(exc, click.Abort):
        _cli_logger.log_warning("Aborted", "cli_aborted")
        click.echo("\n⚠️  Aborted", err=True)
    else:
        debug_value = getattr(settings, 'debug', False)
        _cli_logger.log_error(
            f"Error: {str(exc)}",
            exc,
            "cli_error"
        )
        click.echo(error(f"❌ Error: {exc}"), err=True)
        if debug_value:
            import traceback
            click.echo(traceback.format_exc(), err=True)


def main():
    """
    Point d'entrée principal de la CLI.
    """
    ctx = CliContext()
    
    try:
        # Configurer le logging par défaut
        configure_cli_logging()
        
        # Logging du démarrage
        _cli_logger.log_info(
            "CLI main() started",
            "main_start",
            version=VERSION
        )
        
        # Exécuter la CLI avec le contexte (standalone_mode=False permet de capturer les exceptions ici)
        cli(obj=ctx, standalone_mode=False)
        
        # Mettre à jour les métriques
        ctx.commands_executed += 1
        
        _cli_logger.log_info(
            f"CLI completed in {ctx.get_uptime():.2f}s",
            "main_completed",
            uptime=ctx.get_uptime(),
            commands_executed=ctx.commands_executed,
            errors=ctx.errors
        )
        
    except Exception as e:
        handle_exception(e, ctx)
        sys.exit(1)
    finally:
        # Afficher les métriques en mode verbose
        if ctx.metrics.get("verbose"):
            click.echo(f"\n⏱️  CLI executed in {ctx.get_uptime():.2f}s", err=True)


# ==============================================================================
# POINT D'ENTRÉE
# ==============================================================================

if __name__ == "__main__":
    main()