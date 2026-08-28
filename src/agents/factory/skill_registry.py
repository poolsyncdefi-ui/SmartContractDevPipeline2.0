# src/agents/factory/skill_registry.py
from typing import Dict, List, Type
from src.agents.base.skill import BaseSkill
from src.core.exceptions import SkillNotFoundError

class SkillRegistry:
    """Registre singleton des compétences disponibles."""
    
    _instance = None
    _skills: Dict[str, Type[BaseSkill]] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, skill_id: str, skill_class: Type[BaseSkill]) -> None:
        """Enregistre une compétence."""
        self._skills[skill_id] = skill_class
    
    def get(self, skill_id: str) -> Type[BaseSkill]:
        """Récupère une compétence par son ID."""
        if skill_id not in self._skills:
            raise SkillNotFoundError(skill_id=skill_id, message=f"Skill '{skill_id}' not found")
        return self._skills[skill_id]
    
    def has_skill(self, skill_id: str) -> bool:
        """Vérifie si une compétence existe."""
        return skill_id in self._skills
    
    def list_skills(self) -> List[str]:
        """Liste tous les IDs de compétences."""
        return list(self._skills.keys())