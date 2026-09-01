# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - LLM Client Interface
# ==============================================================================
# Fichier: src/llm/llm_client.py
# Description: Interface abstraite pour les clients LLM.
#              Support de multiples fournisseurs (Ollama, OpenAI, etc.).
#              Métriques avancées, cache, callbacks et gestion des coûts.
# ==============================================================================

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union, AsyncIterator, Callable, Awaitable
from datetime import datetime
from dataclasses import dataclass, field
import logging
import asyncio
import hashlib
import json
from enum import Enum

from src.core.exceptions import LLMError, LLMConnectionError, LLMResponseError

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# ENUMS
# ==============================================================================

class LLMProvider(str, Enum):
    """Fournisseurs LLM supportés."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    MOCK = "mock"


class LLMModelType(str, Enum):
    """Types de modèles LLM."""
    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    CODE = "code"


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class LLMRequest:
    """Requête LLM."""
    id: str = field(default_factory=lambda: hashlib.md5(str(datetime.utcnow().timestamp()).encode()).hexdigest()[:8])
    prompt: str = ""
    system_prompt: Optional[str] = None
    temperature: float = 0.1
    max_tokens: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit la requête en dictionnaire."""
        return {
            "id": self.id,
            "prompt": self.prompt[:200] + "..." if len(self.prompt) > 200 else self.prompt,
            "system_prompt": self.system_prompt[:200] + "..." if self.system_prompt and len(self.system_prompt) > 200 else self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "model": self.model,
            "provider": self.provider,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class LLMResponse:
    """Réponse LLM."""
    text: str = ""
    model: Optional[str] = None
    provider: Optional[str] = None
    duration_ms: float = 0.0
    tokens_used: Optional[int] = None
    cost: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit la réponse en dictionnaire."""
        return {
            "text": self.text[:200] + "..." if len(self.text) > 200 else self.text,
            "model": self.model,
            "provider": self.provider,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "cost": self.cost,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class LLMMetrics:
    """Métriques d'utilisation du LLM."""
    total_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    total_duration_ms: float = 0.0
    average_duration_ms: float = 0.0
    requests_per_second: float = 0.0
    tokens_per_second: float = 0.0
    by_model: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_provider: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_request: Optional[datetime] = None
    first_request: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "total_duration_ms": self.total_duration_ms,
            "average_duration_ms": self.average_duration_ms,
            "requests_per_second": self.requests_per_second,
            "tokens_per_second": self.tokens_per_second,
            "by_model": self.by_model,
            "by_provider": self.by_provider,
            "last_request": self.last_request.isoformat() if self.last_request else None,
            "first_request": self.first_request.isoformat() if self.first_request else None
        }


# ==============================================================================
# INTERFACE LLM
# ==============================================================================

