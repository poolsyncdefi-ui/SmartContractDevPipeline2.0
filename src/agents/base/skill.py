# src/agents/base/skill.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Dict, Any, Type, Optional
from src.core.models import Skill as SkillConfig

class BaseSkill(ABC):
    """Classe de base pour toutes les compétences."""
    
    skill_id: str
    name: str
    description: str
    input_schema: Type[BaseModel]
    
    def __init__(self, config: SkillConfig, llm_client=None, knowledge_base=None):
        self.config = config
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Exécute la compétence avec les paramètres donnés."""
        pass
    
    @abstractmethod
    def get_system_prompt_rules(self) -> str:
        """Retourne les règles système pour le prompt."""
        pass
    
    def validate_parameters(self, params: Dict[str, Any]) -> BaseModel:
        """Valide les paramètres d'entrée."""
        return self.input_schema(**params)
    
    def set_llm_client(self, client) -> None:
        """Injecte le client LLM."""
        self.llm_client = client
    
    def set_knowledge_base(self, kb) -> None:
        """Injecte la base de connaissances."""
        self.knowledge_base = kb