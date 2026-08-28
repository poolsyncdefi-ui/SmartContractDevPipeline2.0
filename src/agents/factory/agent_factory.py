# src/agents/factory/agent_factory.py
from typing import List, Type, Dict, Any
from src.agents.base.abstract_agent import AbstractAgent
from src.agents.factory.skill_registry import SkillRegistry
from src.agents.base.skill import BaseSkill
from src.core.exceptions import SkillNotFoundError

class AgentFactory:
    """Fabrique d'instanciation d'agents."""
    
    def __init__(self, registry: SkillRegistry, llm_client=None, knowledge_base=None):
        self.registry = registry
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self._templates: Dict[str, Type[AbstractAgent]] = {}
    
    def register_agent_template(self, role_name: str, agent_class: Type[AbstractAgent]) -> None:
        """Enregistre un template d'agent."""
        self._templates[role_name] = agent_class
    
    def create_agent(self, agent_id: str, role_name: str, skill_ids: List[str]) -> AbstractAgent:
        """Crée un agent avec les compétences spécifiées."""
        agent_cls = self._templates.get(role_name)
        if not agent_cls:
            raise ValueError(f"Agent template '{role_name}' not found")
        
        skills = []
        for skill_id in skill_ids:
            skill_cls = self.registry.get(skill_id)
            # On instancie la compétence avec ses dépendances
            # Note: la configuration de la compétence doit être chargée depuis un catalogue
            skill_instance = skill_cls(skill_id, self.llm_client, self.knowledge_base)
            skills.append(skill_instance)
        
        return agent_cls(agent_id=agent_id, name=role_name, skills=skills)