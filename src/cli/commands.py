# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - CLI Commands
# ==============================================================================
# Fichier: src/cli/commands.py
# Description: Commandes Click pour la CLI.
#              Opérations de gestion, exécution et maintenance du pipeline.
#              Support des projets, tâches, sprints, artefacts, compétences,
#              configuration, notifications et webhooks.
#              Version refactorisée avec logger structuré et horodatages timezone-aware.
# ==============================================================================

import click
import asyncio
import sys
import json
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from src.config.settings import settings
from src.db.database import init_database, check_db_connection, get_async_session
from src.db.migrations import run_migrations, reset_models, get_current_version
from src.models.project import ProjectModel, ProjectStatus, ProjectChain
from src.models.task import TaskModel, TaskState, TaskPriority, TaskType
from src.orchestration.workflow_engine import WorkflowEngine
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.status_manager import normalize_status, status_manager

# ==============================================================================
# LOGGER STRUCTURÉ POUR LA CLI
# ==============================================================================

_cli_logger = StructuredLogger(
    component_name="CLI",
    log_level=LogLevel.INFO
)


# ==============================================================================
# OPTIONS COMMUNES
# ==============================================================================

def common_options(f):
    """Options communes pour les commandes."""
    options = [
        click.option('--verbose', '-v', is_flag=True, help='Verbose output'),
        click.option('--quiet', '-q', is_flag=True, help='Quiet output'),
        click.option('--json', '-j', 'output_json', is_flag=True, help='Output as JSON'),
    ]
    for option in reversed(options):
        f = option(f)
    return f


def output_result(result: Any, output_json: bool = False) -> None:
    """
    Affiche un résultat.
    
    Args:
        result: Résultat à afficher
        output_json: Sortie en JSON
    """
    if output_json:
        if hasattr(result, 'to_dict'):
            click.echo(json.dumps(result.to_dict(), indent=2))
        else:
            click.echo(json.dumps(result, indent=2, default=str))
    elif isinstance(result, dict):
        for key, value in result.items():
            click.echo(f"{key}: {value}")
    elif isinstance(result, list):
        for item in result:
            click.echo(f"- {item}")
    else:
        click.echo(result)


def require_db(f):
    """Décorateur pour s'assurer que la base de données est connectée."""
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        if not asyncio.run(check_db_connection()):
            click.echo("❌ Database not connected. Run 'pipeline db-init' first.", err=True)
            ctx.exit(1)
        return ctx.invoke(f, *args, **kwargs)
    return wrapper


# ==============================================================================
# COMMANDES PRINCIPALES
# ==============================================================================

@click.group()
def cli():
    """Smart Contract Dev Pipeline CLI."""
    _cli_logger.log_info("CLI session started", "cli_start")
    pass


# ==============================================================================
# COMMANDES DE GESTION
# ==============================================================================

