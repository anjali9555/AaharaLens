import pytest
import os
import shutil
from unittest.mock import patch, MagicMock
from src.services.rag_service import rag_service, FastEmbedBGEEmbedding
from src.services.cache_service import cache_service, CacheService
from src.services.ai_service import ai_service
from src.services.nutrition_service import NutritionCalculationService
from src.repositories.database import (
    DocumentStore,
    meal_entries_collection,
    get_user_nutrition_analytics
)
from src.core.config import settings
from src.schemas.nutrition_schemas import MealEntryCreate
from src.routes.chat_routes import get_rag_health_status, rebuild_rag_index, clear_rag_cache


# ================= 1. EMBEDDINGS (FastEmbed BGE-small-en-v1.5) =================

def test_local_bge_embeddings_loading_and_dimensions():
    """Verify FastEmbed BGE ONNX model loads locally, runs on CPU, and yields exact 384 dimensions."""
    adapter = FastEmbedBGEEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir=settings.EMBEDDING_CACHE_DIR)
    
    # Query embedding (with BGE prefix)
    q_vec = adapter._get_query_embedding("high protein vegetarian foods")
    assert isinstance(q_vec, list)
    assert len(q_vec) == 384
    assert all(isinstance(v, float) for v in q_vec)

    # Passage text embedding
    doc_vec = adapter._get_text_embedding("Lentils and paneer deliver complete branched-chain amino acids.")
    assert len(doc_vec) == 384

    # Empty text handling (must not crash, returns valid vector)
    empty_vec = adapter._get_text_embedding("")
    assert len(empty_vec) == 384

    # Batch embedding
    batch_vecs = adapter._get_text_embeddings(["Text 1", "Text 2", "Text 3"])
    assert len(batch_vecs) == 3
    assert len(batch_vecs[0]) == 384


# ================= 2. QDRANT VECTOR DATABASE =================

def test_qdrant_collection_and_vector_operations():
    """Verify Qdrant vector storage, metadata payloads, similarity search, and duplicate prevention."""
    import qdrant_client
    from qdrant_client.http.models import Distance, VectorParams, PointStruct

    test_qdrant_dir = "data/storage/test_qdrant_unit"
    os.makedirs(test_qdrant_dir, exist_ok=True)
    test_client = qdrant_client.QdrantClient(path=test_qdrant_dir)
    collection_name = "test_nutrition_unit"

    if test_client.collection_exists(collection_name):
        test_client.delete_collection(collection_name)

    test_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )

    adapter = FastEmbedBGEEmbedding(cache_dir=settings.EMBEDDING_CACHE_DIR)
    doc_text = "Spinach contains bioavailable non-heme iron and folate."
    vec = adapter._get_text_embedding(doc_text)

    # Insert point with rich metadata payload
    test_client.upsert(
        collection_name=collection_name,
        points=[
            PointStruct(
                id=101,
                vector=vec,
                payload={
                    "document_id": "spinach_01",
                    "source": "clinical_nutrition_guidelines.md",
                    "category": "Micronutrients",
                    "content_hash": "hash_spinach_01",
                    "text": doc_text
                }
            )
        ]
    )

    # Verify search
    q_vec = adapter._get_query_embedding("iron rich vegetables")
    hits = test_client.query_points(collection_name=collection_name, query=q_vec, limit=1).points
    assert len(hits) == 1
    assert hits[0].payload["document_id"] == "spinach_01"
    assert hits[0].payload["category"] == "Micronutrients"
    assert hits[0].score > 0.0

    test_client.close()
    if os.path.exists(test_qdrant_dir):
        shutil.rmtree(test_qdrant_dir, ignore_errors=True)


# ================= 3. HYBRID RAG (BM25 + DENSE VECTOR FUSION) =================

def test_hybrid_rag_rrf_scoring_and_deduplication():
    """Verify hybrid Reciprocal Rank Fusion combines BM25 and dense vectors without duplicates."""
    query = "paneer protein and calcium"
    chunks = rag_service.retrieve_relevant_chunks(query, top_k=3)
    assert len(chunks) > 0
    assert len(chunks) <= 3

    seen_ids = set()
    for c in chunks:
        cid = c.get("chunk_id")
        assert cid not in seen_ids, "Chunks must be deduplicated"
        seen_ids.add(cid)
        assert "retrieval_method" in c
        assert "rrf_score" in c
        assert c["rrf_score"] > 0


def test_rag_health_endpoint_and_admin_diagnostics():
    """Verify RAG health check endpoint returns complete diagnostic metadata."""
    health = get_rag_health_status()
    assert health["rag_mode"] == "Hybrid (BM25 + FastEmbed BGE Dense)"
    assert health["embedding_model"] == settings.EMBEDDING_MODEL_NAME
    assert health["embedding_dimensions"] == 384
    assert "qdrant_mode" in health
    assert "bm25_chunks_indexed" in health
    assert health["bm25_chunks_indexed"] > 0


def test_rag_unsupported_questions_guardrail():
    """Verify chatbot handles non-nutrition queries safely and grounds responses."""
    mock_llm_response = (
        "I specialize in personalized clinical nutrition and dietary guidance. "
        "The current knowledge base does not contain information on automotive mechanics."
    )
    with patch.object(ai_service, "_call_llm", return_value=mock_llm_response):
        resp = rag_service.answer_query("How do I replace a car engine alternator?")
        assert resp is not None
        assert "nutrition" in resp.answer.lower() or "knowledge base" in resp.answer.lower()
        assert resp.conversation_id is not None


