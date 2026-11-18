import os
import shutil
import time
import pytest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock

from src.main import app, health_check
from src.core.config import settings
from src.services.rag_service import HybridRAGService, FastEmbedBGEEmbedding, rag_service
from src.services.cache_service import CacheService
from src.repositories.database import check_database_health


# ================= 1. BGE FASTEMBED REUSE & DIMENSIONS =================

def test_bge_fastembed_singleton_loading_and_dimensions():
    """Verify FastEmbed ONNX model reuses singleton instance across instantiations and produces 384-dim vectors."""
    adapter1 = FastEmbedBGEEmbedding(model_name=settings.EMBEDDING_MODEL_NAME, cache_dir=settings.EMBEDDING_CACHE_DIR)
    adapter2 = FastEmbedBGEEmbedding(model_name=settings.EMBEDDING_MODEL_NAME, cache_dir=settings.EMBEDDING_CACHE_DIR)
    
    # Must reuse the same underlying TextEmbedding instance
    assert adapter1._embed_model is adapter2._embed_model

    # Check query embedding
    vec = adapter1._get_query_embedding("optimal daily protein for muscle recovery")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)


# ================= 2. QDRANT SINGLE-CLIENT LIFECYCLE & LOCK HANDLING =================

def test_qdrant_single_client_lifecycle_and_graceful_shutdown():
    """Verify Qdrant client initializes, answers queries, and releases locks upon close()."""
    import qdrant_client
    
    mem_client = qdrant_client.QdrantClient(location=":memory:")
    service = HybridRAGService(qdrant_client_override=mem_client)
    
    assert service.qdrant_mode == "injected_client"
    assert service.qdrant_client is not None
    
    # Verify collection check
    service.ensure_ready()
    status = service.get_health_status()
    assert status["qdrant_healthy"] is True
    assert status["single_process_owner"] is True
    
    # Close gracefully
    service.close()


def test_qdrant_storage_lock_handling_and_fallback():
    """Verify Qdrant catches process storage lock errors and falls back to in-memory mode safely."""
    import qdrant_client
    
    mock_mem = MagicMock()
    with patch.object(qdrant_client, "QdrantClient") as mock_qc:
        # First call (remote) fails, second call (local persistent) raises lock error, third call falls back to :memory:
        mock_qc.side_effect = [
            Exception("Remote server offline"),
            RuntimeError("Storage folder is already locked by another process: storage.lock"),
            mock_mem
        ]
        
        service = HybridRAGService()
        assert service.qdrant_mode == "in_memory_fallback"
        assert service.qdrant_client is not None


# ================= 3. REDIS CONNECTION FAILURE & MEMORY FALLBACK =================

def test_cache_service_redis_unavailable_fallback():
    """Verify CacheService operates safely in thread-safe in-memory fallback when Redis is absent."""
    with patch("src.core.config.settings.REDIS_URL", "redis://nonexistent-host:9999/0"):
        cache = CacheService()
        assert cache.is_redis_healthy() is False
        assert cache.redis_client is None
        
        diag = cache.get_diagnostics()
        assert diag["mode"] == "in_memory_fallback"
        assert diag["fallback_active"] is True
        assert diag["redis_connected"] is False
        assert "Process-local in-memory cache active" in diag["warning"]


def test_cache_service_thread_safe_monotonic_ttl():
    """Verify in-memory cache handles TTL expiration accurately using monotonic clock and supports concurrency."""
    cache = CacheService()
    # Force in-memory fallback
    cache.redis_client = None

    test_key = "test_monotonic_apple"
    cache.set("nutrition", test_key, {"calories": 52.0}, ttl=1)
    
    # Immediately accessible
    val = cache.get("nutrition", test_key)
    assert val is not None
    assert val["calories"] == 52.0

    # Wait for expiration
    time.sleep(1.1)
    expired_val = cache.get("nutrition", test_key)
    assert expired_val is None

    # Thread safety test with concurrent reads and writes
    errors = []
    def worker(worker_id):
        try:
            for i in range(20):
                k = f"thread_key_{worker_id}_{i}"
                cache.set("thread_test", k, {"val": i}, ttl=5)
                res = cache.get("thread_test", k)
                if res is None or res.get("val") != i:
                    errors.append(f"Mismatch on {k}")
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, w) for w in range(5)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Thread concurrency errors encountered: {errors}"


# ================= 4. FASTAPI LIFESPAN & HEALTH DIAGNOSTICS =================

def test_fastapi_lifespan_and_health_endpoint():
    """Verify FastAPI health_check endpoint exposes full system diagnostics."""
    data = health_check()
    assert data["status"] == "healthy"
    assert data["runtime"] == "Windows-Native"
    assert "database" in data
    assert "vector_db" in data
    assert "rag" in data
    assert "cache" in data
    assert "timestamp" in data


def test_fastapi_lifespan_warmup_and_shutdown():
    """Verify lifespan warmup and graceful shutdown mechanisms."""
    # Ensure warmup verifies Qdrant collection
    rag_service.ensure_ready()
    status = rag_service.get_health_status()
    assert status["qdrant_healthy"] is True

    # Ensure graceful close releases client and allows safe re-initialization
    rag_service.close()
    assert rag_service.qdrant_client is None
    rag_service.ensure_ready()
    assert rag_service.qdrant_client is not None


# ================= 5. MONGODB ATLAS & CREDENTIAL PROTECTION =================

def test_mongodb_atlas_health_diagnostics_privacy():
    """Verify database health status reports connectivity without leaking secrets or credentials."""
    health = check_database_health()
    assert "status" in health
    assert "backend" in health
    assert "database" in health
    assert "connected_to_atlas" in health
    assert "fallback_active" in health
    
    # Must not leak passwords or full URI with credentials
    for v in health.values():
        val_str = str(v)
        assert "mongodb+srv://" not in val_str
        assert "password" not in val_str.lower()


# ================= 6. WINDOWS-NATIVE SCRIPTS VERIFICATION =================

def test_windows_native_startup_scripts_exist():
    """Verify all 4 required PowerShell scripts exist and specify single-worker native startup."""
    scripts = [
        "scripts/start_backend.ps1",
        "scripts/start_frontend.ps1",
        "scripts/check_services.ps1",
        "scripts/stop_application.ps1"
    ]
    for s in scripts:
        assert os.path.exists(s), f"Missing required Windows script: {s}"
        with open(s, "r", encoding="utf-8") as f:
            content = f.read()
            assert len(content) > 100

    # Backend script must enforce single worker and local port 8000
    with open("scripts/start_backend.ps1", "r", encoding="utf-8") as f:
        backend_content = f.read()
        assert "--workers 1" in backend_content
        assert "8000" in backend_content
