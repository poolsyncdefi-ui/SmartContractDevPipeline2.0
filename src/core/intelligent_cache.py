# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Intelligent Cache
# ==============================================================================
# Fichier: src/core/intelligent_cache.py
# Description: Cache avec stratégies d'invalidation intelligentes,
#              métriques d'utilisation et support des TTL adaptatifs.
#              Optimise les temps de cycle du pipeline en réduisant
#              les appels redondants coûteux.
# ==============================================================================

from typing import Dict, Any, Optional, List, Callable, Union, Tuple, TypeVar, Generic
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import asyncio
import uuid
from enum import Enum
from dataclasses import dataclass, field
import statistics
from collections import defaultdict

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ==============================================================================
# ÉNUMÉRATIONS
# ==============================================================================

class CacheStrategy(str, Enum):
    """
    Stratégies de mise en cache.
    """
    TTL = "ttl"                      # Durée de vie fixe
    LRU = "lru"                      # Least Recently Used
    LFU = "lfu"                      # Least Frequently Used
    ADAPTIVE = "adaptive"            # TTL adaptatif basé sur l'utilisation
    SLIDING = "sliding"              # TTL glissant (renouvelé à chaque accès)


class CacheEvent(str, Enum):
    """
    Événements du cache.
    """
    HIT = "hit"
    MISS = "miss"
    EXPIRED = "expired"
    EVICTED = "evicted"
    SET = "set"
    CLEARED = "cleared"
    UPDATED = "updated"
    ADAPTIVE_TTL_CHANGED = "adaptive_ttl_changed"


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class CacheEntry(Generic[T]):
    """
    Entrée de cache avec métadonnées.
    """
    key: str
    value: T
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_access: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 300
    access_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    size_bytes: int = 0
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """
        Vérifie si l'entrée est expirée.
        
        Returns:
            bool: True si expirée
        """
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return elapsed >= self.ttl_seconds
    
    def is_sliding_expired(self) -> bool:
        """
        Vérifie si l'entrée est expirée en mode TTL glissant.
        
        Returns:
            bool: True si expirée
        """
        elapsed = (datetime.now(timezone.utc) - self.last_access).total_seconds()
        return elapsed >= self.ttl_seconds
    
    def touch(self) -> None:
        """Met à jour la date de dernier accès."""
        self.last_access = datetime.now(timezone.utc)
        self.access_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'entrée en dictionnaire."""
        return {
            "key": self.key,
            "created_at": self.created_at.isoformat(),
            "last_access": self.last_access.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "access_count": self.access_count,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "size_bytes": self.size_bytes,
            "tags": self.tags,
            "metadata": self.metadata,
            "expired": self.is_expired(),
        }


@dataclass
class CacheMetrics:
    """
    Métriques du cache.
    """
    total_entries: int = 0
    total_hits: int = 0
    total_misses: int = 0
    total_evictions: int = 0
    total_expirations: int = 0
    hit_rate: float = 0.0
    miss_rate: float = 0.0
    average_ttl: float = 0.0
    average_access_count: float = 0.0
    memory_usage_bytes: int = 0
    by_tag: Dict[str, int] = field(default_factory=dict)
    by_strategy: Dict[str, int] = field(default_factory=dict)
    access_history: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "total_entries": self.total_entries,
            "total_hits": self.total_hits,
            "total_misses": self.total_misses,
            "total_evictions": self.total_evictions,
            "total_expirations": self.total_expirations,
            "hit_rate": self.hit_rate,
            "miss_rate": self.miss_rate,
            "average_ttl": self.average_ttl,
            "average_access_count": self.average_access_count,
            "memory_usage_bytes": self.memory_usage_bytes,
            "by_tag": self.by_tag,
            "by_strategy": self.by_strategy,
        }


# ==============================================================================
# INTELLIGENT CACHE
# ==============================================================================

