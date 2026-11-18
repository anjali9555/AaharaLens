import json
import time
import threading
from typing import Any, Optional, Dict
from loguru import logger
from src.core.config import settings

class CacheService:
    """
    Advanced multi-tier application cache with safe Windows-native operation.
    MODE A: Redis distributed primary store when available and healthy.
    MODE B: Thread-safe, monotonic-time in-memory TTL fallback when Redis is unavailable.
    """

    def __init__(self):
        self.enabled = settings.REDIS_CACHE_ENABLED
        self.redis_client = None
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._cleanup_counter = 0
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "invalidations": 0
        }
        self._init_redis()

    def _init_redis(self):
        """Initializes Redis client with fast timeout check and PING verification."""
        if not self.enabled or not settings.REDIS_URL:
            logger.info("Application cache running in memory-only fallback mode.")
            return

        try:
            import redis
            client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0
            )
            client.ping()
            self.redis_client = client
            logger.info("Application caching successfully connected to Redis.")
        except Exception as e:
            logger.warning(f"Redis cache unavailable ({e}). Operating in thread-safe in-memory fallback mode.")
            self.redis_client = None

    def is_redis_healthy(self) -> bool:
        """Returns True if Redis is actively responding to ping."""
        if not self.redis_client:
            return False
        try:
            return bool(self.redis_client.ping())
        except Exception:
            return False

    def _cleanup_expired(self, force: bool = False):
        """Safely cleans up expired in-memory entries to prevent memory accumulation."""
        now = time.monotonic()
        with self._lock:
            self._cleanup_counter += 1
            if not force and self._cleanup_counter % 50 != 0:
                return
            expired_keys = [k for k, v in self._memory_cache.items() if v.get("expires_at", 0) <= now]
            for k in expired_keys:
                self._memory_cache.pop(k, None)

    def _format_key(self, namespace: str, key: str) -> str:
        """Formats namespaced cache key (e.g. 'aaharalens:nutrition:apple:100g')."""
        clean_key = str(key).strip().lower().replace(" ", "_")
        return f"aaharalens:{namespace}:{clean_key}"

    def get(self, namespace: str, key: str) -> Optional[Any]:
        """Retrieves cached JSON item from Redis or thread-safe in-memory fallback."""
        if not self.enabled:
            return None

        full_key = self._format_key(namespace, key)

        # 1. Try Redis primary cache
        if self.redis_client:
            try:
                val = self.redis_client.get(full_key)
                if val is not None:
                    with self._lock:
                        self.stats["hits"] += 1
                    return json.loads(val)
                with self._lock:
                    self.stats["misses"] += 1
                return None
            except Exception as e:
                logger.debug(f"Redis read error on {full_key}: {e}")

        # 2. In-memory fallback with monotonic clock
        now = time.monotonic()
        with self._lock:
            item = self._memory_cache.get(full_key)
            if item:
                if item["expires_at"] > now:
                    self.stats["hits"] += 1
                    return item["val"]
                else:
                    self._memory_cache.pop(full_key, None)
            self.stats["misses"] += 1

        return None

    def set(self, namespace: str, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Stores item with TTL (in seconds) in Redis or thread-safe in-memory store."""
        if not self.enabled:
            return False

        full_key = self._format_key(namespace, key)
        ttl_val = ttl if ttl is not None else settings.CACHE_TTL_DEFAULT

        # 1. Store in Redis
        if self.redis_client:
            try:
                payload = json.dumps(value)
                self.redis_client.setex(full_key, ttl_val, payload)
                with self._lock:
                    self.stats["sets"] += 1
                return True
            except Exception as e:
                logger.debug(f"Redis set error on {full_key}: {e}")

        # 2. Store in thread-safe memory fallback with monotonic clock
        with self._lock:
            self._cleanup_expired()
            self._memory_cache[full_key] = {
                "val": value,
                "expires_at": time.monotonic() + ttl_val
            }
            self.stats["sets"] += 1
        return True

    def delete(self, namespace: str, key: str) -> bool:
        """Deletes a specific cached key."""
        full_key = self._format_key(namespace, key)
        deleted = False

        if self.redis_client:
            try:
                res = self.redis_client.delete(full_key)
                deleted = bool(res)
            except Exception as e:
                logger.debug(f"Redis delete error on {full_key}: {e}")

        with self._lock:
            if full_key in self._memory_cache:
                self._memory_cache.pop(full_key, None)
                deleted = True

            if deleted:
                self.stats["invalidations"] += 1
        return deleted

    def invalidate_namespace(self, namespace: str) -> int:
        """Invalidates all keys under a specific namespace."""
        count = 0
        pattern = f"aaharalens:{namespace}:*"

        # 1. Invalidate Redis keys
        if self.redis_client:
            try:
                keys = self.redis_client.keys(pattern)
                if keys:
                    count += self.redis_client.delete(*keys)
            except Exception as e:
                logger.debug(f"Redis pattern invalidation error: {e}")

        # 2. Invalidate in-memory keys
        with self._lock:
            mem_keys = [k for k in self._memory_cache if k.startswith(f"aaharalens:{namespace}:")]
            for mk in mem_keys:
                self._memory_cache.pop(mk, None)
                count += 1
            self.stats["invalidations"] += count
        return count

    # Convenience domain helpers
    def get_cached_nutrition(self, food_query: str, portion: Optional[str] = None) -> Optional[Dict[str, Any]]:
        k = f"{food_query}:{portion or 'default'}"
        return self.get("nutrition", k)

    def cache_nutrition(self, food_query: str, portion: Optional[str], data: Dict[str, Any]):
        k = f"{food_query}:{portion or 'default'}"
        self.set("nutrition", k, data, ttl=settings.CACHE_TTL_NUTRITION)

    def get_cached_rag(self, query_key: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        prefix = f"user_{user_id}:" if user_id else "global:"
        return self.get("rag", f"{prefix}{query_key}")

    def cache_rag(self, query_key: str, data: Dict[str, Any], user_id: Optional[str] = None):
        prefix = f"user_{user_id}:" if user_id else "global:"
        self.set("rag", f"{prefix}{query_key}", data, ttl=settings.CACHE_TTL_RAG)

    def invalidate_rag_cache(self) -> int:
        return self.invalidate_namespace("rag")

    def get_cached_analytics(self, user_id: str, window: str = "7d") -> Optional[Dict[str, Any]]:
        return self.get("analytics", f"{user_id}:{window}")

    def cache_analytics(self, user_id: str, window: str, data: Dict[str, Any]):
        self.set("analytics", f"{user_id}:{window}", data, ttl=settings.CACHE_TTL_ANALYTICS)

    def invalidate_user_cache(self, user_id: str) -> int:
        """Invalidates all cached data specific to a user (analytics, user-specific RAG)."""
        count = self.delete("analytics", f"{user_id}:7d")
        count += self.delete("analytics", f"{user_id}:30d")
        return count

    def get_diagnostics(self) -> Dict[str, Any]:
        """Provides cache metrics for administrative diagnostics."""
        with self._lock:
            total_reqs = self.stats["hits"] + self.stats["misses"]
            hit_ratio = round((self.stats["hits"] / total_reqs * 100), 1) if total_reqs > 0 else 0.0
            redis_ok = self.is_redis_healthy()
            return {
                "mode": "redis" if redis_ok else "in_memory_fallback",
                "redis_connected": redis_ok,
                "redis_url_configured": bool(settings.REDIS_URL),
                "fallback_active": not redis_ok,
                "in_memory_items": len(self._memory_cache),
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_ratio_percent": hit_ratio,
                "total_sets": self.stats["sets"],
                "invalidations": self.stats["invalidations"],
                "warning": None if redis_ok else "Process-local in-memory cache active. Multiple workers or instances will not share cache state."
            }

cache_service = CacheService()

