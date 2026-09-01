# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Ollama Client
# ==============================================================================
# Fichier: src/llm/ollama_client.py
# Description: Client Ollama pour l'exécution de modèles LLM locaux.
#              Support de génération, embeddings, streaming, health checks,
#              cache des embeddings et métriques avancées.
# ==============================================================================

import httpx
import json
import asyncio
import hashlib
from typing import Optional, List, Dict, Any, AsyncIterator, Union
from datetime import datetime, timedelta
import logging

from src.llm.llm_client import LLMClient
from src.config.settings import settings
from src.core.exceptions import LLMConnectionError, LLMResponseError, LLMError

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# CLIENT OLLAMA
# ==============================================================================

class OllamaClient(LLMClient):
    """
    Client pour les modèles Ollama locaux.
    
    Supporte:
    - Génération de texte (generate)
    - Embeddings (embed)
    - Streaming (generate_stream)
    - Health checks
    - Cache des embeddings
    - Métriques avancées
    - Gestion des modèles
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        temperature: float = 0.1,
        timeout: int = 60,
        connect_timeout: int = 10,
        max_retries: int = 3,
        cache_embeddings: bool = True,
        cache_ttl: int = 3600,
        **kwargs
    ):
        """
        Initialise le client Ollama.
        
        Args:
            base_url: URL du serveur Ollama
            model: Nom du modèle de génération
            embedding_model: Nom du modèle d'embedding
            temperature: Température par défaut
            timeout: Timeout global en secondes
            connect_timeout: Timeout de connexion en secondes
            max_retries: Nombre maximum de tentatives
            cache_embeddings: Activer le cache des embeddings
            cache_ttl: Durée de vie du cache en secondes
        """
        super().__init__(
            model=model or settings.llm.default_model,
            temperature=temperature,
            timeout=timeout
        )
        
        self.base_url = base_url or settings.llm.ollama_url
        self.embedding_model = embedding_model or settings.llm.embedding_model
        self.connect_timeout = connect_timeout
        self.max_retries = max_retries
        self.cache_embeddings = cache_embeddings
        self.cache_ttl = cache_ttl
        
        # Client HTTP
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False
        
        # Cache des embeddings
        self._embedding_cache: Dict[str, Dict[str, Any]] = {}
        
        # Métriques avancées
        self._metrics = {
            "total_generations": 0,
            "total_embeddings": 0,
            "total_cache_hits": 0,
            "total_cache_misses": 0,
            "total_errors": 0,
            "average_generation_time": 0.0,
            "average_embedding_time": 0.0,
            "last_generation_time": None,
            "last_embedding_time": None,
            "models_available": []
        }
        
        logger.info(f"OllamaClient initialized: base_url={self.base_url}, model={self.model}, embedding_model={self.embedding_model}")
    
    async def _ensure_client(self) -> None:
        """
        S'assure que le client HTTP est initialisé.
        """
        if self._initialized and self._client:
            return
        
        if self._client:
            await self._client.aclose()
        
        # Configuration des timeouts granulaires
        timeout_config = httpx.Timeout(
            timeout=self.timeout,
            connect=self.connect_timeout,
            read=self.timeout,
            write=30.0,
            pool=5.0
        )
        
        self._client = httpx.AsyncClient(
            timeout=timeout_config,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
        self._initialized = True
        
        # Mettre à jour les modèles disponibles
        await self._update_models_available()
    
    async def _update_models_available(self) -> None:
        """
        Met à jour la liste des modèles disponibles.
        """
        try:
            models = await self.list_models()
            self._metrics["models_available"] = models
        except Exception as e:
            logger.warning(f"Failed to update models list: {str(e)}")
    
    async def _request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        method: str = "POST",
        retry_on_failure: bool = True
    ) -> Dict[str, Any]:
        """
        Effectue une requête vers l'API Ollama.
        
        Args:
            endpoint: Endpoint de l'API (ex: "api/generate")
            data: Données de la requête
            method: Méthode HTTP (GET, POST)
            retry_on_failure: Réessayer en cas d'échec
            
        Returns:
            Dict[str, Any]: Réponse JSON
            
        Raises:
            LLMConnectionError: Si la connexion échoue
            LLMResponseError: Si la réponse est invalide
        """
        await self._ensure_client()
        
        url = f"{self.base_url}/{endpoint}"
        start_time = datetime.utcnow()
        
        for attempt in range(self.max_retries if retry_on_failure else 1):
            try:
                if method.upper() == "GET":
                    response = await self._client.get(url)
                else:
                    response = await self._client.post(url, json=data)
                
                response.raise_for_status()
                
                # Mettre à jour les métriques
                duration = (datetime.utcnow() - start_time).total_seconds()
                self._update_metrics(endpoint, duration, success=True)
                
                return response.json()
                
            except httpx.TimeoutException as e:
                if attempt < self.max_retries - 1 and retry_on_failure:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Request timed out, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                raise LLMConnectionError(
                    url=self.base_url,
                    message=f"Request timed out: {str(e)}"
                )
            except httpx.ConnectError as e:
                if attempt < self.max_retries - 1 and retry_on_failure:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Connection failed, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                raise LLMConnectionError(
                    url=self.base_url,
                    message=f"Connection failed: {str(e)}"
                )
            except httpx.HTTPStatusError as e:
                self._metrics["total_errors"] += 1
                raise LLMResponseError(
                    message=f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                )
            except Exception as e:
                self._metrics["total_errors"] += 1
                if attempt < self.max_retries - 1 and retry_on_failure:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Request failed, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                raise LLMError(f"Ollama request failed: {str(e)}")
        
        raise LLMError(f"Request failed after {self.max_retries} attempts")
    
    def _update_metrics(self, endpoint: str, duration: float, success: bool) -> None:
        """
        Met à jour les métriques.
        
        Args:
            endpoint: Endpoint appelé
            duration: Durée de la requête
            success: Succès de la requête
        """
        if "generate" in endpoint:
            self._metrics["total_generations"] += 1
            if success:
                current_avg = self._metrics["average_generation_time"]
                count = self._metrics["total_generations"]
                self._metrics["average_generation_time"] = (
                    (current_avg * (count - 1) + duration) / count
                )
                self._metrics["last_generation_time"] = datetime.utcnow()
        elif "embeddings" in endpoint:
            self._metrics["total_embeddings"] += 1
            if success:
                current_avg = self._metrics["average_embedding_time"]
                count = self._metrics["total_embeddings"]
                self._metrics["average_embedding_time"] = (
                    (current_avg * (count - 1) + duration) / count
                )
                self._metrics["last_embedding_time"] = datetime.utcnow()
    
    # ==========================================================================
    # GÉNÉRATION
    # ==========================================================================
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        num_ctx: Optional[int] = None,
        num_gpu: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Génère une réponse à partir d'un prompt.
        
        Args:
            prompt: Prompt principal
            system_prompt: Prompt système (optionnel)
            temperature: Température (remplace la valeur par défaut)
            max_tokens: Nombre maximum de tokens
            top_p: Top-p sampling
            top_k: Top-k sampling
            repeat_penalty: Pénalité de répétition
            num_ctx: Taille du contexte
            num_gpu: Nombre de GPUs à utiliser
            **kwargs: Arguments supplémentaires
            
        Returns:
            str: Réponse générée
        """
        self._request_count += 1
        self._last_request_time = datetime.utcnow()
        
        # Préparer les données
        data = {
            "model": self.model,
            "prompt": prompt,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": False,
            **kwargs
        }
        
        if system_prompt:
            data["system"] = system_prompt
        
        # Options avancées
        options = {}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if top_p is not None:
            options["top_p"] = top_p
        if top_k is not None:
            options["top_k"] = top_k
        if repeat_penalty is not None:
            options["repeat_penalty"] = repeat_penalty
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        if num_gpu is not None:
            options["num_gpu"] = num_gpu
        
        if options:
            data["options"] = options
        
        try:
            logger.debug(f"Sending generation request to {self.model}")
            response = await self._request("api/generate", data)
            
            if "response" not in response:
                raise LLMResponseError(
                    message="Missing 'response' field in Ollama response",
                    response_preview=json.dumps(response)[:200]
                )
            
            return response["response"].strip()
            
        except LLMConnectionError:
            raise
        except LLMResponseError:
            raise
        except Exception as e:
            raise LLMError(f"Generation failed: {str(e)}")
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Génère une réponse en streaming.
        
        Args:
            prompt: Prompt principal
            system_prompt: Prompt système (optionnel)
            temperature: Température
            max_tokens: Nombre maximum de tokens
            **kwargs: Arguments supplémentaires
            
        Yields:
            str: Tokens générés en streaming
        """
        self._request_count += 1
        self._last_request_time = datetime.utcnow()
        
        await self._ensure_client()
        
        # Préparer les données
        data = {
            "model": self.model,
            "prompt": prompt,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": True,
            **kwargs
        }
        
        if system_prompt:
            data["system"] = system_prompt
        
        if max_tokens:
            data["options"] = {"num_predict": max_tokens}
        
        url = f"{self.base_url}/api/generate"
        
        try:
            async with self._client.stream("POST", url, json=data) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            if "response" in chunk:
                                yield chunk["response"]
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            raise LLMError(f"Streaming generation failed: {str(e)}")
    
    # ==========================================================================
    # EMBEDDINGS AVEC CACHE
    # ==========================================================================
    
    async def embed(self, text: str, use_cache: bool = True) -> List[float]:
        """
        Génère un embedding pour un texte avec cache.
        
        Args:
            text: Texte à encoder
            use_cache: Utiliser le cache
            
        Returns:
            List[float]: Embedding vectoriel
        """
        # Vérifier le cache
        if use_cache and self.cache_embeddings:
            cache_key = hashlib.md5(text.encode()).hexdigest()
            if cache_key in self._embedding_cache:
                cache_entry = self._embedding_cache[cache_key]
                # Vérifier le TTL
                if (datetime.utcnow() - cache_entry["timestamp"]).total_seconds() < self.cache_ttl:
                    self._metrics["total_cache_hits"] += 1
                    logger.debug(f"Embedding cache hit for key: {cache_key[:8]}")
                    return cache_entry["embedding"]
                else:
                    # Cache expiré
                    del self._embedding_cache[cache_key]
        
        self._metrics["total_cache_misses"] += 1
        
        # Générer l'embedding
        data = {
            "model": self.embedding_model,
            "prompt": text
        }
        
        try:
            response = await self._request("api/embeddings", data)
            
            if "embedding" not in response:
                raise LLMResponseError(
                    message="Missing 'embedding' field in Ollama response",
                    response_preview=json.dumps(response)[:200]
                )
            
            embedding = response["embedding"]
            
            # Mettre en cache
            if use_cache and self.cache_embeddings:
                cache_key = hashlib.md5(text.encode()).hexdigest()
                self._embedding_cache[cache_key] = {
                    "embedding": embedding,
                    "timestamp": datetime.utcnow(),
                    "text": text[:100]  # Aperçu
                }
                logger.debug(f"Embedding cached with key: {cache_key[:8]}")
            
            return embedding
            
        except Exception as e:
            raise LLMError(f"Embedding generation failed: {str(e)}")
    
    async def embed_batch(self, texts: List[str], use_cache: bool = True) -> List[List[float]]:
        """
        Génère des embeddings pour plusieurs textes en parallèle.
        
        Args:
            texts: Liste des textes à encoder
            use_cache: Utiliser le cache
            
        Returns:
            List[List[float]]: Liste des embeddings
        """
        tasks = [self.embed(text, use_cache) for text in texts]
        return await asyncio.gather(*tasks)
    
    async def clear_embedding_cache(self) -> int:
        """
        Vide le cache des embeddings.
        
        Returns:
            int: Nombre d'entrées supprimées
        """
        count = len(self._embedding_cache)
        self._embedding_cache.clear()
        logger.info(f"Cleared {count} cached embeddings")
        return count
    
    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du cache des embeddings.
        
        Returns:
            Dict[str, Any]: Statistiques du cache
        """
        return {
            "total_cached": len(self._embedding_cache),
            "cache_hits": self._metrics["total_cache_hits"],
            "cache_misses": self._metrics["total_cache_misses"],
            "hit_rate": (
                self._metrics["total_cache_hits"] / (self._metrics["total_cache_hits"] + self._metrics["total_cache_misses"])
                if self._metrics["total_cache_hits"] + self._metrics["total_cache_misses"] > 0
                else 0
            ),
            "ttl_seconds": self.cache_ttl
        }
    
    # ==========================================================================
    # HEALTH CHECK
    # ==========================================================================
    
    async def health_check(self) -> bool:
        """
        Vérifie si le serveur Ollama est disponible.
        
        Returns:
            bool: True si disponible
        """
        try:
            await self._ensure_client()
            response = await self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed: {str(e)}")
            return False
    
    async def health_check_detailed(self) -> Dict[str, Any]:
        """
        Vérification de santé détaillée.
        
        Returns:
            Dict[str, Any]: Informations de santé détaillées
        """
        result = {
            "status": "unknown",
            "version": None,
            "models": [],
            "default_model": self.model,
            "embedding_model": self.embedding_model
        }
        
        try:
            await self._ensure_client()
            
            # Vérifier la disponibilité
            response = await self._client.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                result["status"] = "healthy"
                result["version"] = data.get("version", "unknown")
                result["models"] = [m.get("name") for m in data.get("models", [])]
                
                # Vérifier que le modèle par défaut est disponible
                if self.model not in result["models"]:
                    result["status"] = "degraded"
                    result["warning"] = f"Default model '{self.model}' not found"
            else:
                result["status"] = "unhealthy"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)
        
        return result
    
    # ==========================================================================
    # GESTION DES MODÈLES
    # ==========================================================================
    
    async def list_models(self) -> List[str]:
        """
        Liste les modèles disponibles sur le serveur Ollama.
        
        Returns:
            List[str]: Liste des noms de modèles
        """
        try:
            response = await self._request("api/tags", {}, method="GET", retry_on_failure=False)
            models = response.get("models", [])
            return [model.get("name", "unknown") for model in models]
        except Exception as e:
            logger.error(f"Failed to list models: {str(e)}")
            return []
    
    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """
        Récupère les informations d'un modèle.
        
        Args:
            model_name: Nom du modèle
            
        Returns:
            Dict[str, Any]: Informations du modèle
        """
        try:
            response = await self._request("api/show", {"name": model_name})
            return response
        except Exception as e:
            logger.error(f"Failed to get model info for {model_name}: {str(e)}")
            return {}
    
    async def pull_model(
        self,
        model_name: str,
        stream: bool = False,
        callback: Optional[Callable[[str], None]] = None
    ) -> Union[bool, AsyncIterator[str]]:
        """
        Télécharge un modèle depuis Ollama.
        
        Args:
            model_name: Nom du modèle à télécharger
            stream: Retourner un stream des progrès
            callback: Fonction de callback pour les progrès
            
        Returns:
            Union[bool, AsyncIterator[str]]: True si réussi ou stream des progrès
        """
        if stream:
            return self._pull_model_stream(model_name, callback)
        
        try:
            await self._request("api/pull", {"name": model_name})
            logger.info(f"Model {model_name} pulled successfully")
            await self._update_models_available()
            return True
        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {str(e)}")
            return False
    
    async def _pull_model_stream(
        self,
        model_name: str,
        callback: Optional[Callable[[str], None]] = None
    ) -> AsyncIterator[str]:
        """
        Télécharge un modèle en streaming.
        
        Args:
            model_name: Nom du modèle
            callback: Fonction de callback pour les progrès
            
        Yields:
            str: Messages de progression
        """
        await self._ensure_client()
        
        url = f"{self.base_url}/api/pull"
        data = {"name": model_name}
        
        try:
            async with self._client.stream("POST", url, json=data) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            status = chunk.get("status", "")
                            if callback:
                                callback(status)
                            yield status
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            raise LLMError(f"Model pull failed: {str(e)}")
    
    async def delete_model(self, model_name: str) -> bool:
        """
        Supprime un modèle.
        
        Args:
            model_name: Nom du modèle à supprimer
            
        Returns:
            bool: True si réussi
        """
        try:
            await self._request("api/delete", {"name": model_name})
            logger.info(f"Model {model_name} deleted successfully")
            await self._update_models_available()
            return True
        except Exception as e:
            logger.error(f"Failed to delete model {model_name}: {str(e)}")
            return False
    
    # ==========================================================================
    # MÉTRIQUES
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques détaillées du client.
        
        Returns:
            Dict[str, Any]: Statistiques détaillées
        """
        return {
            "model": self.model,
            "embedding_model": self.embedding_model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "request_count": self._request_count,
            "last_request": self._last_request_time.isoformat() if self._last_request_time else None,
            **self._metrics,
            "embedding_cache": self.get_embedding_cache_stats(),
            "is_connected": self._initialized,
            "base_url": self.base_url
        }
    
    # ==========================================================================
    # FERMETURE
    # ==========================================================================
    
    async def close(self) -> None:
        """
        Ferme le client HTTP.
        """
        if self._client:
            await self._client.aclose()
            self._initialized = False
            logger.debug("Ollama client closed")
    
    async def __aenter__(self):
        await self._ensure_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()