class IntelligentCache(Generic[T]):
    """
    Cache intelligent avec stratégies d'invalidation avancées.
    
    Features:
    - Stratégies multiples (TTL, LRU, LFU, ADAPTIVE, SLIDING)
    - Métriques détaillées d'utilisation
    - TTL adaptatif basé sur les patterns d'accès
    - Support des tags pour l'invalidation par catégorie
    - Gestion de la mémoire avec éviction automatique
    - Cache distribué avec support des callbacks
    """
    
    def __init__(
        self,
        default_ttl: int = 300,
        max_entries: int = 1000,
        max_memory_bytes: int = 100 * 1024 * 1024,  # 100 MB
        strategy: CacheStrategy = CacheStrategy.TTL,
        enable_metrics: bool = True,
        listeners: Optional[List[Callable[[CacheEvent, Dict], None]]] = None,
        eviction_check_interval: int = 60,
    ):
        """
        Initialise le cache intelligent.
        
        Args:
            default_ttl: TTL par défaut en secondes
            max_entries: Nombre maximum d'entrées
            max_memory_bytes: Mémoire maximale en octets
            strategy: Stratégie de cache
            enable_metrics: Activer les métriques
            listeners: Listeners d'événements
            eviction_check_interval: Intervalle de vérification de l'éviction
        """
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self.max_memory_bytes = max_memory_bytes
        self.strategy = strategy
        self.enable_metrics = enable_metrics
        self.listeners = listeners or []
        self.eviction_check_interval = eviction_check_interval
        
        self._cache: Dict[str, CacheEntry[T]] = {}
        self._tag_index: Dict[str, List[str]] = defaultdict(list)
        self._metrics = CacheMetrics()
        self._lru_list: List[str] = []
        self._access_frequency: Dict[str, int] = defaultdict(int)
        
        # Verrou
        self._lock = asyncio.Lock()
        
        # ID unique
        self._cache_id = str(uuid.uuid4())[:8]
        
        # Tâche de maintenance
        self._maintenance_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info(f"IntelligentCache initialized: {self._cache_id} (strategy={strategy.value})")
    
    # ==========================================================================
    # OPÉRATIONS PRINCIPALES
    # ==========================================================================
    
    async def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """
        Récupère une valeur du cache.
        
        Args:
            key: Clé de l'entrée
            default: Valeur par défaut si non trouvée
            
        Returns:
            Optional[T]: Valeur ou None
        """
        async with self._lock:
            if key not in self._cache:
                self._update_metrics(key, is_hit=False)
                await self._emit_event(CacheEvent.MISS, {"key": key})
                return default
            
            entry = self._cache[key]
            
            # Vérifier l'expiration selon la stratégie
            if self.strategy == CacheStrategy.SLIDING:
                if entry.is_sliding_expired():
                    await self._remove_entry(key, reason="sliding_expired")
                    self._update_metrics(key, is_hit=False)
                    await self._emit_event(CacheEvent.EXPIRED, {"key": key})
                    return default
            else:
                if entry.is_expired():
                    await self._remove_entry(key, reason="ttl_expired")
                    self._update_metrics(key, is_hit=False)
                    await self._emit_event(CacheEvent.EXPIRED, {"key": key})
                    return default
            
            # Mettre à jour le dernier accès
            entry.touch()
            self._update_lru(key)
            self._update_frequency(key)
            
            self._update_metrics(key, is_hit=True)
            await self._emit_event(CacheEvent.HIT, {"key": key, "access_count": entry.access_count})
            
            return entry.value
    
    async def set(
        self,
        key: str,
        value: T,
        ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Définit une valeur dans le cache.
        
        Args:
            key: Clé de l'entrée
            value: Valeur à stocker
            ttl: TTL personnalisé en secondes
            tags: Tags pour l'indexation
            metadata: Métadonnées supplémentaires
        """
        async with self._lock:
            # Vérifier les limites
            await self._ensure_capacity()
            
            # Créer l'entrée
            entry = CacheEntry(
                key=key,
                value=value,
                ttl_seconds=ttl or self.default_ttl,
                tags=tags or [],
                metadata=metadata or {},
                size_bytes=self._calculate_size(value)
            )
            
            # Ajouter au cache
            old_entry = self._cache.get(key)
            self._cache[key] = entry
            
            # Mettre à jour l'index des tags
            for tag in entry.tags:
                self._tag_index[tag].append(key)
            
            # Mettre à jour les listes LRU/LFU
            self._update_lru(key)
            self._update_frequency(key)
            
            # Mettre à jour les métriques
            self._metrics.total_entries = len(self._cache)
            self._metrics.memory_usage_bytes += entry.size_bytes
            if old_entry:
                self._metrics.memory_usage_bytes -= old_entry.size_bytes
            
            await self._emit_event(CacheEvent.SET, {
                "key": key,
                "ttl": entry.ttl_seconds,
                "tags": entry.tags,
                "size_bytes": entry.size_bytes
            })
    
    async def delete(self, key: str) -> bool:
        """
        Supprime une entrée du cache.
        
        Args:
            key: Clé de l'entrée
            
        Returns:
            bool: True si supprimée
        """
        async with self._lock:
            if key not in self._cache:
                return False
            
            entry = self._cache[key]
            await self._remove_entry(key, reason="manual_delete")
            return True
    
    async def clear(self) -> None:
        """Vide le cache."""
        async with self._lock:
            self._cache.clear()
            self._tag_index.clear()
            self._lru_list.clear()
            self._access_frequency.clear()
            self._metrics.total_entries = 0
            self._metrics.memory_usage_bytes = 0
            
            await self._emit_event(CacheEvent.CLEARED, {"entries_cleared": len(self._cache)})
            logger.info(f"Cache {self._cache_id} cleared")
    
    # ==========================================================================
    # OPÉRATIONS AVANCÉES
    # ==========================================================================
    
    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
        ttl: Optional[int] = None,
        tags: Optional[List[str]] = None
    ) -> T:
        """
        Récupère la valeur du cache ou la génère si absente.
        
        Args:
            key: Clé de l'entrée
            factory: Fonction asynchrone pour générer la valeur
            ttl: TTL personnalisé
            tags: Tags pour l'indexation
            
        Returns:
            T: Valeur (du cache ou générée)
        """
        cached = await self.get(key)
        if cached is not None:
            return cached
        
        value = await factory()
        await self.set(key, value, ttl=ttl, tags=tags)
        return value
    
    async def get_by_tag(self, tag: str) -> List[Tuple[str, T]]:
        """
        Récupère toutes les entrées associées à un tag.
        
        Args:
            tag: Tag à rechercher
            
        Returns:
            List[Tuple[str, T]]: Liste des (clé, valeur)
        """
        async with self._lock:
            keys = self._tag_index.get(tag, [])
            results = []
            
            for key in keys:
                if key in self._cache:
                    entry = self._cache[key]
                    # Vérifier l'expiration selon la stratégie
                    if self.strategy == CacheStrategy.SLIDING:
                        if entry.is_sliding_expired():
                            await self._remove_entry(key, reason="sliding_expired")
                            continue
                    else:
                        if entry.is_expired():
                            await self._remove_entry(key, reason="ttl_expired")
                            continue
                    
                    results.append((key, entry.value))
            
            return results
    
    async def invalidate_by_tag(self, tag: str) -> int:
        """
        Invalide toutes les entrées associées à un tag.
        
        Args:
            tag: Tag à invalider
            
        Returns:
            int: Nombre d'entrées invalidées
        """
        async with self._lock:
            keys = self._tag_index.get(tag, []).copy()
            count = 0
            
            for key in keys:
                if key in self._cache:
                    await self._remove_entry(key, reason="tag_invalidation")
                    count += 1
            
            if count > 0:
                await self._emit_event(CacheEvent.EVICTED, {
                    "tag": tag,
                    "count": count,
                    "reason": "tag_invalidation"
                })
            
            return count
    
    async def get_ttl(self, key: str) -> Optional[int]:
        """
        Récupère le TTL restant d'une entrée.
        
        Args:
            key: Clé de l'entrée
            
        Returns:
            Optional[int]: TTL restant en secondes ou None
        """
        async with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            elapsed = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
            remaining = max(0, entry.ttl_seconds - elapsed)
            return int(remaining)
    
    async def update_ttl(self, key: str, new_ttl: int) -> bool:
        """
        Met à jour le TTL d'une entrée.
        
        Args:
            key: Clé de l'entrée
            new_ttl: Nouveau TTL en secondes
            
        Returns:
            bool: True si mis à jour
        """
        async with self._lock:
            if key not in self._cache:
                return False
            
            entry = self._cache[key]
            old_ttl = entry.ttl_seconds
            entry.ttl_seconds = new_ttl
            entry.created_at = datetime.now(timezone.utc)  # Réinitialiser le timer
            
            await self._emit_event(CacheEvent.UPDATED, {
                "key": key,
                "old_ttl": old_ttl,
                "new_ttl": new_ttl
            })
            
            return True
    
    # ==========================================================================
    # MÉTHODES PRIVÉES
    # ==========================================================================
    
    async def _remove_entry(self, key: str, reason: str = "manual") -> None:
        """
        Supprime une entrée du cache (interne, sans verrou).
        
        Args:
            key: Clé de l'entrée
            reason: Raison de la suppression
        """
        if key not in self._cache:
            return
        
        entry = self._cache[key]
        
        # Supprimer des index de tags
        for tag in entry.tags:
            if tag in self._tag_index:
                self._tag_index[tag] = [k for k in self._tag_index[tag] if k != key]
                if not self._tag_index[tag]:
                    del self._tag_index[tag]
        
        # Supprimer de la liste LRU
        if key in self._lru_list:
            self._lru_list.remove(key)
        
        # Supprimer de la fréquence
        if key in self._access_frequency:
            del self._access_frequency[key]
        
        # Mettre à jour les métriques
        self._metrics.total_entries = len(self._cache) - 1
        self._metrics.memory_usage_bytes -= entry.size_bytes
        
        # Supprimer du cache
        del self._cache[key]
        
        await self._emit_event(CacheEvent.EVICTED, {
            "key": key,
            "reason": reason,
            "ttl_seconds": entry.ttl_seconds,
            "access_count": entry.access_count
        })
    
    async def _ensure_capacity(self) -> None:
        """Assure que le cache n'atteint pas ses limites."""
        # Vérifier le nombre d'entrées
        while len(self._cache) >= self.max_entries:
            await self._evict_one()
        
        # Vérifier la mémoire
        while self._metrics.memory_usage_bytes > self.max_memory_bytes:
            await self._evict_one()
    
    async def _evict_one(self) -> None:
        """Évite une entrée selon la stratégie."""
        if not self._cache:
            return
        
        evict_key = None
        
        if self.strategy == CacheStrategy.LRU:
            # Éviter la moins récemment utilisée
            if self._lru_list:
                evict_key = self._lru_list[-1]  # Dernier = moins récent
        
        elif self.strategy == CacheStrategy.LFU:
            # Éviter la moins fréquemment utilisée
            if self._access_frequency:
                evict_key = min(self._access_frequency.items(), key=lambda x: x[1])[0]
        
        elif self.strategy in [CacheStrategy.TTL, CacheStrategy.ADAPTIVE, CacheStrategy.SLIDING]:
            # Éviter celle avec le TTL le plus court ou la plus ancienne
            if self._cache:
                entries = list(self._cache.items())
                entries.sort(key=lambda x: (
                    x[1].created_at if self.strategy == CacheStrategy.TTL else
                    x[1].last_access
                ))
                evict_key = entries[0][0]
        
        if evict_key and evict_key in self._cache:
            await self._remove_entry(evict_key, reason=f"eviction_{self.strategy.value}")
    
    def _update_lru(self, key: str) -> None:
        """Met à jour la liste LRU."""
        if key in self._lru_list:
            self._lru_list.remove(key)
        self._lru_list.insert(0, key)
    
    def _update_frequency(self, key: str) -> None:
        """Met à jour la fréquence d'accès."""
        self._access_frequency[key] += 1
    
    def _update_metrics(self, key: str, is_hit: bool) -> None:
        """
        Met à jour les métriques.
        
        Args:
            key: Clé de l'entrée
            is_hit: True si c'est un hit
        """
        if not self.enable_metrics:
            return
        
        if is_hit:
            self._metrics.total_hits += 1
            if key in self._cache:
                self._cache[key].hit_count += 1
        else:
            self._metrics.total_misses += 1
            if key in self._cache:
                self._cache[key].miss_count += 1
        
        total = self._metrics.total_hits + self._metrics.total_misses
        self._metrics.hit_rate = self._metrics.total_hits / total if total > 0 else 0
        self._metrics.miss_rate = self._metrics.total_misses / total if total > 0 else 0
        
        # Mise à jour des moyennes
        if self._cache:
            self._metrics.average_access_count = sum(e.access_count for e in self._cache.values()) / len(self._cache)
            self._metrics.average_ttl = sum(e.ttl_seconds for e in self._cache.values()) / len(self._cache)
    
    def _calculate_size(self, value: Any) -> int:
        """
        Calcule la taille approximative d'une valeur en octets.
        
        Args:
            value: Valeur à mesurer
            
        Returns:
            int: Taille en octets
        """
        try:
            if isinstance(value, (str, bytes)):
                return len(value)
            elif isinstance(value, (int, float, bool)):
                return 8
            elif isinstance(value, (list, tuple)):
                return sum(self._calculate_size(v) for v in value)
            elif isinstance(value, dict):
                return sum(self._calculate_size(k) + self._calculate_size(v) for k, v in value.items())
            elif isinstance(value, (dict, list, tuple)):
                return len(json.dumps(value, default=str))
            else:
                return 64  # Valeur par défaut
        except Exception:
            return 64
    
    # ==========================================================================
    # MÉTRIQUES ET STATISTIQUES
    # ==========================================================================
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Retourne les métriques du cache.
        
        Returns:
            Dict[str, Any]: Métriques
        """
        return {
            "cache_id": self._cache_id,
            "strategy": self.strategy.value,
            "default_ttl": self.default_ttl,
            "max_entries": self.max_entries,
            "max_memory_bytes": self.max_memory_bytes,
            "total_entries": len(self._cache),
            "memory_usage_bytes": self._metrics.memory_usage_bytes,
            "hit_rate": self._metrics.hit_rate,
            "miss_rate": self._metrics.miss_rate,
            "total_hits": self._metrics.total_hits,
            "total_misses": self._metrics.total_misses,
            "total_evictions": self._metrics.total_evictions,
            "total_expirations": self._metrics.total_expirations,
            "average_ttl": self._metrics.average_ttl,
            "average_access_count": self._metrics.average_access_count,
            "by_tag": dict(self._metrics.by_tag),
            "by_strategy": dict(self._metrics.by_strategy),
            "access_frequency": dict(self._access_frequency),
            "lru_count": len(self._lru_list),
        }
    
    def get_hit_rate(self) -> float:
        """
        Retourne le taux de succès du cache.
        
        Returns:
            float: Taux de succès (0-1)
        """
        total = self._metrics.total_hits + self._metrics.total_misses
        return self._metrics.total_hits / total if total > 0 else 0
    
    def get_miss_rate(self) -> float:
        """
        Retourne le taux d'échec du cache.
        
        Returns:
            float: Taux d'échec (0-1)
        """
        total = self._metrics.total_hits + self._metrics.total_misses
        return self._metrics.total_misses / total if total > 0 else 0
    
    # ==========================================================================
    # ÉVÉNEMENTS
    # ==========================================================================
    
    def add_listener(self, listener: Callable[[CacheEvent, Dict], None]) -> None:
        """
        Ajoute un listener d'événements.
        
        Args:
            listener: Fonction de callback
        """
        self.listeners.append(listener)
    
    def remove_listener(self, listener: Callable[[CacheEvent, Dict], None]) -> None:
        """
        Supprime un listener d'événements.
        
        Args:
            listener: Fonction de callback
        """
        if listener in self.listeners:
            self.listeners.remove(listener)
    
    async def _emit_event(self, event_type: CacheEvent, data: Dict[str, Any]) -> None:
        """
        Émet un événement à tous les listeners.
        
        Args:
            event_type: Type d'événement
            data: Données de l'événement
        """
        for listener in self.listeners:
            try:
                listener(event_type, data)
            except Exception as e:
                logger.error(f"Listener error: {e}")
    
    # ==========================================================================
    # MAINTENANCE
    # ==========================================================================
    
    async def start(self) -> None:
        """Démarre la tâche de maintenance."""
        if self._running:
            return
        
        self._running = True
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        logger.info(f"Cache {self._cache_id} maintenance started")
    
    async def stop(self) -> None:
        """Arrête la tâche de maintenance."""
        self._running = False
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            self._maintenance_task = None
        logger.info(f"Cache {self._cache_id} maintenance stopped")
    
    async def _maintenance_loop(self) -> None:
        """Boucle de maintenance du cache."""
        while self._running:
            try:
                await asyncio.sleep(self.eviction_check_interval)
                
                async with self._lock:
                    # Nettoyer les entrées expirées
                    expired_keys = []
                    for key, entry in self._cache.items():
                        is_expired = entry.is_sliding_expired() if self.strategy == CacheStrategy.SLIDING else entry.is_expired()
                        if is_expired:
                            expired_keys.append(key)
                    
                    for key in expired_keys:
                        await self._remove_entry(key, reason="maintenance_expired")
                        self._metrics.total_expirations += 1
                    
                    if expired_keys:
                        await self._emit_event(CacheEvent.EXPIRED, {
                            "count": len(expired_keys),
                            "keys": expired_keys
                        })
                
                # TTL adaptatif (si activé)
                if self.strategy == CacheStrategy.ADAPTIVE:
                    await self._adjust_adaptive_ttl()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Maintenance error: {e}")
    
    async def _adjust_adaptive_ttl(self) -> None:
        """
        Ajuste les TTL de manière adaptative basée sur l'utilisation.
        """
        if len(self._cache) < 2:
            return
        
        # Calculer la moyenne d'accès
        total_access = sum(e.access_count for e in self._cache.values())
        avg_access = total_access / len(self._cache) if self._cache else 0
        
        for key, entry in list(self._cache.items()):
            # Si l'entrée est très utilisée, augmenter son TTL
            if entry.access_count > avg_access * 2:
                new_ttl = min(entry.ttl_seconds * 1.5, 3600)  # Max 1 heure
                if new_ttl > entry.ttl_seconds:
                    old_ttl = entry.ttl_seconds
                    entry.ttl_seconds = int(new_ttl)
                    await self._emit_event(CacheEvent.ADAPTIVE_TTL_CHANGED, {
                        "key": key,
                        "old_ttl": old_ttl,
                        "new_ttl": entry.ttl_seconds,
                        "access_count": entry.access_count,
                        "reason": "high_usage"
                    })
            elif entry.access_count < avg_access / 2:
                # Si l'entrée est peu utilisée, réduire son TTL
                new_ttl = max(entry.ttl_seconds * 0.7, 60)  # Min 1 minute
                if new_ttl < entry.ttl_seconds:
                    old_ttl = entry.ttl_seconds
                    entry.ttl_seconds = int(new_ttl)
                    await self._emit_event(CacheEvent.ADAPTIVE_TTL_CHANGED, {
                        "key": key,
                        "old_ttl": old_ttl,
                        "new_ttl": entry.ttl_seconds,
                        "access_count": entry.access_count,
                        "reason": "low_usage"
                    })
    
    # ==========================================================================
    # MÉTHODES DE CONVENANCE
    # ==========================================================================
    
    async def get_str(self, key: str, default: str = "") -> str:
        """Récupère une valeur string du cache."""
        value = await self.get(key)
        return str(value) if value is not None else default
    
    async def get_int(self, key: str, default: int = 0) -> int:
        """Récupère une valeur entière du cache."""
        value = await self.get(key)
        return int(value) if value is not None else default
    
    async def get_bool(self, key: str, default: bool = False) -> bool:
        """Récupère une valeur booléenne du cache."""
        value = await self.get(key)
        return bool(value) if value is not None else default
    
    async def get_list(self, key: str, default: Optional[List] = None) -> List:
        """Récupère une liste du cache."""
        value = await self.get(key)
        return value if value is not None else (default or [])
    
    async def get_dict(self, key: str, default: Optional[Dict] = None) -> Dict:
        """Récupère un dictionnaire du cache."""
        value = await self.get(key)
        return value if value is not None else (default or {})
    
    # ==========================================================================
    # REPRÉSENTATION
    # ==========================================================================
    
    def __repr__(self) -> str:
        return f"<IntelligentCache(id={self._cache_id}, entries={len(self._cache)}, hit_rate={self.get_hit_rate():.2%})>"
    
    def __len__(self) -> int:
        return len(self._cache)


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_cache():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Intelligent Cache")
        print("=" * 60)
        
        # Création du cache
        cache = IntelligentCache[str](
            default_ttl=30,
            max_entries=100,
            strategy=CacheStrategy.TTL,
            enable_metrics=True
        )
        
        print("\n📋 Test de base:")
        await cache.set("test_key", "Hello World", tags=["test", "demo"])
        value = await cache.get("test_key")
        print(f"  Get: {value}")
        
        # Test de la stratégie LRU
        print("\n📋 Test de la stratégie LRU:")
        lru_cache = IntelligentCache[str](
            max_entries=5,
            strategy=CacheStrategy.LRU
        )
        
        for i in range(8):
            await lru_cache.set(f"key_{i}", f"value_{i}")
        
        print(f"  Entrées après 8 insertions (max=5): {len(lru_cache)}")
        print(f"  Clés présentes: {list(lru_cache._cache.keys())}")
        
        # Test du get_or_set
        print("\n📋 Test du get_or_set:")
        async def expensive_factory():
            print("  🔄 Exécution du factory (coûteux)")
            await asyncio.sleep(0.5)
            return "Generated Value"
        
        value1 = await cache.get_or_set("generated_key", expensive_factory)
        print(f"  Premier appel: {value1}")
        
        value2 = await cache.get_or_set("generated_key", expensive_factory)
        print(f"  Deuxième appel (cache): {value2}")
        
        # Test des tags
        print("\n📋 Test des tags:")
        await cache.set("tagged_1", "value_1", tags=["tagA", "common"])
        await cache.set("tagged_2", "value_2", tags=["tagB", "common"])
        await cache.set("tagged_3", "value_3", tags=["tagA"])
        
        tag_a_values = await cache.get_by_tag("tagA")
        print(f"  Tag 'tagA': {[(k, v) for k, v in tag_a_values]}")
        
        common_values = await cache.get_by_tag("common")
        print(f"  Tag 'common': {[(k, v) for k, v in common_values]}")
        
        # Invalidation par tag
        invalidated = await cache.invalidate_by_tag("tagA")
        print(f"  Invalidation de 'tagA': {invalidated} entrées")
        
        # Métriques
        print("\n📋 Métriques:")
        metrics = cache.get_metrics()
        for key, value in metrics.items():
            if key == "access_frequency":
                continue
            print(f"  {key}: {value}")
        
        print(f"\n  Hit rate: {cache.get_hit_rate():.2%}")
        print(f"  Miss rate: {cache.get_miss_rate():.2%}")
        
        print("\n✅ Tests terminés.")
    
    asyncio.run(test_cache())