@cli.command()
@common_options
def status(verbose: bool, quiet: bool, output_json: bool):
    """Affiche le statut du pipeline."""
    _cli_logger.log_info("Executing status command", "cmd_status")
    
    result = {
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    # Base de données
    click.echo("\n📊 Database:")
    try:
        db_ok = asyncio.run(check_db_connection())
        result["database"] = {"status": "connected" if db_ok else "disconnected"}
        if db_ok:
            version = asyncio.run(get_current_version())
            result["database"]["schema_version"] = version or "unknown"
            click.echo(f"  ✅ Connected (schema: {version or 'unknown'})")
        else:
            click.echo("  ❌ Not connected")
            result["database"]["status"] = "disconnected"
    except Exception as e:
        click.echo(f"  ❌ Error: {e}")
        result["database"] = {"status": "error", "error": str(e)}
        _cli_logger.log_error("Database check failed", e, "db_check_failed")
    
    # Configuration
    click.echo("\n⚙️ Configuration:")
    config = {
        "workspace": str(getattr(settings.pipeline, 'default_workspace', './workspace')),
        "database_url": getattr(settings.database, 'url', 'postgresql://...'),
        "redis_url": getattr(settings.redis, 'url', 'redis://localhost:6379/0'),
        "ollama_url": getattr(settings.llm, 'ollama_url', 'http://localhost:11434'),
        "environment": getattr(settings, 'env', 'development'),
        "debug": getattr(settings, 'debug', False)
    }
    result["config"] = config
    for key, value in config.items():
        click.echo(f"  {key}: {value}")
    
    # Statistiques
    async def get_stats():
        from sqlalchemy import select, func
        from src.models.project import ProjectModel
        from src.models.task import TaskModel, TaskState
        
        async with get_async_session() as session:
            projects = await session.execute(select(func.count()).select_from(ProjectModel))
            tasks = await session.execute(select(func.count()).select_from(TaskModel))
            completed = await session.execute(
                select(func.count()).select_from(TaskModel)
                .where(TaskModel.state == TaskState.SUCCESS)
            )
            return {
                "projects": projects.scalar() or 0,
                "tasks": tasks.scalar() or 0,
                "completed_tasks": completed.scalar() or 0
            }
    
    try:
        stats = asyncio.run(get_stats())
        result["stats"] = stats
        click.echo("\n📊 Statistics:")
        click.echo(f"  Projects: {stats['projects']}")
        click.echo(f"  Tasks: {stats['tasks']}")
        click.echo(f"  Completed tasks: {stats['completed_tasks']}")
    except Exception as e:
        click.echo(f"  ❌ Error getting stats: {e}")
        _cli_logger.log_warning(f"Failed to get stats: {e}", "stats_failed")
    
    if output_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo("\n" + "=" * 60)


@cli.command()
@common_options
@click.option('--reset', is_flag=True, help='Reset database (drop and recreate)')
@click.option('--seed', is_flag=True, help='Seed database with initial data')
def db_init(reset: bool, seed: bool, verbose: bool, quiet: bool, output_json: bool):
    """Initialise la base de données."""
    _cli_logger.log_info(
        "Executing db-init command",
        "cmd_db_init",
        reset=reset,
        seed=seed
    )
    click.echo("📊 Initializing database...")
    
    if reset:
        click.echo("⚠️  Resetting database (all data will be lost!)")
        if not click.confirm("Are you sure?"):
            click.echo("Cancelled.")
            return
        asyncio.run(reset_models())
        click.echo("✅ Database reset")
    
    asyncio.run(init_database(create_tables=True))
    
    if seed:
        click.echo("📊 Seeding database...")
        try:
            from src.db.seeds import seed_all
            asyncio.run(seed_all())
            click.echo("✅ Database seeded")
        except ImportError:
            click.echo("⚠️  Seed module not found, skipping.")
        except Exception as e:
            _cli_logger.log_error("Seeding failed", e, "seed_failed")
            click.echo(f"⚠️  Seeding failed: {e}")
    
    click.echo("✅ Database initialized")
    
    if output_json:
        click.echo(json.dumps({"status": "success", "action": "db_init"}))


@cli.command()
@common_options
def db_migrate(verbose: bool, quiet: bool, output_json: bool):
    """Exécute les migrations de la base de données."""
    _cli_logger.log_info("Executing db-migrate command", "cmd_db_migrate")
    click.echo("📊 Running migrations...")
    
    try:
        asyncio.run(run_migrations())
        current_version = asyncio.run(get_current_version())
        click.echo(f"✅ Migrations completed (version: {current_version})")
        
        if output_json:
            click.echo(json.dumps({
                "status": "success",
                "action": "db_migrate",
                "version": current_version
            }))
    except Exception as e:
        _cli_logger.log_error("Migration failed", e, "migration_failed")
        click.echo(f"❌ Migration failed: {e}")
        if output_json:
            click.echo(json.dumps({"status": "error", "error": str(e)}))


@cli.command()
@common_options
@click.argument('version')
def db_rollback(version: str, verbose: bool, quiet: bool, output_json: bool):
    """Rollback vers une version spécifique."""
    _cli_logger.log_info(
        f"Executing db-rollback command to version {version}",
        "cmd_db_rollback",
        version=version
    )
    click.echo(f"📊 Rolling back to version {version}...")
    
    try:
        from src.db.migrations import rollback_to_version
        asyncio.run(rollback_to_version(version))
        click.echo(f"✅ Rollback to {version} completed")
        
        if output_json:
            click.echo(json.dumps({
                "status": "success",
                "action": "db_rollback",
                "version": version
            }))
    except Exception as e:
        _cli_logger.log_error("Rollback failed", e, "rollback_failed")
        click.echo(f"❌ Rollback failed: {e}")
        if output_json:
            click.echo(json.dumps({"status": "error", "error": str(e)}))


# ==============================================================================
# COMMANDES DE PROJET
# ==============================================================================

@cli.command()
@common_options
@click.argument('name')
@click.option('--spec', '-s', help='Path to YAML specification file')
@click.option('--config', '-c', help='Path to JSON config file')
@click.option('--chain', help='Blockchain (ethereum, polygon, etc.)')
@click.option('--tags', help='Comma-separated tags')
@click.option('--priority', default='medium', help='Priority (low, medium, high, critical)')
@click.option('--category', default='other', help='Category (defi, nft, gaming, dao, etc.)')
def project_create(name: str, spec: Optional[str], config: Optional[str], 
                   chain: Optional[str], tags: Optional[str], priority: str,
                   category: str, verbose: bool, quiet: bool, output_json: bool):
    """Crée un nouveau projet."""
    _cli_logger.log_info(
        f"Executing project-create command for {name}",
        "cmd_project_create",
        project_name=name
    )
    click.echo(f"📋 Creating project: {name}")
    
    # Charger la spécification
    spec_content = ""
    if spec:
        spec_path = Path(spec)
        if not spec_path.exists():
            _cli_logger.log_error(
                f"Specification file not found: {spec}",
                None,
                "spec_file_not_found"
            )
            click.echo(f"❌ Specification file not found: {spec}")
            return
        spec_content = spec_path.read_text()
    else:
        # Template par défaut
        spec_content = f"""project:
  name: {name}
  chain: {chain or 'ethereum'}
  version: 1.0.0
  description: "A smart contract project"
  category: {category}
  priority: {priority}
  tags: {tags or ''}
"""
    
    # Charger la configuration
    config_data = {}
    if config:
        config_path = Path(config)
        if not config_path.exists():
            _cli_logger.log_error(
                f"Config file not found: {config}",
                None,
                "config_file_not_found"
            )
            click.echo(f"❌ Config file not found: {config}")
            return
        try:
            if config_path.suffix == '.json':
                config_data = json.loads(config_path.read_text())
            elif config_path.suffix in ['.yml', '.yaml']:
                config_data = yaml.safe_load(config_path.read_text())
        except Exception as e:
            _cli_logger.log_error(f"Error loading config: {e}", e, "config_load_failed")
            click.echo(f"❌ Error loading config: {e}")
            return
    
    # Créer le projet manuellement
    async def save_project():
        import uuid
        from src.models.project import ProjectPriority, ProjectCategory, ProjectChain
        
        async with get_async_session() as session:
            project = ProjectModel(
                id=str(uuid.uuid4()),
                name=name,
                spec_yaml=spec_content,
                config=config_data,
                chain=ProjectChain(chain) if chain else ProjectChain.ETHEREUM,
                priority=ProjectPriority(priority) if priority else ProjectPriority.MEDIUM,
                category=ProjectCategory(category) if category else ProjectCategory.OTHER,
                status=ProjectStatus.CREATED
            )
            # Appliquer les tags
            if tags:
                project.set_tags([t.strip() for t in tags.split(',')])
            
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project
    
    try:
        saved_project = asyncio.run(save_project())
        click.echo(f"✅ Project created: {saved_project.id}")
        click.echo(f"   Name: {saved_project.name}")
        click.echo(f"   Chain: {saved_project.chain.value if saved_project.chain else 'ethereum'}")
        click.echo(f"   Status: {saved_project.status.value if saved_project.status else 'CREATED'}")
        click.echo(f"   Priority: {saved_project.priority.value if saved_project.priority else 'medium'}")
        click.echo(f"   Category: {saved_project.category.value if saved_project.category else 'other'}")
        
        _cli_logger.log_info(
            f"Project created: {saved_project.id}",
            "project_created",
            project_id=saved_project.id,
            project_name=name
        )
        
        if output_json:
            click.echo(json.dumps(saved_project.to_dict(), indent=2))
            
    except Exception as e:
        _cli_logger.log_error(f"Error creating project: {e}", e, "project_create_failed")
        click.echo(f"❌ Error creating project: {e}")
        if output_json:
            click.echo(json.dumps({"status": "error", "error": str(e)}))


@cli.command()
@common_options
@click.argument('project_id')
def project_show(project_id: str, verbose: bool, quiet: bool, output_json: bool):
    """Affiche les détails d'un projet."""
    _cli_logger.log_info(
        f"Executing project-show command for {project_id}",
        "cmd_project_show",
        project_id=project_id
    )
    click.echo(f"📋 Showing project: {project_id}")
    
    async def get_project():
        from sqlalchemy import select
        from src.models.project import ProjectModel
        
        async with get_async_session() as session:
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )
            return result.scalar_one_or_none()
    
    project = asyncio.run(get_project())
    
    if not project:
        _cli_logger.log_warning(f"Project not found: {project_id}", "project_not_found")
        click.echo(f"❌ Project {project_id} not found")
        return
    
    if output_json:
        click.echo(json.dumps(project.to_dict(include_config=True), indent=2))
    else:
        click.echo(f"\n📊 Project Details:")
        click.echo(f"  ID: {project.id}")
        click.echo(f"  Name: {project.name}")
        click.echo(f"  Description: {project.description}")
        click.echo(f"  Status: {project.status.value if project.status else 'N/A'}")
        click.echo(f"  Priority: {project.priority.value if project.priority else 'N/A'}")
        click.echo(f"  Category: {project.category.value if project.category else 'N/A'}")
        click.echo(f"  Chain: {project.chain.value if project.chain else 'N/A'}")
        click.echo(f"  Version: {project.version}")
        click.echo(f"  Tags: {', '.join(project.get_tags())}")
        click.echo(f"  Tasks: {project.task_count} (completed: {project.completed_task_count})")
        click.echo(f"  Security score: {project.security_score}")
        click.echo(f"  Quality score: {project.quality_score}")
        click.echo(f"  Completion rate: {project.completion_rate:.1f}%")
        click.echo(f"  Created: {project.created_at.isoformat() if project.created_at else 'N/A'}")
        click.echo(f"  Updated: {project.updated_at.isoformat() if project.updated_at else 'N/A'}")


