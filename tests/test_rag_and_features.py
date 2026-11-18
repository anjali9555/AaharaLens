import pytest
from starlette.requests import Request
from slowapi.errors import RateLimitExceeded
from fastapi import HTTPException

from src.services.rag_service import rag_service
from src.services.nutrition_service import NutritionCalculationService
from src.schemas.nutrition_schemas import ProfileUpdateRequest, FoodSubstitutionRequest, RecipeGeneratorRequest
from src.routes.profile_routes import update_user_profile, get_user_profile
from src.routes.food_routes import suggest_substitution, generate_leftover_recipes
from src.core.limiter import limiter

def test_rag_keyword_retrieval():
    """Verify that BM25-style keyword retrieval matches clinical knowledge base chunks."""
    chunks = rag_service.retrieve_relevant_chunks("beta-glucan cholesterol oats", top_k=3)
    assert len(chunks) > 0
    # At least one chunk should reference oats, fiber, or cholesterol
    matched_texts = " ".join([c["text"].lower() for c in chunks])
    assert "oat" in matched_texts or "fiber" in matched_texts or "cholesterol" in matched_texts

def test_rag_chunk_metadata():
    """Verify all knowledge chunks contain source, title, and token indexing."""
    assert len(rag_service.chunks) > 0
    for chunk in rag_service.chunks:
        assert "chunk_id" in chunk
        assert "source" in chunk
        assert "title" in chunk
        assert "tokens" in chunk
        assert len(chunk["tokens"]) > 0

def test_profile_target_recalculation():
    """Verify updating user profile recalculates Mifflin-St Jeor targets immediately."""
    user = {"id": "test-prof-user-777", "email": "prof@test.com"}
    req = ProfileUpdateRequest(
        age=30,
        gender="female",
        height_cm=165.0,
        weight_kg=60.0,
        activity_level="sedentary",
        fitness_goal="weight_loss",
        dietary_preference="vegetarian",
        allergies=["dairy"]
    )
    res = update_user_profile(req, current_user=user)
    assert res.profile.age == 30
    assert res.profile.gender == "female"
    assert "dairy" in res.profile.allergies
    
    # Check that targets were recalculated
    # For 30yo female, 60kg, 165cm:
    # BMR = (10*60) + (6.25*165) - (5*30) - 161 = 600 + 1031.25 - 150 - 161 = 1320.25
    # Sedentary (1.2) = 1584.3 kcal. Weight loss deficit (~400 kcal) = ~1184.3 kcal
    assert res.targets.bmr == pytest.approx(1320.3, abs=2.0)
    assert res.targets.target_calories < res.targets.tdee

def test_food_substitution_service():
    """Verify healthy food substitution recommendation."""
    res = suggest_substitution(FoodSubstitutionRequest(
        food_name="White Rice",
        goal_or_reason="Lower glycemic index and higher fiber"
    ))
    assert res.original_food.lower() == "white rice"
    assert len(res.substitutions) > 0
    assert res.substitutions[0].substitute_name is not None

def test_recipe_generation():
    """Verify leftover ingredients recipe creation."""
    res = generate_leftover_recipes(RecipeGeneratorRequest(
        ingredients=["Spinach", "Paneer", "Tomatoes"],
        dietary_preference="vegetarian",
        fitness_goal="muscle_gain"
    ))
    assert len(res.recipes) > 0
    recipe = res.recipes[0]
    assert recipe.title is not None
    assert recipe.calories_per_serving > 0
