# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Database Seeds
# ==============================================================================
# Fichier: src/db/seeds.py
# Description: Données initiales pour la base de données.
#              Ce fichier est utilisé par migrations.py lors de l'initialisation
#              avec l'option --seed.
# ==============================================================================

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

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

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# FONCTIONS DE SEED
# ==============================================================================

async def seed_projects() -> None:
    """
    Seed des projets.
    Vérifie si le projet existe déjà avant de le créer pour éviter les doublons.
    """
    logger.info("🌱 Seeding projects...")
    
    async with get_async_session() as session:
        try:
            stmt = select(ProjectModel).where(ProjectModel.name == "SecureVault")
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
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
            logger.info(f"✅ Project created: {project.id} - {project.name}")
            
        except Exception as e:
            await session.rollback()
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
    logger.info("🌱 Seeding skills...")
    
    async with get_async_session() as session:
        try:
            status_active = SkillStatus.ACTIVE.value if hasattr(SkillStatus.ACTIVE, "value") else SkillStatus.ACTIVE
            scope_global = SkillScope.GLOBAL.value if hasattr(SkillScope.GLOBAL, "value") else SkillScope.GLOBAL

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
            
            for skill_data in skills_data:
                stmt = select(SkillRecordModel).where(
                    SkillRecordModel.skill_id == skill_data["skill_id"]
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    logger.info(f"ℹ️ Skill '{skill_data['skill_id']}' already exists, skipping.")
                    continue
                
                skill = SkillRecordModel(**skill_data)
                session.add(skill)
                logger.debug(f"✅ Skill added: {skill_data['skill_id']}")
            
            await session.commit()
            logger.info(f"✅ {len(skills_data)} skills seeded successfully")
            
        except Exception as e:
            await session.rollback()
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
    logger.info("🌱 Seeding sprints and tasks...")
    
    async with get_async_session() as session:
        try:
            stmt = select(ProjectModel).where(ProjectModel.name == "SecureVault")
            result = await session.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                logger.warning("ℹ️ Project 'SecureVault' not found, skipping sprints and tasks.")
                return
            
            sprint_stmt = select(Sprint).where(Sprint.project_id == project.id)
            sprint_result = await session.execute(sprint_stmt)
            existing_sprints = sprint_result.scalars().all()
            
            if existing_sprints:
                logger.info("ℹ️ Sprints already exist for project 'SecureVault', skipping.")
                return
            
            now = datetime.now(timezone.utc)
            sprint_status = getattr(SprintStatus, "PLANNED", "planned")
            
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
                    "task_type": getattr(TaskType, "DESIGN", "design"),
                    "priority": getattr(TaskPriority, "HIGH", "high"),
                    "state": getattr(TaskState, "PENDING", "pending")
                },
                {
                    "name": "Core Implementation",
                    "description": "Implement core Vault functionalities",
                    "skill_id": "solidity_generation",
                    "parameters": {"type": "implementation", "name": "VaultCore"},
                    "task_type": getattr(TaskType, "DEVELOPMENT", "development"),
                    "priority": getattr(TaskPriority, "HIGH", "high"),
                    "state": getattr(TaskState, "PENDING", "pending")
                }
            ]
            
            for task_data in tasks_data:
                task = TaskModel(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    sprint_id=sprint.id,
                    **task_data
                )
                session.add(task)
                
            await session.commit()
            logger.info(f"✅ Sprint 1 and {len(tasks_data)} tasks seeded successfully")
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Failed to seed sprint and tasks: {e}")
            raise StorageError(
                message=f"Failed to seed sprint and tasks: {e}",
                operation="seed_sprint_and_tasks"
            )


async def seed_all() -> None:
    """Exécute l'ensemble du processus de seeding dans le bon ordre de dépendance."""
    logger.info("🌱 Execution globale des seeds DB...")
    await seed_projects()
    await seed_skills()
    await seed_sprint_and_tasks()
    logger.info("✅ Seeding global terminé avec succès.")


# ==============================================================================
# POINT D'ENTRÉE POUR L'EXÉCUTION DIRECTE
# ==============================================================================

if __name__ == "__main__":
    async def main():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Database Seeds")
        print("=" * 60)
        await seed_all()
        print("\n✅ Seeding complet.")

    asyncio.run(main())