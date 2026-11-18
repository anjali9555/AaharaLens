import pytest
from src.services.nutrition_service import NutritionCalculationService
from src.services.rag_service import rag_service
from src.repositories.database import food_analysis_collection

def test_transparent_health_score_calculation():
    """Verify objective transparent health scoring on nutrient metrics per 100g."""
    per_100_healthy = {
        "calories": 120.0,
        "protein": 14.0,
        "fat": 2.0,
        "saturated_fat": 0.5,
        "carbs": 12.0,
        "fiber": 6.5,
        "sugar": 1.0,
        "sodium_mg": 120.0
    }
    score, details = NutritionCalculationService.compute_transparent_health_score(per_100_healthy)
    assert 1 <= score <= 10
    assert score >= 7
    assert isinstance(details, dict)

    per_100_unhealthy = {
        "calories": 480.0,
        "protein": 1.0,
        "fat": 24.0,
        "saturated_fat": 12.0,
        "carbs": 65.0,
        "fiber": 0.5,
        "sugar": 35.0,
        "sodium_mg": 950.0
    }
    score_unhealthy, _ = NutritionCalculationService.compute_transparent_health_score(per_100_unhealthy)
    assert 1 <= score_unhealthy <= 10
    assert score_unhealthy < score

def test_food_nutrition_per_100g_and_micros():
    """Verify nutrition calculation and scaled serving weights."""
    res = NutritionCalculationService.calculate_food_nutrition("roti", "2 rotis")
    assert res is not None
    assert res.serving_weight_g > 0
    assert res.calories > 0
    assert res.protein > 0
    assert res.carbohydrates > 0

def test_rag_query_caching_and_fallbacks():
    """Verify RAG retrieval and indexing."""
    count = rag_service.rebuild_index()
    assert count > 0

    chunks = rag_service.retrieve_relevant_chunks("protein and muscle recovery", top_k=2)
    assert isinstance(chunks, list)
    assert len(chunks) <= 2
    for c in chunks:
        assert "text" in c
        assert "source" in c

def test_food_analysis_history_lifecycle():
    """Verify saving and retrieving food analysis history."""
    test_record = {
        "user_id": "test_user_analysis_123",
        "food_item": "Dal Tadka",
        "calories": 180.0,
        "protein": 9.5
    }
    inserted = food_analysis_collection.insert_one(test_record)
    assert inserted is not None

    found = food_analysis_collection.find_one({"user_id": "test_user_analysis_123"})
    assert found is not None
    assert found["food_item"] == "Dal Tadka"

    food_analysis_collection.delete_one({"user_id": "test_user_analysis_123"})
