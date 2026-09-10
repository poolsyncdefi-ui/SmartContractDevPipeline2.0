# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Database Seeds
# ==============================================================================
# Fichier: src/db/seeds.py
# Description: Données initiales pour la base de données.
#              Ce fichier est utilisé par migrations.py lors de l'initialisation
#              avec l'option --seed.
#              Version refactorisée avec horodatages timezone-aware et
#              intégration des nouveaux modules système.
# ==============================================================================

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy import select

from src.db.database import get_async_session
from src.models.project import (
    ProjectModel,
    ProjectStatus,
    ProjectChain,
    ProjectPriority,
    ProjectCategory,
)
from src.models.task import TaskModel, TaskState, TaskPriority, TaskType
from src.models.skill_record import SkillRecordModel, SkillStatus, SkillScope
from src.models.sprint import Sprint, SprintStatus
from src.core.exceptions import StorageError
from src.core.status_manager import normalize_status, status_manager
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)

# Logger structuré global pour les seeds
_seed_logger = StructuredLogger(
    component_name="DatabaseSeeds",
    log_level=LogLevel.INFO
)


# ==============================================================================
# FONCTIONS DE SEED
# ==============================================================================

async def seed_projects() -> None:
    """
    Seed des projets.
    Vérifie si le projet existe déjà avant de le créer pour éviter les doublons.
    """
    _seed_logger.log_info("Seeding projects...", "seed_projects_start")
    logger.info("🌱 Seeding projects...")
    
    async with get_async_session() as session:
        try:
            stmt = select(ProjectModel).where(ProjectModel.name == "SecureVault")
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                _seed_logger.log_info(
                    "Project 'SecureVault' already exists, skipping.",
                    "seed_projects_skip"
                )
                logger.info("ℹ️ Project 'SecureVault' already exists, skipping.")
                return
            
            project = ProjectModel(
                id=str(uuid.uuid4()),
                name="SecureVault",
                description="A secure token vault with governance and multi-signature support",
                status=ProjectStatus.CREATED,
                chain=ProjectChain.ETHEREUM,
                priority=ProjectPriority.HIGH,
                category=ProjectCategory.DEFI,
                spec_yaml="""project:
  name: SecureVault
  chain: ethereum
  version: 1.0.0
  description: A secure token vault with governance
  category: defi
  priority: high
  tags:
    - vault
    - security
    - defi
""",
                config={
                    "deployment": {
                        "safe_address": "0x1234567890123456789012345678901234567890",
                        "admin_address": "0x0987654321098765432109876543210987654321"
                    }
                },
                tags=["vault", "security", "defi"],
                is_template=False,
                is_public=False
            )
            
            session.add(project)
            await session.commit()
            
            _seed_logger.log_info(
                f"Project created: {project.id}",
                "seed_projects_created",
                project_id=project.id,
                project_name=project.name
            )
            logger.info(f"✅ Project created: {project.id} - {project.name}")
            
        except Exception as e:
            await session.rollback()
            _seed_logger.log_error(
                f"Failed to seed projects: {str(e)}",
                e,
                "seed_projects_failed"
            )
            logger.error(f"❌ Failed to seed projects: {e}")
            raise StorageError(
                message=f"Failed to seed projects: {e}",
                operation="seed_projects"
            )