@cli.command()
@common_options
@click.option('--status', help='Filter by status')
@click.option('--priority', help='Filter by priority')
@click.option('--category', help='Filter by category')
@click.option('--chain', help='Filter by chain')
@click.option('--limit', default=20, help='Limit results')
def project_list(status: Optional[str], priority: Optional[str], 
                 category: Optional[str], chain: Optional[str], 
                 limit: int, verbose: bool, quiet: bool, output_json: bool):
    """Liste tous les projets."""
    _cli_logger.log_info("Executing project-list command", "cmd_project_list")
    click.echo("📋 Listing projects...")
    
    async def list_projects():
        from sqlalchemy import select
        from src.models.project import ProjectModel
        
        async with get_async_session() as session:
            query = select(ProjectModel)
            if status:
                query = query.where(ProjectModel.status == status)
            if priority:
                query = query.where(ProjectModel.priority == priority)
            if category:
                query = query.where(ProjectModel.category == category)
            if chain:
                query = query.where(ProjectModel.chain == chain)
            query = query.limit(limit)
            result = await session.execute(query)
            return result.scalars().all()
    
    projects = asyncio.run(list_projects())
    
    if output_json:
        click.echo(json.dumps([p.to_dict() for p in projects], indent=2))
    else:
        if not projects:
            click.echo("No projects found.")
            return
        
        click.echo(f"\n📊 Found {len(projects)} projects:")
        click.echo("  ID | Name | Status | Priority | Tasks | Completion | Created")
        click.echo("  " + "-" * 80)
        for p in projects:
            click.echo(f"  {p.id[:8]} | {p.name[:20]} | {p.status.value if p.status else 'N/A':<8} | "
                       f"{p.priority.value if p.priority else 'medium':<8} | {p.task_count:>5} | "
                       f"{p.completion_rate:>5.0f}% | "
                       f"{p.created_at.strftime('%Y-%m-%d') if p.created_at else 'N/A'}")


@cli.command()
@common_options
@click.argument('project_id')
@click.option('--status', help='New status')
@click.option('--name', help='New name')
@click.option('--description', help='New description')
@click.option('--priority', help='New priority')
@click.option('--category', help='New category')
@click.option('--chain', help='New chain')
@click.option('--tags', help='New tags (comma-separated)')
def project_update(project_id: str, status: Optional[str], name: Optional[str], 
                   description: Optional[str], priority: Optional[str],
                   category: Optional[str], chain: Optional[str],
                   tags: Optional[str], verbose: bool, quiet: bool, output_json: bool):
    """Met à jour un projet."""
    _cli_logger.log_info(
        f"Executing project-update command for {project_id}",
        "cmd_project_update",
        project_id=project_id
    )
    click.echo(f"📋 Updating project: {project_id}")
    
    updates = {}
    if status:
        updates["status"] = status
    if name:
        updates["name"] = name
    if description:
        updates["description"] = description
    if priority:
        updates["priority"] = priority
    if category:
        updates["category"] = category
    if chain:
        updates["chain"] = chain
    if tags:
        updates["tags"] = [t.strip() for t in tags.split(',')]
    
    if not updates:
        click.echo("❌ No updates specified")
        return
    
    async def update_project():
        from sqlalchemy import select
        from src.models.project import ProjectModel, ProjectStatus, ProjectPriority, ProjectCategory, ProjectChain
        
        async with get_async_session() as session:
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                return None
            
            for key, value in updates.items():
                if key == "status":
                    project.update_status(ProjectStatus(value))
                elif key == "priority":
                    project.priority = ProjectPriority(value)
                elif key == "category":
                    project.category = ProjectCategory(value)
                elif key == "chain":
                    project.chain = ProjectChain(value)
                elif key == "tags":
                    project.set_tags(value)
                else:
                    setattr(project, key, value)
            
            await session.commit()
            await session.refresh(project)
            return project
    
    project = asyncio.run(update_project())
    
    if not project:
        _cli_logger.log_warning(f"Project not found: {project_id}", "project_not_found")
        click.echo(f"❌ Project {project_id} not found")
        return
    
    click.echo(f"✅ Project updated: {project.id}")
    click.echo(f"   Status: {project.status.value if project.status else 'N/A'}")
    click.echo(f"   Name: {project.name}")
    click.echo(f"   Priority: {project.priority.value if project.priority else 'N/A'}")
    click.echo(f"   Category: {project.category.value if project.category else 'N/A'}")
    click.echo(f"   Chain: {project.chain.value if project.chain else 'N/A'}")
    click.echo(f"   Tags: {', '.join(project.get_tags())}")
    
    _cli_logger.log_info(
        f"Project updated: {project_id}",
        "project_updated",
        project_id=project_id,
        updates=list(updates.keys())
    )
    
    if output_json:
        click.echo(json.dumps(project.to_dict(), indent=2))