class LLMClient(ABC):
    """
    Interface abstraite pour les clients LLM.
    Tous les clients LLM doivent implémenter cette interface.
    
    Supporte:
    - Génération de texte (generate)
    - Streaming (generate_stream)
    - Embeddings (embed)
    - Health checks
    - Liste des modèles
    - Métriques avancées
    - Cache des réponses
    - Callbacks
    - Gestion des coûts
    """
    
    def __init__(
        self,
        model: str,
        temperature: float = 0.1,
        timeout: int = 60,
        provider: str = "unknown",
        cache_enabled: bool = False,
        cache_ttl: int = 3600
    ):
        """
        Initialise le client LLM.
        
        Args:
            model: Nom du modèle à utiliser
            temperature: Température pour la génération (0-1)
            timeout: Timeout en secondes
            provider: Nom du fournisseur
            cache_enabled: Activer le cache des réponses
            cache_ttl: Durée de vie du cache en secondes
        """
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.provider = provider
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        
        self._last_request_time: Optional[datetime] = None
        self._request_count = 0
        self._metrics = LLMMetrics()
        self._callbacks: List[Callable[[LLMRequest, Optional[LLMResponse], Optional[Exception]], Awaitable[None]]] = []
        self._cache: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"LLMClient initialized: model={model}, provider={provider}, temperature={temperature}")
    
    # ==========================================================================
    # MÉTHODES ABSTRAITES
    # ==========================================================================
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Génère une réponse à partir d'un prompt.
        
        Args:
            prompt: Prompt principal
            system_prompt: Prompt système (optionnel)
            temperature: Température (remplace la valeur par défaut)
            max_tokens: Nombre maximum de tokens
            **kwargs: Arguments supplémentaires
            
        Returns:
            str: Réponse générée
            
        Raises:
            LLMConnectionError: Si la connexion échoue
            LLMResponseError: Si la réponse est invalide
            LLMError: Pour les autres erreurs
        """
        pass
    
    @abstractmethod
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
            
        Raises:
            LLMError: Si la génération échoue
        """
        pass
    
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """
        Génère un embedding pour un texte.
        
        Args:
            text: Texte à encoder
            
        Returns:
            List[float]: Embedding vectoriel
            
        Raises:
            LLMError: Si l'embedding échoue
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Vérifie si le serveur LLM est disponible.
        
        Returns:
            bool: True si disponible
        """
        pass
    
    @abstractmethod
    async def list_models(self) -> List[str]:
        """
        Liste les modèles disponibles.
        
        Returns:
            List[str]: Liste des noms de modèles
        """
        pass
    
    # ==========================================================================
    # MÉTHODES CONCRÈTES AVEC CACHE ET MÉTRIQUES
    # ==========================================================================
    
    def _generate_cache_key(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """Génère une clé de cache pour une requête."""
        cache_data = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens,
            "model": self.model,
            "kwargs": kwargs
        }
        # Trier les clés pour garantir la cohérence
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[str]:
        """Récupère une réponse du cache."""
        if not self.cache_enabled:
            return None
        
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if (datetime.utcnow() - entry["timestamp"]).total_seconds() < self.cache_ttl:
                logger.debug(f"Cache hit for key: {cache_key[:8]}")
                return entry["response"]
            else:
                # Cache expiré
                del self._cache[cache_key]
        
        return None
    
    def _set_cache(self, cache_key: str, response: str) -> None:
        """Stocke une réponse dans le cache."""
        if self.cache_enabled:
            self._cache[cache_key] = {
                "response": response,
                "timestamp": datetime.utcnow()
            }
    
    def _update_metrics(
        self,
        request: LLMRequest,
        response: Optional[LLMResponse] = None,
        error: Optional[Exception] = None
    ) -> None:
        """Met à jour les métriques."""
        self._metrics.total_requests += 1
        self._request_count += 1
        self._last_request_time = datetime.utcnow()
        
        if not self._metrics.first_request:
            self._metrics.first_request = datetime.utcnow()
        
        self._metrics.last_request = datetime.utcnow()
        
        if response:
            self._metrics.total_tokens += response.tokens_used or 0
            self._metrics.total_cost += response.cost or 0
            self._metrics.total_duration_ms += response.duration_ms
            
            # Mise à jour des moyennes
            if self._metrics.total_requests > 0:
                self._metrics.average_duration_ms = self._metrics.total_duration_ms / self._metrics.total_requests
            
            # Par modèle
            model = response.model or self.model
            if model not in self._metrics.by_model:
                self._metrics.by_model[model] = {"requests": 0, "tokens": 0, "cost": 0}
            self._metrics.by_model[model]["requests"] += 1
            self._metrics.by_model[model]["tokens"] += response.tokens_used or 0
            self._metrics.by_model[model]["cost"] += response.cost or 0
            
            # Par fournisseur
            provider = response.provider or self.provider
            if provider not in self._metrics.by_provider:
                self._metrics.by_provider[provider] = {"requests": 0, "tokens": 0, "cost": 0}
            self._metrics.by_provider[provider]["requests"] += 1
            self._metrics.by_provider[provider]["tokens"] += response.tokens_used or 0
            self._metrics.by_provider[provider]["cost"] += response.cost or 0
            
            # Taux
            elapsed = (datetime.utcnow() - self._metrics.first_request).total_seconds()
            if elapsed > 0:
                self._metrics.requests_per_second = self._metrics.total_requests / elapsed
                self._metrics.tokens_per_second = self._metrics.total_tokens / elapsed
    
    async def _notify_callbacks(
        self,
        request: LLMRequest,
        response: Optional[LLMResponse] = None,
        error: Optional[Exception] = None
    ) -> None:
        """Notifie les callbacks."""
        for callback in self._callbacks:
            try:
                await callback(request, response, error)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    # ==========================================================================
    # MÉTHODES PUBLIQUES AVANCÉES
    # ==========================================================================
    
    async def generate_with_cache(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Génère une réponse avec cache.
        
        Args:
            prompt: Prompt principal
            system_prompt: Prompt système (optionnel)
            temperature: Température
            max_tokens: Nombre maximum de tokens
            **kwargs: Arguments supplémentaires
            
        Returns:
            str: Réponse générée
        """
        request = LLMRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens,
            model=self.model,
            provider=self.provider,
            metadata=kwargs
        )
        
        # Vérifier le cache
        cache_key = self._generate_cache_key(prompt, system_prompt, temperature, max_tokens, **kwargs)
        cached_response = self._get_from_cache(cache_key)
        
        if cached_response is not None:
            response = LLMResponse(
                text=cached_response,
                model=self.model,
                provider=self.provider,
                metadata={"from_cache": True}
            )
            await self._notify_callbacks(request, response)
            return cached_response
        
        # Générer la réponse
        try:
            start_time = datetime.utcnow()
            
            response_text = await self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            response = LLMResponse(
                text=response_text,
                model=self.model,
                provider=self.provider,
                duration_ms=duration_ms,
                metadata={"from_cache": False}
            )
            
            # Mettre en cache
            self._set_cache(cache_key, response_text)
            
            # Mettre à jour les métriques
            self._update_metrics(request, response)
            
            # Notifier les callbacks
            await self._notify_callbacks(request, response)
            
            return response_text
            
        except Exception as e:
            self._update_metrics(request, error=e)
            await self._notify_callbacks(request, error=e)
            raise
    
    async def generate_with_retry(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
        **kwargs
    ) -> str:
        """
        Génère une réponse avec tentative automatique en cas d'échec.
        
        Args:
            prompt: Prompt principal
            system_prompt: Prompt système (optionnel)
            temperature: Température
            max_tokens: Nombre maximum de tokens
            max_retries: Nombre maximum de tentatives
            **kwargs: Arguments supplémentaires
            
        Returns:
            str: Réponse générée
            
        Raises:
            LLMError: Si toutes les tentatives échouent
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await self.generate_with_cache(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
            except (LLMConnectionError, LLMResponseError) as e:
                last_error = e
                logger.warning(
                    f"LLM request failed (attempt {attempt + 1}/{max_retries}): {str(e)}"
                )
                if attempt < max_retries - 1:
                    wait_time = 2 ** (attempt + 1)
                    await asyncio.sleep(wait_time)
        
        raise LLMError(f"All {max_retries} retries failed: {last_error}")
    
    async def generate_with_context(
        self,
        prompt: str,
        context: List[str],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        Génère une réponse avec contexte enrichi (RAG).
        
        Args:
            prompt: Prompt principal
            context: Liste de textes de contexte
            system_prompt: Prompt système (optionnel)
            temperature: Température
            **kwargs: Arguments supplémentaires
            
        Returns:
            str: Réponse générée
        """
        if context:
            context_text = "\n\n".join(context)
            enriched_prompt = f"Context:\n{context_text}\n\n{prompt}"
        else:
            enriched_prompt = prompt
        
        return await self.generate_with_cache(
            prompt=enriched_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            **kwargs
        )
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Génère des embeddings pour plusieurs textes.
        
        Args:
            texts: Liste des textes à encoder
            
        Returns:
            List[List[float]]: Liste des embeddings
        """
        tasks = [self.embed(text) for text in texts]
        return await asyncio.gather(*tasks)
    
    # ==========================================================================
    # GESTION DES CALLBACKS
    # ==========================================================================
    
    def add_callback(
        self,
        callback: Callable[[LLMRequest, Optional[LLMResponse], Optional[Exception]], Awaitable[None]]
    ) -> None:
        """
        Ajoute un callback pour le suivi des requêtes.
        
        Args:
            callback: Fonction async appelée avec (request, response, error)
        """
        self._callbacks.append(callback)
    
    def remove_callback(
        self,
        callback: Callable[[LLMRequest, Optional[LLMResponse], Optional[Exception]], Awaitable[None]]
    ) -> None:
        """
        Supprime un callback.
        
        Args:
            callback: Fonction de callback à supprimer
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    # ==========================================================================
    # MÉTRIQUES ET STATISTIQUES
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques d'utilisation.
        
        Returns:
            Dict[str, Any]: Statistiques
        """
        return {
            "model": self.model,
            "provider": self.provider,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "request_count": self._request_count,
            "cache_enabled": self.cache_enabled,
            "cache_size": len(self._cache),
            "last_request": self._last_request_time.isoformat() if self._last_request_time else None,
            "metrics": self._metrics.to_dict()
        }
    
    def get_metrics(self) -> LLMMetrics:
        """
        Retourne les métriques d'utilisation.
        
        Returns:
            LLMMetrics: Métriques
        """
        return self._metrics
    
    def clear_cache(self) -> int:
        """
        Vide le cache des réponses.
        
        Returns:
            int: Nombre d'entrées supprimées
        """
        cache_size = len(self._cache)
        self._cache.clear()
        logger.info(f"Cleared {cache_size} cached responses")
        return cache_size
    
    # ==========================================================================
    # GESTION DES COÛTS
    # ==========================================================================
    
    def estimate_cost(self, tokens: int, model: Optional[str] = None) -> float:
        """
        Estime le coût d'une requête.
        
        Args:
            tokens: Nombre de tokens
            model: Modèle utilisé (optionnel)
            
        Returns:
            float: Coût estimé
        """
        # Tarifs par défaut (à ajuster selon le fournisseur)
        rates = {
            "gpt-4": {"input": 0.00003, "output": 0.00006},
            "gpt-3.5-turbo": {"input": 0.000001, "output": 0.000002},
            "claude-3": {"input": 0.000015, "output": 0.000075},
            "default": {"input": 0.000001, "output": 0.000002}
        }
        
        model_key = model or self.model
        rate = rates.get(model_key, rates["default"])
        
        # Estimation simplifiée (50% input, 50% output)
        input_tokens = tokens // 2
        output_tokens = tokens - input_tokens
        
        return (input_tokens * rate["input"]) + (output_tokens * rate["output"])
    
    # ==========================================================================
    # FERMETURE
    # ==========================================================================
    
    async def close(self) -> None:
        """
        Ferme le client et libère les ressources.
        """
        pass
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# ==============================================================================
# CLIENT LLM DE TEST (MOCK)
# ==============================================================================

class MockLLMClient(LLMClient):
    """
    Client LLM de test qui simule les réponses.
    Utile pour les tests et le développement.
    """
    
    def __init__(
        self,
        model: str = "mock-model",
        temperature: float = 0.1,
        timeout: int = 60,
        **kwargs
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            timeout=timeout,
            provider="mock",
            **kwargs
        )
        self._responses: List[str] = []
        self._stream_responses: List[str] = []
        self._embedding_dimension = 128
        self._delay_ms = 0
    
    def add_response(self, response: str) -> None:
        """
        Ajoute une réponse simulée (non-streaming).
        
        Args:
            response: Réponse à ajouter
        """
        self._responses.append(response)
    
    def add_stream_response(self, tokens: List[str]) -> None:
        """
        Ajoute une réponse simulée pour le streaming.
        
        Args:
            tokens: Liste des tokens à générer en streaming
        """
        self._stream_responses.extend(tokens)
    
    def set_embedding_dimension(self, dimension: int) -> None:
        """
        Définit la dimension des embeddings simulés.
        
        Args:
            dimension: Dimension des embeddings
        """
        self._embedding_dimension = dimension
    
    def set_delay(self, delay_ms: int) -> None:
        """
        Définit un délai de simulation.
        
        Args:
            delay_ms: Délai en millisecondes
        """
        self._delay_ms = delay_ms
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        self._request_count += 1
        self._last_request_time = datetime.utcnow()
        
        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)
        
        if self._responses:
            return self._responses.pop(0)
        
        # Réponse par défaut
        prompt_preview = prompt[:50] + "..." if len(prompt) > 50 else prompt
        return f"Mock response for: {prompt_preview}"
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        self._request_count += 1
        self._last_request_time = datetime.utcnow()
        
        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)
        
        if self._stream_responses:
            for token in self._stream_responses:
                yield token
            return
        
        # Streaming simulé
        prompt_preview = prompt[:30] + "..." if len(prompt) > 30 else prompt
        yield "Mock streaming response for: "
        for char in prompt_preview:
            yield char
            await asyncio.sleep(0.05)
    
    async def embed(self, text: str) -> List[float]:
        # Embedding simulé (vecteur déterministe)
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = [float(b) / 255.0 for b in hash_bytes[:self._embedding_dimension]]
        
        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)
        
        return embedding
    
    async def health_check(self) -> bool:
        return True
    
    async def list_models(self) -> List[str]:
        return ["mock-model", "mock-embedding-model", "mock-code-model"]