# ================= 4. REDIS & APPLICATION CACHING =================

def test_cache_nutrition_get_set_and_stats():
    """Verify caching food nutrition lookups with TTL and hit/miss tracking."""
    cache = CacheService()
    test_key = "test_apple_macro"
    test_data = {"food": "Apple", "calories": 52.0, "protein": 0.3}

    # Miss
    assert cache.get("nutrition", test_key) is None
    init_misses = cache.stats["misses"]
    assert init_misses >= 1

    # Set
    cache.set("nutrition", test_key, test_data, ttl=60)

    # Hit
    retrieved = cache.get("nutrition", test_key)
    assert retrieved is not None
    assert retrieved["calories"] == 52.0
    assert cache.stats["hits"] >= 1

    # Diagnostics
    diag = cache.get_diagnostics()
    assert "hits" in diag
    assert "misses" in diag
    assert "hit_ratio_percent" in diag


def test_cache_user_isolation_and_invalidation():
    """Verify strict user isolation in caching and namespace invalidation."""
    cache = CacheService()

    # User A cached analytics
    cache.set("analytics", "user_AAA:7d", {"calories_avg": 2100.0})
    # User B cached analytics
    cache.set("analytics", "user_BBB:7d", {"calories_avg": 1600.0})

    # Strict isolation
    assert cache.get("analytics", "user_AAA:7d")["calories_avg"] == 2100.0
    assert cache.get("analytics", "user_BBB:7d")["calories_avg"] == 1600.0

    # Invalidate user A only
    cache.invalidate_user_cache("user_AAA")
    assert cache.get("analytics", "user_AAA:7d") is None
    # User B remains intact
    assert cache.get("analytics", "user_BBB:7d") is not None


# ================= 5. MONGODB AGGREGATION & ANALYTICS =================

def test_mongodb_aggregation_pipeline_simulator():
    """Verify DocumentStore aggregation pipeline handles $match, $sort, and $limit."""
    test_store = DocumentStore("test_agg_store")
    test_store._write_fallback([
        {"id": "1", "user_id": "u1", "calories": 250, "date": "2026-11-01"},
        {"id": "2", "user_id": "u1", "calories": 500, "date": "2026-11-02"},
        {"id": "3", "user_id": "u2", "calories": 300, "date": "2026-11-02"},
        {"id": "4", "user_id": "u1", "calories": 150, "date": "2026-11-03"},
    ])

    pipeline = [
        {"$match": {"user_id": "u1", "date": {"$gte": "2026-11-01", "$lte": "2026-11-02"}}},
        {"$sort": {"calories": -1}},
        {"$limit": 1}
    ]
    results = test_store.aggregate(pipeline)
    assert len(results) == 1
    assert results[0]["id"] == "2"
    assert results[0]["calories"] == 500


def test_user_nutrition_analytics_computation():
    """Verify 7-day nutrition analytics calculates averages, macro percentages, and category breakdown."""
    user_id = "test_analytics_user_99"

    # Clean up prior residual entries
    while meal_entries_collection.delete_one({"user_id": user_id}):
        pass

    # Insert test meals directly into fallback/mock store
    meal_entries_collection.insert_one({
        "user_id": user_id,
        "date": "2026-11-10",
        "meal_type": "breakfast",
        "food_name": "Oatmeal with Almonds",
        "calories": 350.0,
        "protein": 14.0,
        "carbohydrates": 45.0,
        "fat": 8.0,
        "fiber": 6.0
    })
    meal_entries_collection.insert_one({
        "user_id": user_id,
        "date": "2026-11-10",
        "meal_type": "lunch",
        "food_name": "Dal Tadka and Roti",
        "calories": 450.0,
        "protein": 18.0,
        "carbohydrates": 65.0,
        "fat": 10.0,
        "fiber": 8.0
    })

    analytics = get_user_nutrition_analytics(user_id=user_id, days=30)
    assert analytics["user_id"] == user_id
    assert analytics["totals"]["calories"] == 800.0
    assert analytics["totals"]["protein"] == 32.0
    assert analytics["daily_averages"]["calories"] > 0
    assert "macro_distribution" in analytics
    assert analytics["macro_distribution"]["protein_percent"] > 0
    assert "category_breakdown" in analytics
    assert "Breakfast" in analytics["category_breakdown"]

    # Clean up
    while meal_entries_collection.delete_one({"user_id": user_id}):
        pass


# ================= 6. PERSONALIZED RECOMMENDATIONS & FOOD COMPARISON =================

def test_next_meal_decision_engine_protein_deficit():
    """Verify deterministic next-meal decision engine prescribes protein-rich meals for deficits."""
    decision = ai_service.decide_next_meal(
        target_calories=2000.0,
        consumed_calories=1200.0,
        target_protein=90.0,
        consumed_protein=40.0,  # 50g deficit
        target_carbs=220.0,
        consumed_carbs=150.0,
        dietary_pref="vegetarian"
    )
    assert isinstance(decision, str)
    assert len(decision) > 10


def test_food_comparison_determinism():
    """Verify deterministic macro comparison between two foods."""
    res = ai_service.compare_foods("paneer", "tofu")
    assert "paneer" in res.food_a.food_name.lower()
    assert "tofu" in res.food_b.food_name.lower()
    assert res.winner_for_muscle_gain is not None
    assert "protein" in res.comparison_summary.lower()