@cli.command()
@common_options
@click.argument('project_id')
@click.option('--yes', is_flag=True, help='Skip confirmation')
def project_delete(project_id: str, yes: bool, verbose: bool, quiet: bool, output_json: bool):
    """Supprime un projet."""
    _cli_logger.log_info(
        f"Executing project-delete command for {project_id}",
        "cmd_project_delete",
        project_id=project_id
    )
    click.echo(f"📋 Deleting project: {project_id}")
    
    if not yes:
        click.echo("⚠️  This will permanently delete the project and all its data!")
        if not click.confirm("Are you sure?"):
            click.echo("Cancelled.")
            return
    
    async def delete_project():
        from sqlalchemy import select
        from src.models.project import ProjectModel
        
        async with get_async_session() as session:
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                return None
            
            await session.delete(project)
            await session.commit()
            return project
    
    project = asyncio.run(delete_project())
    
    if not project:
        _cli_logger.log_warning(f"Project not found: {project_id}", "project_not_found")
        click.echo(f"❌ Project {project_id} not found")
        return
    
    _cli_logger.log_info(
        f"Project deleted: {project_id}",
        "project_deleted",
        project_id=project_id,
        project_name=project.name
    )
    click.echo(f"✅ Project deleted: {project.name} ({project.id})")
    
    if output_json:
        click.echo(json.dumps({"status": "success", "project_id": project_id}))


# ==============================================================================
# COMMANDES DE TÂCHE
# ==============================================================================

@cli.command()
@common_options
@click.argument('project_id')
@click.argument('name')
@click.option('--skill', '-s', required=True, help='Skill ID')
@click.option('--parameters', '-p', help='Parameters (JSON string)')
@click.option('--depends-on', '-d', help='Dependencies (comma-separated task IDs)')
@click.option('--priority', default='normal', help='Priority (low, normal, high, critical)')
@click.option('--task-type', default='custom', help='Task type')
@click.option('--requires-validation', is_flag=True, help='Requires human validation')
@click.option('--timeout', default=600, help='Timeout in seconds')
@click.option('--max-retries', default=3, help='Max retries')
def task_create(project_id: str, name: str, skill: str, parameters: Optional[str],
                depends_on: Optional[str], priority: str, task_type: str,
                requires_validation: bool, timeout: int, max_retries: int,
                verbose: bool, quiet: bool, output_json: bool):
    """Crée une nouvelle tâche."""
    _cli_logger.log_info(
        f"Executing task-create command for {name}",
        "cmd_task_create",
        project_id=project_id,
        task_name=name
    )
    click.echo(f"📋 Creating task: {name}")
    
    # Parser les paramètres
    params = {}
    if parameters:
        try:
            params = json.loads(parameters)
        except json.JSONDecodeError:
            _cli_logger.log_error(
                f"Invalid parameters JSON: {parameters}",
                None,
                "invalid_params_json"
            )
            click.echo(f"❌ Invalid parameters JSON: {parameters}")
            return
    
    # Parser les dépendances
    deps = []
    if depends_on:
        deps = [d.strip() for d in depends_on.split(',')]
    
    async def create_task():
        import uuid
        from sqlalchemy import select
        from src.models.project import ProjectModel
        from src.models.task import TaskModel, TaskPriority, TaskType
        
        async with get_async_session() as session:
            # Vérifier le projet
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                return {"error": f"Project {project_id} not found"}
            
            # Créer la tâche
            task = TaskModel(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name=name,
                skill_id=skill,
                parameters=params,
                dependencies=deps,
                priority=TaskPriority(priority) if priority in ['low', 'normal', 'high', 'critical'] else TaskPriority.NORMAL,
                task_type=TaskType(task_type) if task_type in [t.value for t in TaskType] else TaskType.CUSTOM,
                requires_human_validation=requires_validation,
                timeout_seconds=timeout,
                max_retries=max_retries
            )
            
            session.add(task)
            # Incrémenter le compteur
            project.task_count = (project.task_count or 0) + 1
            await session.commit()
            await session.refresh(task)
            return task
    
    result = asyncio.run(create_task())
    
    if isinstance(result, dict) and "error" in result:
        _cli_logger.log_warning(result["error"], "task_create_error")
        click.echo(f"❌ {result['error']}")
        return
    
    _cli_logger.log_info(
        f"Task created: {result.id}",
        "task_created",
        task_id=result.id,
        task_name=name
    )
    click.echo(f"✅ Task created: {result.id}")
    click.echo(f"   Name: {result.name}")
    click.echo(f"   Skill: {result.skill_id}")
    click.echo(f"   Priority: {result.priority.value if result.priority else 'normal'}")
    click.echo(f"   State: {result.state.value if result.state else 'PENDING'}")
    
    if output_json:
        click.echo(json.dumps(result.to_dict(), indent=2))


@cli.command()
@common_options
@click.argument('task_id')
def task_show(task_id: str, verbose: bool, quiet: bool, output_json: bool):
    """Affiche les détails d'une tâche."""
    _cli_logger.log_info(
        f"Executing task-show command for {task_id}",
        "cmd_task_show",
        task_id=task_id
    )
    click.echo(f"📋 Showing task: {task_id}")
    
    async def get_task():
        from sqlalchemy import select
        from src.models.task import TaskModel
        
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.id == task_id)
            )
            return result.scalar_one_or_none()
    
    task = asyncio.run(get_task())
    
    if not task:
        _cli_logger.log_warning(f"Task not found: {task_id}", "task_not_found")
        click.echo(f"❌ Task {task_id} not found")
        return
    
    if output_json:
        click.echo(json.dumps(task.to_dict(include_result=True), indent=2))
    else:
        click.echo(f"\n📊 Task Details:")
        click.echo(f"  ID: {task.id}")
        click.echo(f"  Name: {task.name}")
        click.echo(f"  Description: {task.description}")
        click.echo(f"  State: {task.state.value if task.state else 'PENDING'}")
        click.echo(f"  Priority: {task.priority.value if task.priority else 'normal'}")
        click.echo(f"  Task Type: {task.task_type.value if task.task_type else 'custom'}")
        click.echo(f"  Project: {task.project_id}")
        click.echo(f"  Skill: {task.skill_id}")
        click.echo(f"  Dependencies: {', '.join(task.dependencies) if task.dependencies else 'None'}")
        click.echo(f"  Retries: {task.retry_count}/{task.max_retries}")
        click.echo(f"  Duration: {task.duration_seconds:.2f}s")
        click.echo(f"  Requires Validation: {'Yes' if task.requires_human_validation else 'No'}")
        click.echo(f"  Validated: {'Yes' if task.human_validated else 'No'}")
        click.echo(f"  Created: {task.created_at.isoformat() if task.created_at else 'N/A'}")
        click.echo(f"  Updated: {task.updated_at.isoformat() if task.updated_at else 'N/A'}")
        
        if task.result:
            click.echo(f"\n  Result: {json.dumps(task.result, indent=2)}")
        if task.error_message:
            click.echo(f"\n  Error: {task.error_message}")


