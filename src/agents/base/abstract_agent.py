# src/agents/base/abstract_agent.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from src.agents.base.skill import BaseSkill
from datetime import datetime

class AbstractAgent(ABC):
    """Classe de base abstraite pour tous les agents du pipeline."""
    
    def __init__(self, agent_id: str, name: str, skills: Optional[List[BaseSkill]] = None):
        self.agent_id = agent_id
        self.name = name
        self.skills = skills or []
        self.history: List[Dict] = []

    @abstractmethod
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute une tâche spécifique.
        
        Args:
            task_data: Dictionnaire contenant les données de la tâche
            
        Returns:
            Dict avec 'status', 'result', etc.
        """
        pass

    def attach_skill(self, skill: BaseSkill) -> None:
        """Ajoute une compétence à l'agent."""
        self.skills.append(skill)

    async def log_execution(self, task_id: str, prompt: str, response: str, tool_output: str) -> None:
        """Enregistre l'exécution d'une tâche dans l'historique."""
        self.history.append({
            "task_id": task_id,
            "prompt": prompt,
            "response": response,
            "tool_output": tool_output,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_capabilities(self) -> List[Dict]:
        """Retourne la liste des compétences de l'agent."""
        return [{"id": s.skill_id, "name": s.name} for s in self.skills]

    def health_check(self) -> Dict:
        """Vérifie l'état de santé de l'agent."""
        return {
            "status": "healthy",
            "agent_id": self.agent_id,
            "skills_count": len(self.skills)
        }