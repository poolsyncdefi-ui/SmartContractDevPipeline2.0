# src/cli/commands.py
import click
import asyncio
from pathlib import Path

@click.group()
def cli():
    """Smart Contract Dev Pipeline 2.0 CLI."""
    pass

@cli.command()
@click.option('--path', default='.', help='Chemin du projet')
def init(path):
    """Initialise un nouveau projet."""
    config_path = Path(path) / "project_config.yaml"
    if config_path.exists():
        click.echo("Fichier de configuration déjà existant.")
        return
    
    template = """project:
  name: my_project
  description: Mon projet de smart contract
  chain: ethereum
  frontend: false

team_requirements:
  - skill: erc20
    count: 1
    priority: 1

sprint_workflow:
  - step: 1
    name: "Génération du contrat"
    agent_role: erc20
    action: generate
    depends_on: []
    requires_human_validation: true

quality_gates:
  test_coverage: 80
  gas_increase_limit: 10
  max_cyclomatic_complexity: 10
  slither_severity: high
  formal_verification: false
"""
    config_path.write_text(template)
    click.echo(f"✅ Fichier {config_path} créé.")

@cli.command()
@click.option('--config', default='project_config.yaml', help='Fichier de configuration')
def plan(config):
    """Analyse les besoins et propose une équipe."""
    click.echo("📋 Planification de l'équipe...")
    # À implémenter
    click.echo("✅ Équipe proposée : 1 agent (ERC20)")

@cli.command()
@click.option('--config', default='project_config.yaml')
@click.option('--sprint-id', required=True)
@click.option('--dry-run', is_flag=True)
def sprint(config, sprint_id, dry_run):
    """Lance un sprint."""
    if dry_run:
        click.echo(f"🏃 Mode dry-run pour le sprint {sprint_id}")
        click.echo("✅ Sprint planifié avec succès.")
        return
    click.echo(f"🚀 Lancement du sprint {sprint_id}...")
    # À implémenter

@cli.command()
def status():
    """Affiche l'état du sprint en cours."""
    click.echo("📊 Statut du sprint : EN COURS")
    click.echo("   Tâches : 0/5 terminées")