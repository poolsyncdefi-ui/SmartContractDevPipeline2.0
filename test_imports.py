# test_imports.py
print("=== Test des imports du pipeline ===\n")

try:
    from src.agents.base.abstract_agent import AbstractAgent
    print("✅ AbstractAgent importé")
except Exception as e:
    print(f"❌ AbstractAgent : {e}")

try:
    from src.agents.base.skill import BaseSkill
    print("✅ BaseSkill importé")
except Exception as e:
    print(f"❌ BaseSkill : {e}")

try:
    from src.agents.base.best_practice import BaseBestPractice
    print("✅ BaseBestPractice importé")
except Exception as e:
    print(f"❌ BaseBestPractice : {e}")

try:
    from src.agents.factory.skill_registry import SkillRegistry
    print("✅ SkillRegistry importé")
except Exception as e:
    print(f"❌ SkillRegistry : {e}")

try:
    from src.agents.factory.agent_factory import AgentFactory
    print("✅ AgentFactory importé")
except Exception as e:
    print(f"❌ AgentFactory : {e}")

try:
    from src.agents.templates.developer_agent import DeveloperAgent
    print("✅ DeveloperAgent importé")
except Exception as e:
    print(f"❌ DeveloperAgent : {e}")

try:
    from src.agents.templates.architect_agent import ArchitectAgent
    print("✅ ArchitectAgent importé")
except Exception as e:
    print(f"❌ ArchitectAgent : {e}")

print("\n=== Test terminé ===")