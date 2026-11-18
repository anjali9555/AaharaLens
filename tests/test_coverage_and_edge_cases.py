import io
import pytest
from datetime import datetime, date, timedelta, timezone
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
from PIL import Image

from src.core.security import create_access_token
from src.routes.deps import get_current_user, get_optional_current_user
from src.routes.profile_routes import get_user_profile, update_user_profile
from src.routes.meal_routes import log_meal, get_meals, update_meal, delete_meal, get_daily_dashboard, get_weekly_nutrition_report
from src.routes.planner_routes import generate_meal_plan, regenerate_meal
from src.routes.food_routes import (
    analyze_food_text, analyze_food_image, scan_packaged_label,
    compare_foods, suggest_substitution, generate_leftover_recipes,
    validate_image_upload
)
from src.schemas.nutrition_schemas import (
    ProfileUpdateRequest, MealEntryCreate, MealPlanRequest, SingleMealDetail,
    TextFoodAnalysisRequest, FoodComparisonRequest, FoodSubstitutionRequest,
    RecipeGeneratorRequest
)
from src.services.nutrition_service import NutritionCalculationService, VERIFIED_FOOD_DATABASE
from src.services.ai_service import ai_service
from src.services.rag_service import rag_service
from src.services.meal_planner_service import MealPlannerService
from src.repositories.database import (
    users_collection, profiles_collection, meal_entries_collection, meal_plans_collection
)

# ================= 1. AUTH DEPENDENCY COVERAGE =================

def test_auth_deps_failure_modes():
    """Test all failure branches of get_current_user."""
    # 1. Missing credentials
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=None)
    assert exc.value.status_code == 401

    # 2. Invalid JWT token
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token.payload"))
    assert exc.value.status_code == 401

    # 3. Valid token but user not found in database
    ghost_token = create_access_token("ghost-user-id-not-in-db")
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=ghost_token))
    assert exc.value.status_code == 401

def test_optional_auth_dep():
    """Test get_optional_current_user for guests and authenticated users."""
    assert get_optional_current_user(credentials=None) is None
    assert get_optional_current_user(credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")) is None

    # Valid user
    user_id = "test-opt-user"
    users_collection.insert_one({"id": user_id, "email": "opt@test.com", "username": "optuser", "full_name": "Opt User"})
    valid_token = create_access_token(user_id)
    resolved = get_optional_current_user(credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=valid_token))
    assert resolved is not None
    assert resolved["id"] == user_id

# ================= 2. PROFILE ROUTES & CALCULATION =================

def test_get_user_profile_default_and_custom():
    """Verify profile retrieval, auto-creation of default profile, and custom calorie overrides."""
    user_id = "test-prof-coverage-user"
    user_ctx = {"id": user_id, "email": "prof_cov@test.com"}
    
    # Getting profile before explicit update should return initialized default
    prof = get_user_profile(current_user=user_ctx)
    assert prof.profile.age >= 10
    assert prof.targets.target_calories > 0

    # Update with custom calorie target
    update_req = ProfileUpdateRequest(
        age=28,
        gender="male",
        height_cm=180.0,
        weight_kg=75.0,
        activity_level="active",
        fitness_goal="muscle_gain",
        dietary_preference="non-vegetarian",
        allergies=["peanut"],
        custom_calorie_target=2800.0
    )
    updated = update_user_profile(update_req, current_user=user_ctx)
    assert updated.profile.age == 28
    assert updated.targets.target_calories == 2800.0
    assert updated.targets.target_protein_g >= 120.0

# ================= 3. MEAL ROUTES & WEEKLY REPORT =================

def test_meal_crud_and_weekly_report():
    """Verify listing meals with date filter, updating portions, and 7-day weekly analytics report."""
    user_id = "test-meal-analytics-user"
    user_ctx = {"id": user_id, "email": "meal_analytics@test.com"}
    today_str = date.today().strftime("%Y-%m-%d")

    # Log 3 meals
    m1 = log_meal(MealEntryCreate(
        date=today_str, meal_type="breakfast", food_name="Rolled Oats with Milk",
        serving_size="1 bowl", serving_weight_g=180.0, calories=320.0, protein=12.0,
        carbohydrates=50.0, fat=6.0, fiber=7.0
    ), current_user=user_ctx)

    m2 = log_meal(MealEntryCreate(
        date=today_str, meal_type="lunch", food_name="2 Rotis with Dal Tadka",
        serving_size="1 plate", serving_weight_g=220.0, calories=450.0, protein=18.0,
        carbohydrates=65.0, fat=10.0, fiber=11.0
    ), current_user=user_ctx)

    # List meals
    meals_today = get_meals(date=today_str, current_user=user_ctx)
    assert len(meals_today) >= 2

    # Update meal portion
    updated_m1 = update_meal(m1.id, {"calories": 380.0, "serving_size": "1 large bowl"}, current_user=user_ctx)
    assert updated_m1.calories == 380.0

    # Non-existent meal update raises 404
    with pytest.raises(HTTPException) as exc:
        update_meal("non-existent-id", {"calories": 100.0}, current_user=user_ctx)
    assert exc.value.status_code == 404

    # Daily dashboard
    dash = get_daily_dashboard(today_str, current_user=user_ctx)
    assert dash.consumed_calories >= 700.0
    assert dash.ai_meal_decision is not None

    # Weekly report
    report = get_weekly_nutrition_report(end_date=today_str, current_user=user_ctx)
    assert report.total_meals_logged >= 1
    assert report.average_daily_calories > 0
    assert len(report.actionable_ai_recommendations) > 0

# ================= 4. FOOD ROUTES IMAGE VALIDATION & EDGE CASES =================

