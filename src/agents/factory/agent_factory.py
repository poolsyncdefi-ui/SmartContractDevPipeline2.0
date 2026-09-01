# src/agents/factory/agent_factory.py
from typing import List, Type, Dict, Any
from src.agents.base.abstract_agent import AbstractAgent
from src.agents.factory.skill_registry import SkillRegistry
from src.core.models import Skill, BestPractice
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase

class AgentFactory:
    """Fabrique d'instanciation d'agents."""
    
    def __init__(self, registry: SkillRegistry, llm_client: LLMClient = None, knowledge_base: KnowledgeBase = None):
        self.registry = registry
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self._templates: Dict[str, Type[AbstractAgent]] = {}
        self._skill_configs: Dict[str, Skill] = {}
        self._practice_configs: Dict[str, BestPractice] = {}

    def register_agent_template(self, role_name: str, agent_class: Type[AbstractAgent]) -> None:
        """Enregistre un template d'agent."""
        self._templates[role_name] = agent_class

    def load_configs(self, skill_configs: Dict[str, Skill], practice_configs: Dict[str, BestPractice]) -> None:
        """Charge les configurations des compétences et des pratiques."""
        self._skill_configs = skill_configs
        self._practice_configs = practice_configs

    def create_agent(self, agent_id: str, role_name: str, skill_ids: List[str]) -> AbstractAgent:
        """Crée un agent avec les compétences spécifiées."""
        agent_cls = self._templates.get(role_name)
        if not agent_cls:
            raise ValueError(f"Agent template '{role_name}' not found")
        
        skills = []
        for skill_id in skill_ids:
            skill_cls = self.registry.get(skill_id)
            skill_config = self._skill_configs.get(skill_id)
            if not skill_config:
                raise ValueError(f"Skill config for '{skill_id}' not found")
            skill_instance = skill_cls(skill_config, llm_client=self.llm_client, knowledge_base=self.knowledge_base)
            skills.append(skill_instance)
        
        return agent_cls(agent_id=agent_id, name=role_name, skills=skills)