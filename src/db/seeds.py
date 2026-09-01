# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Database Seeds
# ==============================================================================
# Fichier: src/db/seeds.py
# Description: Données initiales pour la base de données.
# ==============================================================================

import asyncio
from datetime import datetime, timedelta
import uuid

from src.db.database import get_async_session
from src.models.project import ProjectModel, ProjectStatus, ProjectChain, ProjectPriority, ProjectCategory
from src.models.task import TaskModel, TaskState, TaskPriority, TaskType
from src.models.skill_record import SkillRecordModel, SkillStatus, SkillScope


async def seed_projects():
    """Seed des projets."""
    async with get_async_session() as session:
        # Projet exemple
        project = ProjectModel(
            id=str(uuid.uuid4()),
            name="SecureVault",
            description="A secure token vault with governance",
            status=ProjectStatus.CREATED,
            chain=ProjectChain.ETHEREUM,
            priority=ProjectPriority.HIGH,
            category=ProjectCategory.DEFI,
            spec_yaml="""
project:
  name: SecureVault
  chain: ethereum
  version: 1.0.0
  description: A secure token vault
""",
            config={"deployment": {"safe_address": "0x123..."}},
            tags=["vault", "security", "defi"]
        )
        session.add(project)
        await session.commit()


async def seed_skills():
    """Seed des compétences."""
    async with get_async_session() as session:
        # Compétences prédéfinies
        skills = [
            SkillRecordModel(
                skill_id="solidity_generation",
                name="Solidity Contract Generator",
                description="Generates Solidity smart contracts from specifications",
                prompt_rules="You are an expert Solidity developer. Generate secure, optimized code.",
                input_schema_json={"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}},
                status=SkillStatus.ACTIVE.value,
                scope=SkillScope.GLOBAL.value,
                tags=["solidity", "generation", "smart-contract"]
            ),
            SkillRecordModel(
                skill_id="security_audit",
                name="Security Auditor",
                description="Audits smart contracts for vulnerabilities",
                prompt_rules="You are a security expert. Analyze contracts for vulnerabilities.",
                input_schema_json={"type": "object", "properties": {"code": {"type": "string"}}},
                status=SkillStatus.ACTIVE.value,
                scope=SkillScope.GLOBAL.value,
                tags=["security", "audit", "vulnerability"]
            ),
            SkillRecordModel(
                skill_id="test_generation",
                name="Test Generator",
                description="Generates Foundry tests for smart contracts",
                prompt_rules="You are a test engineer. Generate comprehensive test suites.",
                input_schema_json={"type": "object", "properties": {"contract_code": {"type": "string"}}},
                status=SkillStatus.ACTIVE.value,
                scope=SkillScope.GLOBAL.value,
                tags=["testing", "foundry", "solidity"]
            )
        ]
        
        for skill in skills:
            session.add(skill)
        
        await session.commit()


async def seed_all():
    """Exécute tous les seeds."""
    print("🌱 Seeding database...")
    
    await seed_projects()
    await seed_skills()
    
    print("✅ Database seeded successfully")


if __name__ == "__main__":
    asyncio.run(seed_all())