@cli.command()
@common_options
@click.argument('task_id')
@click.option('--state', help='New state')
@click.option('--priority', help='New priority')
@click.option('--parameters', help='New parameters (JSON string)')
def task_update(task_id: str, state: Optional[str], priority: Optional[str],
                parameters: Optional[str], verbose: bool, quiet: bool, output_json: bool):
    """Met à jour une tâche."""
    _cli_logger.log_info(
        f"Executing task-update command for {task_id}",
        "cmd_task_update",
        task_id=task_id
    )
    click.echo(f"📋 Updating task: {task_id}")
    
    updates = {}
    if state:
        updates["state"] = state
    if priority:
        updates["priority"] = priority
    if parameters:
        try:
            updates["parameters"] = json.loads(parameters)
        except json.JSONDecodeError:
            _cli_logger.log_error(
                f"Invalid parameters JSON: {parameters}",
                None,
                "invalid_params_json"
            )
            click.echo(f"❌ Invalid parameters JSON: {parameters}")
            return
    
    if not updates:
        click.echo("❌ No updates specified")
        return
    
    async def update_task():
        from sqlalchemy import select
        from src.models.task import TaskModel, TaskState, TaskPriority
        
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.id == task_id)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                return None
            
            for key, value in updates.items():
                if key == "state":
                    new_state = TaskState(value)
                    if new_state == TaskState.SUCCESS and task.state != TaskState.SUCCESS:
                        task.state = TaskState.SUCCESS
                    elif new_state == TaskState.FAILED and task.state != TaskState.FAILED:
                        task.state = TaskState.FAILED
                        task.error_message = "Updated via CLI"
                    elif new_state == TaskState.CANCELLED:
                        task.state = TaskState.CANCELLED
                        task.error_message = "Cancelled via CLI"
                    else:
                        task.state = new_state
                elif key == "priority":
                    task.priority = TaskPriority(value)
                else:
                    setattr(task, key, value)
            
            await session.commit()
            await session.refresh(task)
            return task
    
    task = asyncio.run(update_task())
    
    if not task:
        _cli_logger.log_warning(f"Task not found: {task_id}", "task_not_found")
        click.echo(f"❌ Task {task_id} not found")
        return
    
    _cli_logger.log_info(
        f"Task updated: {task_id}",
        "task_updated",
        task_id=task_id,
        updates=list(updates.keys())
    )
    
    click.echo(f"✅ Task updated: {task.id}")
    click.echo(f"   State: {task.state.value if task.state else 'PENDING'}")
    click.echo(f"   Priority: {task.priority.value if task.priority else 'normal'}")
    
    if output_json:
        click.echo(json.dumps(task.to_dict(), indent=2))


@cli.command()
@common_options
@click.argument('task_id')
@click.option('--force', is_flag=True, help='Force retry even if max retries reached')
def task_retry(task_id: str, force: bool, verbose: bool, quiet: bool, output_json: bool):
    """Réessaie une tâche échouée."""
    _cli_logger.log_info(
        f"Executing task-retry command for {task_id}",
        "cmd_task_retry",
        task_id=task_id,
        force=force
    )
    click.echo(f"🔄 Retrying task: {task_id}")
    
    async def retry_task():
        from sqlalchemy import select
        from src.models.task import TaskModel, TaskState
        
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.id == task_id)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                return {"error": f"Task {task_id} not found"}
            
            if not task.is_failed and not force:
                return {"error": f"Task {task_id} is not failed (state: {task.state.value})"}
            
            if not task.can_retry() and not force:
                return {"error": f"Task {task_id} has no retries remaining ({task.retry_count}/{task.max_retries})"}
            
            # Réinitialiser
            task.state = TaskState.PENDING
            task.completed_at = None
            task.error_message = None
            task.result = None
            if force:
                task.retry_count = 0
            else:
                task.retry_count += 1
            task.is_retry = True
            
            await session.commit()
            await session.refresh(task)
            
            return {
                "success": True,
                "task_id": task_id,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries
            }
    
    result = asyncio.run(retry_task())
    
    if "error" in result:
        _cli_logger.log_warning(result["error"], "task_retry_error")
        click.echo(f"❌ {result['error']}")
        return
    
    _cli_logger.log_info(
        f"Task retry scheduled: {task_id}",
        "task_retry_scheduled",
        task_id=task_id,
        retry_count=result['retry_count']
    )
    click.echo(f"✅ Task {task_id} retry scheduled (attempt {result['retry_count']}/{result['max_retries']})")
    
    if output_json:
        click.echo(json.dumps(result, indent=2))


@cli.command()
@common_options
@click.argument('task_id')
@click.option('--reason', help='Cancellation reason')
def task_cancel(task_id: str, reason: Optional[str], verbose: bool, quiet: bool, output_json: bool):
    """Annule une tâche."""
    _cli_logger.log_info(
        f"Executing task-cancel command for {task_id}",
        "cmd_task_cancel",
        task_id=task_id,
        reason=reason
    )
    click.echo(f"🛑 Cancelling task: {task_id}")
    
    async def cancel_task():
        from sqlalchemy import select
        from src.models.task import TaskModel, TaskState
        
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.id == task_id)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                return {"error": f"Task {task_id} not found"}
            
            if task.is_terminal:
                return {"error": f"Task {task_id} is already in terminal state: {task.state.value}"}
            
            task.state = TaskState.CANCELLED
            task.error_message = reason or "Cancelled via CLI"
            await session.commit()
            await session.refresh(task)
            return task
    
    result = asyncio.run(cancel_task())
    
    if isinstance(result, dict) and "error" in result:
        _cli_logger.log_warning(result["error"], "task_cancel_error")
        click.echo(f"❌ {result['error']}")
        return
    
    _cli_logger.log_info(
        f"Task cancelled: {task_id}",
        "task_cancelled",
        task_id=task_id,
        reason=reason
    )
    click.echo(f"✅ Task {task_id} cancelled")
    
    if output_json:
        click.echo(json.dumps(result.to_dict(), indent=2))


