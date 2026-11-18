import pytest
from src.schemas.nutrition_schemas import (
    UserRegisterRequest, UserLoginRequest, ProfileUpdateRequest,
    TextFoodAnalysisRequest, FoodComparisonRequest, FoodSubstitutionRequest,
    MealEntryCreate, MealPlanRequest, ChatMessageRequest
)
from src.routes.auth_routes import register_user, login_user, get_current_user_profile
from src.routes.profile_routes import get_user_profile, update_user_profile
from src.routes.food_routes import analyze_food_text, compare_foods, suggest_substitution
from src.routes.meal_routes import log_meal, get_meals, get_daily_dashboard, delete_meal
from src.routes.planner_routes import generate_meal_plan
from src.routes.chat_routes import ask_chat
from src.main import health_check, legacy_analyze_food, legacy_ask_question

def test_health_check_endpoint():
    res = health_check()
    assert res["status"] == "healthy"
    assert "groq_model" in res

def test_legacy_endpoints():
    res_food = legacy_analyze_food("apple")
    assert res_food["food"] == "apple"
    assert res_food["data"]["fiber"] > 0
    
    res_ask = legacy_ask_question("what are the health benefits of oats?")
    assert "oats" in res_ask["answer"].lower()

def test_full_auth_and_profile_flow():
    email = "integration_test@example.com"
    username = "integration_user"
    pwd = "SecurePassword123!"

    # 1. Register
    reg_req = UserRegisterRequest(email=email, username=username, full_name="Integration Tester", password=pwd)
    try:
        reg_res = register_user(reg_req)
        assert reg_res.access_token is not None
        assert reg_res.user.email == email
        user_dict = {"id": reg_res.user.id, "email": email, "username": username, "full_name": "Integration Tester", "created_at": reg_res.user.created_at}
    except Exception:
        # If already registered, login
        login_res = login_user(UserLoginRequest(username_or_email=email, password=pwd))
        assert login_res.access_token is not None
        user_dict = {"id": login_res.user.id, "email": email, "username": username, "full_name": "Integration Tester", "created_at": login_res.user.created_at}

    # 2. Get Me
    me = get_current_user_profile(user_dict)
    assert me.email == email

    # 3. Update Profile
    prof_update = ProfileUpdateRequest(
        age=30, gender="female", height_cm=165.0, weight_kg=60.0,
        activity_level="moderate", dietary_preference="vegetarian",
        fitness_goal="weight_loss", allergies=["peanuts"],
        dietary_restrictions=["low-sodium"], preferred_cuisine=["Indian"]
    )
    prof_res = update_user_profile(prof_update, current_user=user_dict)
    assert prof_res.targets.target_calories > 1000.0
    assert prof_res.profile.dietary_preference == "vegetarian"

    # 4. Log Meal
    meal_req = MealEntryCreate(
        date="2026-11-01",
        meal_type="breakfast",
        food_name="Rolled Oats with Banana",
        serving_size="1 bowl",
        serving_weight_g=180.0,
        calories=320.0,
        protein=11.0,
        carbohydrates=55.0,
        fat=6.0,
        fiber=7.0,
        notes="Pre-workout breakfast"
    )
    meal = log_meal(meal_req, current_user=user_dict)
    assert meal.id is not None
    assert meal.calories == 320.0

    # 5. Daily Dashboard
    dash = get_daily_dashboard("2026-11-01", current_user=user_dict)
    assert dash.consumed_calories >= 320.0
    assert len(dash.meals_by_type["breakfast"]) >= 1

    # 6. Delete Meal
    del_res = delete_meal(meal.id, current_user=user_dict)
    assert del_res["status"] == "success"

def test_food_analysis_routes():
    # Text Analysis
    text_req = TextFoodAnalysisRequest(food_query="2 rotis and 1 bowl dal tadka")
    res = analyze_food_text(text_req, user=None)
    assert len(res.detected_items) >= 1
    assert res.total_calories > 0
    assert res.total_protein > 0

    # Comparison
    comp_req = FoodComparisonRequest(food_a="paneer", food_b="tofu")
    comp_res = compare_foods(comp_req)
    assert comp_res.food_a.food_name != ""
    assert comp_res.food_b.food_name != ""
    assert comp_res.winner_for_muscle_gain != ""

    # Substitution
    sub_req = FoodSubstitutionRequest(food_name="paneer", goal_or_reason="lower calorie vegan")
    sub_res = suggest_substitution(sub_req)
    assert len(sub_res.substitutions) >= 1

def test_meal_planner_and_chat():
    user_dict = {"id": "test-planner-user-01"}
    plan_req = MealPlanRequest(duration_days=1, custom_calories=1800.0, dietary_preference="vegetarian")
    plan_res = generate_meal_plan(plan_req, current_user=user_dict)
    assert plan_res.duration_days == 1
    assert len(plan_res.daily_plans) == 1
    assert plan_res.daily_plans[0].breakfast.dish_name != ""

    chat_req = ChatMessageRequest(message="What are the benefits of oats?", include_user_context=False)
    chat_res = ask_chat(chat_req, user=user_dict)
    assert "oats" in chat_res.answer.lower() or len(chat_res.answer) > 20
    assert len(chat_res.sources) >= 1
