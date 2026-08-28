# src/agents/base/abstract_agent.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from src.agents.base.skill import BaseSkill

class AbstractAgent(ABC):
    """Classe de base abstraite pour tous les agents du pipeline."""
    
    def __init__(self, agent_id: str, name: str, skills: Optional[List[BaseSkill]] = None):
        self.agent_id = agent_id
        self.name = name
        self.skills = skills or []
        self.history: List[Dict] = []
    
    @abstractmethod
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Exécute une tâche spécifique."""
        pass
    
    def attach_skill(self, skill: BaseSkill) -> None:
        """Ajoute une compétence à l'agent."""
        self.skills.append(skill)
    
    async def log_execution(self, task_id: str, prompt: str, response: str, tool_output: str) -> None:
        """Enregistre l'exécution d'une tâche."""
        self.history.append({
            "task_id": task_id,
            "prompt": prompt,
            "response": response,
            "tool_output": tool_output,
            "timestamp": datetime.utcnow().isoformat()
        })