@cli.command()
@common_options
@click.argument('project_id')
@click.option('--state', help='Filter by state')
@click.option('--priority', help='Filter by priority')
@click.option('--limit', default=20, help='Limit results')
def task_list(project_id: str, state: Optional[str], priority: Optional[str], 
              limit: int, verbose: bool, quiet: bool, output_json: bool):
    """Liste les tâches d'un projet."""
    _cli_logger.log_info(
        f"Executing task-list command for project {project_id}",
        "cmd_task_list",
        project_id=project_id
    )
    click.echo(f"📋 Listing tasks for project: {project_id}")
    
    async def list_tasks():
        from sqlalchemy import select
        from src.models.task import TaskModel
        
        async with get_async_session() as session:
            query = select(TaskModel).where(TaskModel.project_id == project_id)
            if state:
                query = query.where(TaskModel.state == state)
            if priority:
                query = query.where(TaskModel.priority == priority)
            query = query.limit(limit)
            result = await session.execute(query)
            return result.scalars().all()
    
    tasks = asyncio.run(list_tasks())
    
    if output_json:
        click.echo(json.dumps([t.to_dict() for t in tasks], indent=2))
    else:
        if not tasks:
            click.echo("No tasks found.")
            return
        
        click.echo(f"\n📊 Found {len(tasks)} tasks:")
        click.echo("  ID | Name | State | Priority | Retries | Duration | Created")
        click.echo("  " + "-" * 80)
        for t in tasks:
            click.echo(f"  {t.id[:8]} | {t.name[:20]} | {t.state.value if t.state else 'PENDING':<8} | "
                       f"{t.priority.value if t.priority else 'normal':<8} | {t.retry_count:>3}/{t.max_retries} | "
                       f"{t.duration_seconds:>6.1f}s | "
                       f"{t.created_at.strftime('%Y-%m-%d') if t.created_at else 'N/A'}")


# ==============================================================================
# COMMANDES DE SPRINT
# ==============================================================================

@cli.command()
@common_options
@click.argument('project_id')
@click.argument('name')
@click.option('--description', help='Sprint description')
@click.option('--start-date', help='Start date (ISO format)')
@click.option('--end-date', help='End date (ISO format)')
def sprint_create(project_id: str, name: str, description: Optional[str],
                  start_date: Optional[str], end_date: Optional[str],
                  verbose: bool, quiet: bool, output_json: bool):
    """Crée un nouveau sprint."""
    _cli_logger.log_info(
        f"Executing sprint-create command for {name}",
        "cmd_sprint_create",
        project_id=project_id,
        sprint_name=name
    )
    click.echo(f"📋 Creating sprint: {name}")
    
    async def create_sprint():
        import uuid
        from sqlalchemy import select
        from src.models.project import ProjectModel
        from src.persistence.models_orm import Sprint
        
        async with get_async_session() as session:
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                return {"error": f"Project {project_id} not found"}
            
            sprint = Sprint(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name=name,
                description=description or "",
                start_date=datetime.fromisoformat(start_date) if start_date else None,
                end_date=datetime.fromisoformat(end_date) if end_date else None
            )
            
            session.add(sprint)
            await session.commit()
            await session.refresh(sprint)
            return sprint
    
    result = asyncio.run(create_sprint())
    
    if isinstance(result, dict) and "error" in result:
        _cli_logger.log_warning(result["error"], "sprint_create_error")
        click.echo(f"❌ {result['error']}")
        return
    
    _cli_logger.log_info(
        f"Sprint created: {result.id}",
        "sprint_created",
        sprint_id=result.id,
        sprint_name=name
    )
    click.echo(f"✅ Sprint created: {result.id}")
    click.echo(f"   Name: {result.name}")
    click.echo(f"   Project: {result.project_id}")
    click.echo(f"   Status: {result.status if result.status else 'planned'}")
    
    if output_json:
        click.echo(json.dumps(result.to_dict(), indent=2))


@cli.command()
@common_options
@click.argument('sprint_id')
def sprint_show(sprint_id: str, verbose: bool, quiet: bool, output_json: bool):
    """Affiche les détails d'un sprint."""
    _cli_logger.log_info(
        f"Executing sprint-show command for {sprint_id}",
        "cmd_sprint_show",
        sprint_id=sprint_id
    )
    click.echo(f"📋 Showing sprint: {sprint_id}")
    
    async def get_sprint():
        from sqlalchemy import select
        from src.persistence.models_orm import Sprint
        
        async with get_async_session() as session:
            result = await session.execute(
                select(Sprint).where(Sprint.id == sprint_id)
            )
            return result.scalar_one_or_none()
    
    sprint = asyncio.run(get_sprint())
    
    if not sprint:
        _cli_logger.log_warning(f"Sprint not found: {sprint_id}", "sprint_not_found")
        click.echo(f"❌ Sprint {sprint_id} not found")
        return
    
    if output_json:
        click.echo(json.dumps(sprint.to_dict(), indent=2))
    else:
        click.echo(f"\n📊 Sprint Details:")
        click.echo(f"  ID: {sprint.id}")
        click.echo(f"  Name: {sprint.name}")
        click.echo(f"  Description: {sprint.description}")
        click.echo(f"  Status: {sprint.status if sprint.status else 'planned'}")
        click.echo(f"  Project: {sprint.project_id}")
        click.echo(f"  Tasks: {len(sprint.task_results) if sprint.task_results else 0}")
        click.echo(f"  Created: {sprint.created_at.isoformat() if sprint.created_at else 'N/A'}")


# ==============================================================================
# COMMANDES D'EXÉCUTION
# ==============================================================================

