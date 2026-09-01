# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - CLI Main Entry Point
# ==============================================================================
# Fichier: src/cli/main.py
# Description: Point d'entrée de la CLI avec les commandes principales.
#              Configuration du logging, gestion des erreurs, couleurs,
#              profiles et métriques.
# ==============================================================================

import click
import logging
import sys
import asyncio
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import json
import time

from src.cli.commands import cli as commands_cli
from src.config.settings import settings, load_settings, reload_settings
from src.core.exceptions import PipelineError

# ==============================================================================
# CONSTANTES
# ==============================================================================

VERSION = "2.0.0"
CLI_NAME = "pipeline"


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
    elif verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    
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
        click.echo(f"❌ Profile '{profile_name}' not found", err=True)
        return False
    
    try:
        with open(profile_path, 'r') as f:
            profile_data = json.load(f)
        
        # Appliquer les paramètres du profile
        for key, value in profile_data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        # Recharger les settings
        reload_settings()
        
        click.echo(success(f"✅ Profile '{profile_name}' loaded"))
        return True
        
    except Exception as e:
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
        # Récupérer les settings
        settings_dict = settings.to_dict(show_secrets=False)
        
        with open(profile_path, 'w') as f:
            json.dump(settings_dict, f, indent=2, default=str)
        
        click.echo(success(f"✅ Profile '{profile_name}' saved to {profile_path}"))
        return True
        
    except Exception as e:
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
        # TODO: Implémenter les logs JSON
        pass
    
    # Charger le profile
    if profile:
        load_profile(profile)
    
    # Stocker les métriques dans le contexte
    ctx.metrics["verbose"] = verbose
    ctx.metrics["quiet"] = quiet
    ctx.metrics["profile"] = profile
    ctx.metrics["no_color"] = no_color


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
    click.echo(f"Smart Contract Dev Pipeline v{VERSION}")
    click.echo(f"Python: {sys.version.split()[0]}")
    click.echo(f"Environment: {settings.env.value}")
    click.echo(f"Debug: {settings.debug}")


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
    
    # Profiles globaux
    global_dir = Path.home() / f".{CLI_NAME}"
    if global_dir.exists():
        for profile_file in global_dir.glob("*.json"):
            click.echo(f"  {profile_file.stem} (global)")
    
    # Profiles locaux
    local_dir = Path(f".{CLI_NAME}")
    if local_dir.exists():
        for profile_file in local_dir.glob("*.json"):
            click.echo(f"  {profile_file.stem} (local)")
    
    if not any([global_dir.exists(), local_dir.exists()]):
        click.echo("  No profiles found")
        click.echo(f"  Run 'pipeline profile create <name>' to create one")


@profile.command('create')
@click.argument('name')
@pass_context
def profile_create(ctx: CliContext, name: str):
    """Crée un nouveau profile."""
    if save_profile(name):
        click.echo(f"✅ Profile '{name}' created successfully")
    else:
        click.echo(error("❌ Failed to create profile"), err=True)


@profile.command('load')
@click.argument('name')
@pass_context
def profile_load(ctx: CliContext, name: str):
    """Charge un profile."""
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
        click.echo(error(f"❌ Profile '{name}' not found"), err=True)
        return
    
    if not yes:
        click.echo(warning(f"⚠️  Delete profile '{name}'?"))
        if not click.confirm("Are you sure?"):
            click.echo("Cancelled.")
            return
    
    profile_path.unlink()
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
        click.echo(error(f"❌ Pipeline Error: {exc}"), err=True)
        if hasattr(exc, 'details') and exc.details:
            import json
            click.echo(f"   Details: {json.dumps(exc.details, indent=2)}", err=True)
    elif isinstance(exc, KeyboardInterrupt):
        click.echo("\n⚠️  Interrupted by user", err=True)
    elif isinstance(exc, click.ClickException):
        # Les exceptions Click sont déjà formatées
        raise
    elif isinstance(exc, click.Abort):
        click.echo("\n⚠️  Aborted", err=True)
    else:
        click.echo(error(f"❌ Error: {exc}"), err=True)
        if settings.debug:
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
        
        # Exécuter la CLI avec le contexte
        cli(obj=ctx)
        
        # Mettre à jour les métriques
        ctx.commands_executed += 1
        
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