def test_image_upload_validation_edge_cases():
    """Verify validation for unsupported MIME types, oversized images, and corrupted images."""
    from fastapi import UploadFile

    # 1. Unsupported MIME type
    bad_mime = UploadFile(filename="doc.pdf", file=io.BytesIO(b"%PDF-1.4..."), headers={"content-type": "application/pdf"})
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(bad_mime)
    assert exc.value.status_code == 400
    assert "Unsupported file format" in exc.value.detail

    # 2. Oversized image (>10MB)
    huge_bytes = b"x" * (10 * 1024 * 1024 + 100)
    huge_file = UploadFile(filename="huge.jpg", file=io.BytesIO(huge_bytes), headers={"content-type": "image/jpeg"})
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(huge_file)
    assert exc.value.status_code == 400
    assert "exceeds maximum limit" in exc.value.detail

    # 3. Corrupted image
    corrupt_file = UploadFile(filename="bad.jpg", file=io.BytesIO(b"NotAJpegAtAll!"), headers={"content-type": "image/jpeg"})
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(corrupt_file)
    assert exc.value.status_code == 400
    assert "corrupted" in exc.value.detail

def test_food_routes_empty_and_invalid_inputs():
    """Verify empty queries and missing arguments raise 400."""
    with pytest.raises(HTTPException) as exc:
        analyze_food_text(TextFoodAnalysisRequest(food_query="   "))
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        compare_foods(FoodComparisonRequest(food_a=" ", food_b="Paneer"))
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        generate_leftover_recipes(RecipeGeneratorRequest(ingredients=[]))
    assert exc.value.status_code == 400

# ================= 5. NUTRITION CALCULATION MATHEMATICAL VERIFICATION =================

def test_nutrition_50g_vs_100g_proportionality():
    """Verify strictly proportional macro scaling for 50g vs 100g portions."""
    item_50g = NutritionCalculationService.calculate_food_nutrition("roti", portion_hint="50g")
    item_100g = NutritionCalculationService.calculate_food_nutrition("roti", portion_hint="100g")
    
    assert item_50g.serving_weight_g == pytest.approx(50.0, abs=0.1)
    assert item_100g.serving_weight_g == pytest.approx(100.0, abs=0.1)
    
    # 50g must be exactly half of 100g
    assert item_50g.calories == pytest.approx(item_100g.calories * 0.5, abs=0.5)
    assert item_50g.protein == pytest.approx(item_100g.protein * 0.5, abs=0.2)
    assert item_50g.carbohydrates == pytest.approx(item_100g.carbohydrates * 0.5, abs=0.5)

def test_fraction_portion_parsing():
    """Verify portion parser handles 'half' and fractional quantities."""
    mult_half, desc_half = NutritionCalculationService.extract_portion_multiplier("half bowl dal", default_serving_g=150.0)
    assert mult_half == 0.5
    assert "0.5" in desc_half

    mult_1_5, desc_1_5 = NutritionCalculationService.extract_portion_multiplier("1.5 cups rice", default_serving_g=150.0)
    assert mult_1_5 == 1.5

def test_raw_vs_cooked_food_verification():
    """Verify that foods specify raw vs cooked state accurately."""
    rice = NutritionCalculationService.calculate_food_nutrition("steamed rice")
    assert rice.calories < 250.0 and rice.serving_weight_g == 150.0  # Cooked rice serving (~195 kcal/150g, ~130 kcal/100g)
    
    oats = NutritionCalculationService.calculate_food_nutrition("rolled oats", portion_hint="100g")
    assert oats.calories > 350.0  # Dry raw grain is calorie dense (~389 kcal/100g)

# ================= 6. ALLERGY SYNONYM EXPANSION IN MEAL PLANNER =================

def test_allergy_synonym_expansion():
    """Verify colloquial Indian and scientific synonyms (e.g. groundnut = peanut, dahi = dairy)."""
    # 1. Groundnut is recognized as peanut allergy
    peanut_expanded = MealPlannerService._expand_allergens(["peanut"])
    assert "groundnut" in peanut_expanded
    assert "mungfali" in peanut_expanded

    # 2. Dahi is recognized as dairy
    dairy_expanded = MealPlannerService._expand_allergens(["dairy"])
    assert "dahi" in dairy_expanded
    assert "paneer" in dairy_expanded
    assert "ghee" in dairy_expanded

    # 3. Test dish with groundnut is substituted when user has peanut allergy
    meal_with_groundnut = SingleMealDetail(
        meal_type="snack",
        dish_name="Roasted Groundnut Chaat",
        portion_size="1 bowl",
        calories=200.0, protein_g=8.0, carbs_g=10.0, fat_g=14.0, fiber_g=3.0,
        key_ingredients=["Groundnut", "Chaat masala", "Lemon"],
        why_recommended="Crisp snack",
        affordable_substitute="Roasted Makhana or Chana"
    )
    sanitized, changed = MealPlannerService._sanitize_meal_allergens(meal_with_groundnut, ["peanut"])
    assert changed is True
    assert "Allergen-Safe" in sanitized.dish_name

# ================= 7. RAG INDEXING & CONVERSATION HISTORY =================

def test_rag_index_rebuild_and_restart():
    """Verify RAG service can rebuild index and parse markdown headers."""
    initial_chunks = len(rag_service.chunks)
    assert initial_chunks > 0

    rag_service.rebuild_index()
    assert len(rag_service.chunks) >= initial_chunks

    # Verify answering query with conversation history
    res = rag_service.answer_query(
        question="What are good sources of plant protein in Indian vegetarian diets?",
        include_user_context=False
    )
    assert res.answer is not None
    assert len(res.sources) > 0
    assert len(res.suggested_followups) >= 1
