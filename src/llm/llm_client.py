# src/llm/llm_client.py
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class LLMClient(ABC):
    """Interface abstraite pour les clients LLM."""
    
    @abstractmethod
    async def generate(self, prompt: str, context: Optional[List[Dict]] = None, **kwargs) -> str:
        """Génère une réponse à partir d'un prompt."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Génère un embedding pour un texte."""
        pass