@cli.command()
@common_options
@click.argument('project_id')
@click.option('--sprint', '-s', help='Sprint ID')
@click.option('--parallel', is_flag=True, help='Execute in parallel')
@click.option('--max-parallel', default=4, help='Max parallel tasks')
def run(project_id: str, sprint: Optional[str], parallel: bool, max_parallel: int, verbose: bool, quiet: bool, output_json: bool):
    """Exécute le pipeline pour un projet."""
    _cli_logger.log_info(
        f"Executing run command for project {project_id}",
        "cmd_run",
        project_id=project_id,
        sprint=sprint,
        parallel=parallel
    )
    click.echo(f"🚀 Running pipeline for project: {project_id}")
    
    async def execute():
        from sqlalchemy import select
        from src.models.project import ProjectModel
        from src.models.task import TaskModel, TaskState
        from src.orchestration.workflow_engine import WorkflowEngine
        
        async with get_async_session() as session:
            # Récupérer le projet
            result = await session.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                return {"error": f"Project {project_id} not found"}
            
            # Récupérer les tâches
            task_query = select(TaskModel).where(TaskModel.project_id == project_id)
            if sprint:
                task_query = task_query.where(TaskModel.sprint_id == sprint)
            task_result = await session.execute(task_query)
            tasks = task_result.scalars().all()
            
            if not tasks:
                return {"error": "No tasks found"}
            
            # Initialiser le moteur de workflow
            engine = WorkflowEngine(
                agents={},  # À configurer plus tard
                max_parallel=max_parallel if parallel else 1
            )
            
            # Ajouter les tâches au moteur
            for task in tasks:
                engine.add_task(
                    task_id=task.id,
                    agent_id=task.skill_id,
                    action="execute",
                    parameters=task.parameters or {},
                    dependencies=task.dependencies or []
                )
            
            # Exécuter
            result = await engine.start(workflow_id=f"cli_{project_id}")
            
            # Mettre à jour le projet
            project.update_status(ProjectStatus.IN_PROGRESS)
            await session.commit()
            
            return {
                "success": True,
                "project_id": project_id,
                "tasks_completed": len(tasks),
                "result": result
            }
    
    result = asyncio.run(execute())
    
    if "error" in result:
        _cli_logger.log_error(
            f"Pipeline execution failed: {result['error']}",
            None,
            "pipeline_execution_failed"
        )
        click.echo(f"❌ {result['error']}")
        return
    
    _cli_logger.log_info(
        f"Pipeline completed: {result['tasks_completed']} tasks",
        "pipeline_completed",
        project_id=project_id,
        tasks_completed=result['tasks_completed']
    )
    click.echo(f"✅ Pipeline completed: {result['tasks_completed']} tasks executed")
    
    if output_json:
        click.echo(json.dumps(result, indent=2, default=str))


@cli.command()
@common_options
@click.argument('task_id')
def task_status(task_id: str, verbose: bool, quiet: bool, output_json: bool):
    """Affiche le statut d'une tâche."""
    _cli_logger.log_info(
        f"Executing task-status command for {task_id}",
        "cmd_task_status",
        task_id=task_id
    )
    click.echo(f"📋 Showing task status: {task_id}")
    
    async def get_task():
        from sqlalchemy import select
        from src.models.task import TaskModel
        
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskModel).where(TaskModel.id == task_id)
            )
            return result.scalar_one_or_none()
    
    task = asyncio.run(get_task())
    
    if not task:
        _cli_logger.log_warning(f"Task not found: {task_id}", "task_not_found")
        click.echo(f"❌ Task {task_id} not found")
        return
    
    if output_json:
        click.echo(json.dumps(task.to_dict(include_result=True), indent=2))
    else:
        click.echo(f"\n📊 Task Status:")
        click.echo(f"  ID: {task.id}")
        click.echo(f"  Name: {task.name}")
        click.echo(f"  State: {task.state.value if task.state else 'PENDING'}")
        click.echo(f"  Priority: {task.priority.value if task.priority else 'normal'}")
        click.echo(f"  Retries: {task.retry_count}/{task.max_retries}")
        click.echo(f"  Duration: {task.duration_seconds:.2f}s")
        click.echo(f"  Is Running: {'Yes' if task.is_running else 'No'}")
        click.echo(f"  Is Terminal: {'Yes' if task.is_terminal else 'No'}")
        click.echo(f"  Is Success: {'Yes' if task.is_success else 'No'}")
        click.echo(f"  Is Failed: {'Yes' if task.is_failed else 'No'}")


# ==============================================================================
# COMMANDES DE SÉCURITÉ
# ==============================================================================

@cli.command()
@common_options
@click.argument('contract_path')
@click.option('--level', default='full', help='Audit level (level_1, level_2, level_3, level_4, full)')
@click.option('--output', '-o', help='Output file for report')
@click.option('--json-output', is_flag=True, help='Output as JSON')
def audit(contract_path: str, level: str, output: Optional[str], json_output: bool, verbose: bool, quiet: bool, output_json: bool):
    """Exécute un audit de sécurité sur un contrat."""
    _cli_logger.log_info(
        f"Executing audit command for {contract_path}",
        "cmd_audit",
        contract_path=contract_path,
        level=level
    )
    click.echo(f"🔒 Auditing contract: {contract_path}")
    
    contract_file = Path(contract_path)
    if not contract_file.exists():
        _cli_logger.log_error(
            f"Contract file not found: {contract_path}",
            None,
            "contract_file_not_found"
        )
        click.echo(f"❌ Contract file not found: {contract_path}")
        return
    
    code = contract_file.read_text()
    
    click.echo("🔍 Running security audit...")
    
    async def run_audit():
        from src.security.shield_orchestrator import SecurityShield
        
        shield = SecurityShield()
        result = await shield.run_full_audit(
            contract_path=contract_path,
            contract_name=contract_file.stem
        )
        return result
    
    try:
        result = asyncio.run(run_audit())
        
        if output:
            output_path = Path(output)
            if output_path.suffix == '.json':
                output_path.write_text(json.dumps(result, indent=2))
            else:
                output_path.write_text(result.get("report", {}).get("summary", "Audit completed"))
            click.echo(f"✅ Audit report saved to: {output}")
        
        _cli_logger.log_info(
            f"Audit completed for {contract_path}",
            "audit_completed",
            contract_path=contract_path,
            secure=result.get('secure', False)
        )
        
        if json_output or output_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"\n📊 Audit Results:")
            click.echo(f"  Secure: {'✅' if result.get('secure') else '❌'}")
            click.echo(f"  Score: {result.get('score', 0):.1f}")
            click.echo(f"  Vulnerabilities: {len(result.get('vulnerabilities', []))}")
            
    except Exception as e:
        _cli_logger.log_error(f"Audit failed: {e}", e, "audit_failed")
        click.echo(f"❌ Audit failed: {e}")


