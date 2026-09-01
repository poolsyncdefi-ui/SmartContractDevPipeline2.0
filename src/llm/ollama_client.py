# src/llm/ollama_client.py
import httpx
from typing import List, Dict, Optional
from src.llm.llm_client import LLMClient
from src.config.settings import settings
from src.core.exceptions import LLMError

class OllamaClient(LLMClient):
    """Client Ollama pour l'inférence LLM locale."""
    
    def __init__(self, base_url: str = None, default_model: str = "deepseek-coder:6.7b-instruct"):
        self.base_url = base_url or settings.ollama_url
        self.default_model = default_model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def generate(self, prompt: str, context: Optional[List[Dict]] = None, **kwargs) -> str:
        """Génère une réponse avec Ollama."""
        try:
            # Construire le prompt complet
            full_prompt = prompt
            if context:
                for msg in context:
                    full_prompt += f"\n{msg.get('role', 'user')}: {msg.get('content', '')}"
            
            response = await self._client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.default_model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": kwargs.get("temperature", 0.1)}
                }
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            raise LLMError(f"Ollama generation error: {e}")

    async def embed(self, text: str) -> List[float]:
        """Génère un embedding avec Ollama."""
        try:
            response = await self._client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.default_model, "prompt": text}
            )
            response.raise_for_status()
            return response.json().get("embedding", [])
        except Exception as e:
            raise LLMError(f"Ollama embedding error: {e}")

    async def check_health(self) -> bool:
        """Vérifie que le serveur Ollama est accessible."""
        try:
            response = await self._client.get(f"{self.base_url}/")
            return response.status_code == 200
        except Exception:
            return False