async def seed_skills() -> None:
    """
    Seed des compétences prédéfinies.
    Vérifie l'existence de chaque compétence avant de l'insérer.
    """
    _seed_logger.log_info("Seeding skills...", "seed_skills_start")
    logger.info("🌱 Seeding skills...")
    
    async with get_async_session() as session:
        try:
            # Utilisation des statuts normalisés
            status_active = normalize_status(SkillStatus.ACTIVE.value)
            scope_global = normalize_status(SkillScope.GLOBAL.value)

            skills_data = [
                {
                    "skill_id": "solidity_generation",
                    "name": "Solidity Contract Generator",
                    "description": "Generates Solidity smart contracts from specifications with best practices",
                    "prompt_rules": """You are an expert Solidity developer. Generate secure, optimized code.
- Use OpenZeppelin v5 contracts when applicable
- Include proper access control (Ownable, AccessControl)
- Add Natspec documentation
- Follow Solidity style guide
- Consider gas optimization""",
                    "input_schema_json": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Contract name"},
                            "type": {"type": "string", "description": "Contract type (ERC20, ERC721, etc.)"},
                            "symbol": {"type": "string", "description": "Token symbol"},
                            "initial_supply": {"type": "integer", "minimum": 0}
                        },
                        "required": ["name", "type"]
                    },
                    "status": status_active,
                    "scope": scope_global,
                    "tags": ["solidity", "generation", "smart-contract", "codegen"]
                },
                {
                    "skill_id": "security_audit",
                    "name": "Security Auditor",
                    "description": "Audits smart contracts for vulnerabilities using Slither and manual review",
                    "prompt_rules": """You are a security expert. Analyze contracts for vulnerabilities.
- Check for reentrancy
- Verify access control
- Detect arithmetic issues
- Review event emissions
- Check for front-running risks
- Validate oracle usage""",
                    "input_schema_json": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Contract code to audit"},
                            "contract_name": {"type": "string", "description": "Name of the contract"}
                        },
                        "required": ["code"]
                    },
                    "status": status_active,
                    "scope": scope_global,
                    "tags": ["security", "audit", "vulnerability", "slither"]
                },
                {
                    "skill_id": "test_generation",
                    "name": "Test Generator",
                    "description": "Generates Foundry/Forge tests for smart contracts",
                    "prompt_rules": """You are a test engineer. Generate comprehensive test suites.
- Use Foundry/Forge testing framework
- Test all public functions
- Include positive and negative test cases
- Add fuzzing tests for invariants
- Cover edge cases
- Use assertions and cheatcodes""",
                    "input_schema_json": {
                        "type": "object",
                        "properties": {
                            "contract_code": {"type": "string", "description": "Contract code to test"},
                            "contract_name": {"type": "string", "description": "Name of the contract"}
                        },
                        "required": ["contract_code"]
                    },
                    "status": status_active,
                    "scope": scope_global,
                    "tags": ["testing", "foundry", "solidity", "forge"]
                },
                {
                    "skill_id": "deployment_script",
                    "name": "Deployment Script Generator",
                    "description": "Generates Foundry deployment scripts for smart contracts",
                    "prompt_rules": """You are a deployment engineer. Generate Foundry deployment scripts.
- Use Forge scripts
- Include constructor arguments
- Add verification steps
- Support multiple networks
- Include gas estimation""",
                    "input_schema_json": {
                        "type": "object",
                        "properties": {
                            "contract_name": {"type": "string", "description": "Name of the contract"},
                            "constructor_args": {"type": "object", "description": "Constructor arguments"},
                            "network": {"type": "string", "description": "Target network"}
                        },
                        "required": ["contract_name"]
                    },
                    "status": status_active,
                    "scope": scope_global,
                    "tags": ["deployment", "foundry", "script"]
                },
                {
                    "skill_id": "formal_verification",
                    "name": "Formal Verification Engineer",
                    "description": "Performs formal verification using Halmos symbolic prover",
                    "prompt_rules": """You are a formal verification engineer. Use Halmos for symbolic verification.
- Define invariants
- Write properties
- Analyze counterexamples
- Guide the user on fixing issues""",
                    "input_schema_json": {
                        "type": "object",
                        "properties": {
                            "contract_code": {"type": "string", "description": "Contract code"},
                            "properties": {"type": "array", "items": {"type": "string"}, "description": "Properties to verify"}
                        },
                        "required": ["contract_code"]
                    },
                    "status": status_active,
                    "scope": scope_global,
                    "tags": ["formal", "verification", "halmos"]
                }
            ]
            
            created_count = 0
            for skill_data in skills_data:
                stmt = select(SkillRecordModel).where(
                    SkillRecordModel.skill_id == skill_data["skill_id"]
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    _seed_logger.log_debug(
                        f"Skill '{skill_data['skill_id']}' already exists, skipping.",
                        "seed_skill_skip"
                    )
                    logger.info(f"ℹ️ Skill '{skill_data['skill_id']}' already exists, skipping.")
                    continue
                
                skill = SkillRecordModel(**skill_data)
                session.add(skill)
                created_count += 1
                _seed_logger.log_debug(
                    f"Skill added: {skill_data['skill_id']}",
                    "seed_skill_added"
                )
            
            await session.commit()
            
            _seed_logger.log_info(
                f"{created_count} skills seeded successfully",
                "seed_skills_completed",
                created_count=created_count,
                total_count=len(skills_data)
            )
            logger.info(f"✅ {created_count} skills seeded successfully")
            
        except Exception as e:
            await session.rollback()
            _seed_logger.log_error(
                f"Failed to seed skills: {str(e)}",
                e,
                "seed_skills_failed"
            )
            logger.error(f"❌ Failed to seed skills: {e}")
            raise StorageError(
                message=f"Failed to seed skills: {e}",
                operation="seed_skills"
            )


async def seed_sprint_and_tasks() -> None:
    """
    Seed des sprints et tâches associés au projet SecureVault.
    Vérifie l'existence du projet avant d'ajouter des sprints.
    """
    _seed_logger.log_info("Seeding sprints and tasks...", "seed_sprint_tasks_start")
    logger.info("🌱 Seeding sprints and tasks...")
    
    async with get_async_session() as session:
        try:
            stmt = select(ProjectModel).where(ProjectModel.name == "SecureVault")
            result = await session.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                _seed_logger.log_warning(
                    "Project 'SecureVault' not found, skipping sprints and tasks.",
                    "seed_sprint_tasks_skip"
                )
                logger.warning("ℹ️ Project 'SecureVault' not found, skipping sprints and tasks.")
                return
            
            sprint_stmt = select(Sprint).where(Sprint.project_id == project.id)
            sprint_result = await session.execute(sprint_stmt)
            existing_sprints = sprint_result.scalars().all()
            
            if existing_sprints:
                _seed_logger.log_info(
                    "Sprints already exist for project 'SecureVault', skipping.",
                    "seed_sprint_tasks_exists"
                )
                logger.info("ℹ️ Sprints already exist for project 'SecureVault', skipping.")
                return
            
            now = datetime.now(timezone.utc)
            # Normalisation du statut
            sprint_status = normalize_status(SprintStatus.PLANNED.value)
            
            sprint = Sprint(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="Sprint 1 - Initial Development",
                description="Initial development of the SecureVault contract",
                status=sprint_status,
                priority=8,
                start_date=now,
                end_date=now + timedelta(days=14),
                tags=["initial", "core"]
            )
            
            session.add(sprint)
            await session.flush()
            
            tasks_data = [
                {
                    "name": "Contract Design",
                    "description": "Design the vault contract architecture",
                    "skill_id": "solidity_generation",
                    "parameters": {"type": "design", "name": "VaultDesign"},
                    "task_type": normalize_status(TaskType.DESIGN.value),
                    "priority": normalize_status(TaskPriority.HIGH.value),
                    "state": normalize_status(TaskState.PENDING.value)
                },
                {
                    "name": "Core Implementation",
                    "description": "Implement core Vault functionalities",
                    "skill_id": "solidity_generation",
                    "parameters": {"type": "implementation", "name": "VaultCore"},
                    "task_type": normalize_status(TaskType.DEVELOPMENT.value),
                    "priority": normalize_status(TaskPriority.HIGH.value),
                    "state": normalize_status(TaskState.PENDING.value)
                }
            ]
            
            created_tasks = 0
            for task_data in tasks_data:
                task = TaskModel(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    sprint_id=sprint.id,
                    **task_data
                )
                session.add(task)
                created_tasks += 1
            
            await session.commit()
            
            _seed_logger.log_info(
                f"Sprint 1 and {created_tasks} tasks seeded successfully",
                "seed_sprint_tasks_completed",
                sprint_id=sprint.id,
                tasks_count=created_tasks
            )
            logger.info(f"✅ Sprint 1 and {created_tasks} tasks seeded successfully")
            
        except Exception as e:
            await session.rollback()
            _seed_logger.log_error(
                f"Failed to seed sprint and tasks: {str(e)}",
                e,
                "seed_sprint_tasks_failed"
            )
            logger.error(f"❌ Failed to seed sprint and tasks: {e}")
            raise StorageError(
                message=f"Failed to seed sprint and tasks: {e}",
                operation="seed_sprint_and_tasks"
            )


async def seed_all() -> None:
    """
    Exécute l'ensemble du processus de seeding dans le bon ordre de dépendance.
    """
    _seed_logger.log_info("Executing global database seeds...", "seed_all_start")
    logger.info("🌱 Execution globale des seeds DB...")
    
    try:
        await seed_projects()
        await seed_skills()
        await seed_sprint_and_tasks()
        
        _seed_logger.log_info(
            "Global seeding completed successfully",
            "seed_all_completed"
        )
        logger.info("✅ Seeding global terminé avec succès.")
        
    except Exception as e:
        _seed_logger.log_error(
            f"Global seeding failed: {str(e)}",
            e,
            "seed_all_failed"
        )
        logger.error(f"❌ Seeding global échoué: {e}")
        raise


async def seed_all_safe() -> Dict[str, Any]:
    """
    Exécute l'ensemble du processus de seeding avec capture des erreurs.
    
    Returns:
        Dict[str, Any]: Rapport de seeding avec les statuts
    """
    report = {
        "status": "success",
        "steps": {},
        "errors": []
    }
    
    steps = [
        ("projects", seed_projects),
        ("skills", seed_skills),
        ("sprint_and_tasks", seed_sprint_and_tasks)
    ]
    
    for step_name, step_func in steps:
        try:
            await step_func()
            report["steps"][step_name] = "success"
        except Exception as e:
            report["steps"][step_name] = "failed"
            report["errors"].append(f"{step_name}: {str(e)}")
            report["status"] = "partial" if len(report["errors"]) < len(steps) else "failed"
    
    return report


# ==============================================================================
# POINT D'ENTRÉE POUR L'EXÉCUTION DIRECTE
# ==============================================================================

if __name__ == "__main__":
    async def main():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Database Seeds")
        print("=" * 60)
        
        report = await seed_all_safe()
        
        print("\n📊 Seed Report:")
        for step, status in report["steps"].items():
            icon = "✅" if status == "success" else "❌"
            print(f"  {icon} {step}: {status}")
        
        if report["errors"]:
            print("\n⚠️ Errors:")
            for error in report["errors"]:
                print(f"  - {error}")
        
        print(f"\n🏁 Final Status: {report['status']}")
        print("\n✅ Seeding complete.")

    asyncio.run(main())