@cli.command()
@common_options
@click.argument('contract_path')
@click.option('--function', '-f', help='Function to verify')
@click.option('--timeout', default=300, help='Timeout in seconds')
def verify(contract_path: str, function: Optional[str], timeout: int, verbose: bool, quiet: bool, output_json: bool):
    """Exécute une vérification formelle sur un contrat."""
    _cli_logger.log_info(
        f"Executing verify command for {contract_path}",
        "cmd_verify",
        contract_path=contract_path,
        function=function
    )
    click.echo(f"🔬 Verifying contract: {contract_path}")
    
    contract_file = Path(contract_path)
    if not contract_file.exists():
        _cli_logger.log_error(
            f"Contract file not found: {contract_path}",
            None,
            "contract_file_not_found"
        )
        click.echo(f"❌ Contract file not found: {contract_path}")
        return
    
    async def run_verification():
        from src.security.formal_verifier import FormalVerifier
        
        verifier = FormalVerifier(timeout=timeout)
        result = await verifier.verify_invariants(
            contract_path=contract_path,
            check_function=function
        )
        return result
    
    try:
        result = asyncio.run(run_verification())
        
        _cli_logger.log_info(
            f"Verification completed for {contract_path}",
            "verification_completed",
            contract_path=contract_path,
            passed=result.get('passed', False)
        )
        
        if output_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"\n📊 Verification Results:")
            click.echo(f"  Passed: {'✅' if result.get('passed') else '❌'}")
            click.echo(f"  Properties: {result.get('passed_count', 0)}/{result.get('total_count', 0)} passed")
            
    except Exception as e:
        _cli_logger.log_error(f"Verification failed: {e}", e, "verification_failed")
        click.echo(f"❌ Verification failed: {e}")


# ==============================================================================
# COMMANDES DE MAINTENANCE
# ==============================================================================

@cli.command()
@common_options
@click.option('--workspace', is_flag=True, help='Clean workspace')
@click.option('--cache', is_flag=True, help='Clean cache')
@click.option('--logs', is_flag=True, help='Clean logs')
@click.option('--all', is_flag=True, help='Clean everything')
def cleanup(workspace: bool, cache: bool, logs: bool, all: bool, verbose: bool, quiet: bool, output_json: bool):
    """Nettoie les fichiers temporaires."""
    _cli_logger.log_info("Executing cleanup command", "cmd_cleanup")
    click.echo("🧹 Cleaning up...")
    
    cleaned = []
    
    # Nettoyer tout
    if all:
        workspace = True
        cache = True
        logs = True
    
    # Nettoyer le workspace
    if workspace:
        workspace_path = getattr(settings.pipeline, 'default_workspace', Path('./workspace'))
        if workspace_path.exists():
            click.echo(f"📁 Cleaning workspace: {workspace_path}")
            import shutil
            shutil.rmtree(workspace_path, ignore_errors=True)
            workspace_path.mkdir(parents=True, exist_ok=True)
            cleaned.append("workspace")
    
    # Nettoyer le cache
    if cache:
        cache_path = Path("./.cache")
        if cache_path.exists():
            click.echo(f"📁 Cleaning cache: {cache_path}")
            import shutil
            shutil.rmtree(cache_path, ignore_errors=True)
            cleaned.append("cache")
    
    # Nettoyer les logs
    if logs:
        log_path = Path("./logs")
        if log_path.exists():
            click.echo(f"📁 Cleaning logs: {log_path}")
            for log_file in log_path.glob("*.log"):
                log_file.unlink()
            cleaned.append("logs")
    
    if not cleaned:
        click.echo("No cleanup specified. Use --workspace, --cache, --logs, or --all.")
        return
    
    _cli_logger.log_info(
        f"Cleanup completed: {', '.join(cleaned)}",
        "cleanup_completed",
        cleaned=cleaned
    )
    click.echo(f"✅ Cleanup completed: {', '.join(cleaned)}")
    
    if output_json:
        click.echo(json.dumps({"status": "success", "cleaned": cleaned}))


@cli.command()
@common_options
def info(verbose: bool, quiet: bool, output_json: bool):
    """Affiche des informations sur l'environnement."""
    _cli_logger.log_info("Executing info command", "cmd_info")
    
    click.echo("=" * 60)
    click.echo("Smart Contract Dev Pipeline - Environment Info")
    click.echo("=" * 60)
    
    # Python
    click.echo(f"\n🐍 Python: {sys.version.split()[0]}")
    click.echo(f"   Path: {sys.executable}")
    
    # Configuration
    click.echo(f"\n⚙️ Configuration:")
    click.echo(f"  Environment: {getattr(settings, 'env', 'development')}")
    click.echo(f"  Debug: {getattr(settings, 'debug', False)}")
    click.echo(f"  Workspace: {getattr(settings.pipeline, 'default_workspace', './workspace')}")
    click.echo(f"  Database: {getattr(settings.database, 'url', 'postgresql://')}")
    click.echo(f"  Redis: {getattr(settings.redis, 'url', 'redis://localhost:6379/0')}")
    click.echo(f"  Ollama: {getattr(settings.llm, 'ollama_url', 'http://localhost:11434')}")
    click.echo(f"  ChromaDB: {getattr(settings.chroma, 'host', 'localhost')}:{getattr(settings.chroma, 'port', 8000)}")
    
    # Vérifications
    click.echo(f"\n🔍 Health Checks:")
    
    # Database
    db_ok = asyncio.run(check_db_connection())
    click.echo(f"  Database: {'✅ Connected' if db_ok else '❌ Disconnected'}")
    
    # Redis
    try:
        import redis.asyncio as aioredis
        redis_client = asyncio.run(aioredis.from_url(getattr(settings.redis, 'url', 'redis://localhost:6379/0')))
        redis_ok = asyncio.run(redis_client.ping())
        asyncio.run(redis_client.close())
        click.echo(f"  Redis: {'✅ Connected' if redis_ok else '❌ Disconnected'}")
    except:
        click.echo("  Redis: ❌ Disconnected")
    
    # Ollama
    try:
        from src.llm.ollama_client import OllamaClient
        ollama = OllamaClient()
        ollama_ok = asyncio.run(ollama.health_check())
        click.echo(f"  Ollama: {'✅ Connected' if ollama_ok else '❌ Disconnected'}")
        if ollama_ok:
            models = asyncio.run(ollama.list_models())
            click.echo(f"    Models: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}")
    except:
        click.echo("  Ollama: ❌ Disconnected")
    
    if output_json:
        click.echo("\n" + json.dumps({
            "python": sys.version.split()[0],
            "environment": getattr(settings, 'env', 'development'),
            "debug": getattr(settings, 'debug', False),
            "workspace": str(getattr(settings.pipeline, 'default_workspace', './workspace')),
            "database": getattr(settings.database, 'url', 'postgresql://'),
            "redis": getattr(settings.redis, 'url', 'redis://localhost:6379/0'),
            "ollama": getattr(settings.llm, 'ollama_url', 'http://localhost:11434')
        }, indent=2))
    
    click.echo("\n" + "=" * 60)