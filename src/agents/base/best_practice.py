# src/agents/base/best_practice.py
from abc import ABC, abstractmethod
from typing import Dict, Any
from src.core.models import BestPractice as BestPracticeConfig

class BaseBestPractice(ABC):
    """Classe de base pour les bonnes pratiques."""
    
    def __init__(self, config: BestPracticeConfig):
        self.config = config
    
    @abstractmethod
    async def validate(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valide la sortie d'une compétence.
        Retourne: {"passed": bool, "message": str, "details": dict}
        """
        pass