# src/persistence/knowledge_base.py
import chromadb
from chromadb.config import Settings
from typing import Dict, List, Any, Optional
from src.llm.llm_client import LLMClient
from src.config.settings import settings
from src.core.exceptions import KnowledgeBaseError

class KnowledgeBase:
    """Wrapper autour de ChromaDB pour l'indexation vectorielle."""
    
    def __init__(self, collection_name: str = "web3_docs", llm_client: Optional[LLMClient] = None):
        try:
            self.client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=Settings(anonymized_telemetry=False)
            )
            self.collection = self.client.get_or_create_collection(name=collection_name)
        except Exception as e:
            raise KnowledgeBaseError(f"Failed to connect to ChromaDB: {e}")
        self.llm = llm_client

    async def add_artifact(self, artifact: Dict) -> str:
        """Ajoute un artefact à la base de connaissances."""
        # À implémenter
        return artifact.get("id", "")

    async def query(self, text: str, top_k: int = 5) -> List[Dict]:
        """Interroge la base de connaissances par similarité."""
        # À implémenter
        return []

    async def _get_embedding(self, text: str) -> List[float]:
        """Génère un embedding pour un texte."""
        if not self.llm:
            raise KnowledgeBaseError("LLM client not set for embedding generation")
        return await self.llm.embed(text)