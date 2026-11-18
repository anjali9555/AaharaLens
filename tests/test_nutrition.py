import pytest
from src.services.nutrition_service import NutritionCalculationService, VERIFIED_FOOD_DATABASE
from src.core.security import hash_password, verify_password, create_access_token, decode_access_token

def test_verified_food_database_lookup():
    """Verify that traditional Indian foods return exact laboratory standards."""
    dal = NutritionCalculationService.calculate_food_nutrition("Dal Tadka")
    assert dal.food_name == "Dal Tadka"
    assert dal.calories > 0
    assert dal.protein > 5.0
    assert "Yellow Toor Dal" in dal.detected_ingredients
    assert dal.is_estimated is False

def test_portion_scaling():
    """Verify that specifying '2 rotis' scales calories and macros accurately."""
    roti_1 = NutritionCalculationService.calculate_food_nutrition("roti", portion_hint="1 roti")
    roti_2 = NutritionCalculationService.calculate_food_nutrition("roti", portion_hint="2 rotis")
    
    assert roti_2.serving_weight_g == pytest.approx(roti_1.serving_weight_g * 2, abs=0.5)
    assert roti_2.calories == pytest.approx(roti_1.calories * 2, abs=1.0)
    assert roti_2.protein == pytest.approx(roti_1.protein * 2, abs=0.2)

def test_tdee_and_bmr_calculation():
    """Verify Mifflin-St Jeor clinical calculations."""
    # 25yo male, 70kg, 175cm, moderate activity
    # BMR = (10*70) + (6.25*175) - (5*25) + 5 = 700 + 1093.75 - 125 + 5 = 1673.75
    # TDEE = 1673.75 * 1.55 = ~2594.3 kcal
    targets = NutritionCalculationService.calculate_personalized_targets(
        age=25,
        gender="male",
        height_cm=175.0,
        weight_kg=70.0,
        activity_level="moderate",
        fitness_goal="maintenance"
    )
    assert targets.bmr == pytest.approx(1673.8, abs=1.0)
    assert targets.tdee == pytest.approx(2594.3, abs=2.0)
    assert targets.target_protein_g >= 70.0
    assert targets.target_water_liters >= 2.0

def test_password_security():
    """Verify password hashing and verification."""
    password = "MySecurePassword123!"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

def test_jwt_token_handling():
    """Verify JWT token creation and decoding."""
    user_id = "test-user-123"
    token = create_access_token(user_id)
    assert isinstance(token, str)
    decoded = decode_access_token(token)
    assert decoded == user_id
