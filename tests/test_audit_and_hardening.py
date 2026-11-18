import io
import json
import uuid
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from PIL import Image

from src.core.config import settings
from src.core.security import hash_password, create_access_token
from src.schemas.nutrition_schemas import (
    SingleMealDetail, MealPlanRequest, ChatMessageRequest,
    RefreshTokenRequest, LogoutRequest, UserRegisterRequest
)
from src.services.allergen_service import AllergenValidationService, ALLERGEN_TAXONOMY
from src.services.nutrition_service import NutritionCalculationService
from src.services.ai_service import ai_service
from src.services.meal_planner_service import MealPlannerService
from src.routes.chat_routes import ask_chat, get_chat_history, rebuild_rag_index, clear_rag_cache
from src.routes.auth_routes import register_user, refresh_token, logout_user
from src.repositories.database import (
    users_collection, refresh_tokens_collection, chat_history_collection,
    meal_plans_collection, check_database_health
)

def create_test_user(email: str, username: str, is_admin: bool = False):
    user = users_collection.find_one({"email": email})
    if not user:
        uid = str(uuid.uuid4())
        doc = {
            "id": uid,
            "email": email,
            "username": username,
            "full_name": "Test User",
            "password_hash": hash_password("ValidPass123!"),
            "role": "admin" if is_admin else "user",
            "is_admin": is_admin
        }
        users_collection.insert_one(doc)
        return doc
    return user


# ================= 1. CHATBOT SECURITY & ISOLATION TESTS =================
def test_chatbot_conversation_ownership_and_cross_user_isolation():
    """Verify that User B cannot read or append to User A's private conversation."""
    alice = create_test_user("user_alice@aaharalens.com", "alice_test")
    bob = create_test_user("user_bob@aaharalens.com", "bob_test")
    conv_id = f"conv_alice_{alice['id'][:8]}"

    # Insert Alice's conversation into chat history
    chat_history_collection.insert_one({
        "conversation_id": conv_id,
        "user_id": alice["id"],
        "question": "What is the protein content of paneer?",
        "answer": "Paneer contains 18.3g protein per 100g."
    })

    # Alice retrieves her conversation history -> Success
    alice_history = get_chat_history(conv_id, current_user=alice)
    assert len(alice_history) >= 1
    assert alice_history[0]["conversation_id"] == conv_id

    # Bob attempts to read Alice's conversation history -> 403 Forbidden!
    with pytest.raises(HTTPException) as exc_b:
        get_chat_history(conv_id, current_user=bob)
    assert exc_b.value.status_code == 403
    assert "Access denied" in exc_b.value.detail

    # Bob attempts to append a message to Alice's conversation -> 403 Forbidden!
    bob_req = ChatMessageRequest(message="Can I read this?", conversation_id=conv_id)
    with pytest.raises(HTTPException) as exc_post_b:
        ask_chat(bob_req, user=bob)
    assert exc_post_b.value.status_code == 403
    assert "Access denied" in exc_post_b.value.detail


def test_chatbot_admin_operations_authorization():
    """Verify that rebuild-index and clear-cache require administrative privileges."""
    regular_user = create_test_user("regular_user@aaharalens.com", "reguser", is_admin=False)
    admin_user = create_test_user("admin_user@aaharalens.com", "adminuser", is_admin=True)

    # Regular user attempting rebuild-index -> 403 Forbidden
    from src.routes.deps import get_current_admin_user
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None

    with pytest.raises(HTTPException) as exc_admin_check:
        get_current_admin_user(request=mock_request, current_user=regular_user)
    assert exc_admin_check.value.status_code == 403
    assert "Administrative privileges required" in exc_admin_check.value.detail

    # Admin user authorization check passes
    authorized_admin = get_current_admin_user(request=mock_request, current_user=admin_user)
    assert authorized_admin["username"] == "adminuser"

    # Admin calling rebuild-index and clear-cache directly
    reb_result = rebuild_rag_index(admin_user=authorized_admin)
    assert reb_result["status"] == "success"
    assert reb_result["chunks"] > 0

    clr_result = clear_rag_cache(admin_user=authorized_admin)
    assert clr_result["status"] == "success"


# ================= 2. AUTHENTICATION & REPLAY DETECTION TESTS =================
def test_refresh_token_replay_attack_detection_and_family_revocation():
    """
    Verify OAuth 2.0 / RFC 6819 Refresh Token Replay Protection:
    Replaying an already-rotated token invalidates all active tokens for that user family.
    """
    test_email = f"replay_{uuid.uuid4().hex[:6]}@aaharalens.com"
    reg_req = UserRegisterRequest(
        full_name="Replay Tester",
        username=f"rep_{uuid.uuid4().hex[:6]}",
        email=test_email,
        password="StrongPassword123!"
    )
    reg_resp = register_user(reg_req)
    rt_1 = reg_resp.refresh_token

    # First rotation: RT1 -> RT2 (RT1 is now revoked, RT2 is active)
    rot_resp_1 = refresh_token(RefreshTokenRequest(refresh_token=rt_1))
    rt_2 = rot_resp_1.refresh_token
    assert rt_2 != rt_1

    # Attacker replays RT1 (already used and revoked!)
    with pytest.raises(HTTPException) as exc_replay:
        refresh_token(RefreshTokenRequest(refresh_token=rt_1))
    assert exc_replay.value.status_code == 401
    assert "Compromised or revoked refresh token" in exc_replay.value.detail

    # Legitimate user now attempts to use RT2 -> Must be rejected because family was invalidated!
    with pytest.raises(HTTPException) as exc_family:
        refresh_token(RefreshTokenRequest(refresh_token=rt_2))
    assert exc_family.value.status_code == 401


def test_auth_logout_revokes_token():
    """Verify that backend /auth/logout revokes the refresh token."""
    test_email = f"logout_{uuid.uuid4().hex[:6]}@aaharalens.com"
    reg_req = UserRegisterRequest(
        full_name="Logout Tester",
        username=f"log_{uuid.uuid4().hex[:6]}",
        email=test_email,
        password="StrongPassword123!"
    )
    reg_resp = register_user(reg_req)
    rt = reg_resp.refresh_token
    user_dict = reg_resp.user.model_dump()

    # Call logout
    res = logout_user(LogoutRequest(refresh_token=rt), current_user=user_dict)
    assert "Logged out successfully" in res["message"]

    # Refresh with revoked token should fail
    with pytest.raises(HTTPException) as exc_revoked:
        refresh_token(RefreshTokenRequest(refresh_token=rt))
    assert exc_revoked.value.status_code == 401


# ================= 3. ALLERGEN SERVICE TESTS =================
def test_allergen_taxonomy_and_synonym_expansion():
    """Verify multi-dialect synonym matching across Indian and global allergens."""
    peanuts = AllergenValidationService.expand_allergens(["peanut"])
    assert "mungfali" in peanuts
    assert "groundnut" in peanuts
    assert "arachis" in peanuts

    dairy = AllergenValidationService.expand_allergens(["dairy"])
    assert "paneer" in dairy
    assert "ghee" in dairy
    assert "dahi" in dairy
    assert "curd" in dairy

    tree_nuts = AllergenValidationService.expand_allergens(["nuts"])
    assert "badam" in tree_nuts
    assert "kaju" in tree_nuts
    assert "almond" in tree_nuts
    assert "walnut" in tree_nuts

    gluten = AllergenValidationService.expand_allergens(["gluten"])
    assert "atta" in gluten
    assert "maida" in gluten
    assert "roti" in gluten
    assert "sooji" in gluten


def test_allergen_safe_meal_plan_sanitization():
    """Verify meal planner replaces unsafe dishes with verified hypoallergenic alternatives."""
    unsafe_meal = SingleMealDetail(
        meal_type="breakfast",
        dish_name="Peanut Butter Toast with Cow Milk",
        portion_size="2 slices + 1 glass (approx 200g)",
        calories=450.0,
        protein_g=18.0,
        carbs_g=42.0,
        fat_g=22.0,
        fiber_g=4.0,
        key_ingredients=["Wheat bread", "Peanut butter", "Cow milk"],
        why_recommended="Calorie rich",
        affordable_substitute="Plain Roti with Milk"
    )

    # Sanitize for peanut, dairy, and gluten allergies
    sanitized, changed = AllergenValidationService.sanitize_meal_plan_item(
        unsafe_meal, ["peanut", "dairy", "gluten"], "vegetarian"
    )
    assert changed is True
    # The new meal must NOT contain peanut, dairy, or gluten!
    is_safe, detected = AllergenValidationService.validate_meal_detail(
        sanitized, ["peanut", "dairy", "gluten"]
    )
    assert is_safe is True
    assert len(detected) == 0


def test_grocery_list_allergen_filtering():
    """Verify grocery list items containing allergens are deterministically removed."""
    grocery = {
        "produce": ["Tomatoes", "Spinach", "Lemon"],
        "grains_and_staples": ["Whole Wheat Atta", "Brown Rice", "Sooji"],
        "proteins_and_dairy": ["Low-fat Paneer", "Fresh Curd", "Tofu"],
        "pantry_and_spices": ["Peanut Oil", "Cumin", "Turmeric"]
    }
    filtered, removed = AllergenValidationService.filter_grocery_list(grocery, ["gluten", "dairy", "peanut"])
    
    assert "Whole Wheat Atta" not in filtered["grains_and_staples"]
    assert "Sooji" not in filtered["grains_and_staples"]
    assert "Brown Rice" in filtered["grains_and_staples"]

    assert "Low-fat Paneer" not in filtered["proteins_and_dairy"]
    assert "Fresh Curd" not in filtered["proteins_and_dairy"]
    assert "Tofu" in filtered["proteins_and_dairy"]

    assert "Peanut Oil" not in filtered["pantry_and_spices"]
    assert "Cumin" in filtered["pantry_and_spices"]
    assert len(removed) >= 5


# ================= 4. USDA FOODDATA CENTRAL & NUTRITION ENGINE TESTS =================
def test_usda_fooddata_central_query_mock():
    """Verify USDA FoodData Central response parsing and macro mapping."""
    mock_usda_resp = MagicMock()
    mock_usda_resp.status_code = 200
    mock_usda_resp.json.return_value = {
        "foods": [
            {
                "description": "Greek Yogurt, Plain, Nonfat",
                "servingSize": 170.0,
                "servingSizeUnit": "g",
                "foodNutrients": [
                    {"nutrientName": "Energy", "value": 59.0},
                    {"nutrientName": "Protein", "value": 10.2},
                    {"nutrientName": "Total lipid (fat)", "value": 0.4},
                    {"nutrientName": "Carbohydrate, by difference", "value": 3.6},
                    {"nutrientName": "Fiber, total dietary", "value": 0.0},
                    {"nutrientName": "Sugars, total including NLEA", "value": 3.2},
                    {"nutrientName": "Sodium, Na", "value": 36.0},
                    {"nutrientName": "Calcium, Ca", "value": 110.0},
                    {"nutrientName": "Iron, Fe", "value": 0.1}
                ]
            }
        ]
    }

    with patch("requests.get", return_value=mock_usda_resp):
        res = NutritionCalculationService.query_usda_fooddata_central("greek yogurt nonfat")
        assert res is not None
        assert res["per_100g"]["calories"] == 59.0
        assert res["per_100g"]["protein"] == 10.2
        assert "Iron" in res["vitamins_and_minerals"]
        assert "Calcium" in res["vitamins_and_minerals"]


def test_unknown_food_transparent_composite_marking():
    """Verify unknown foods return an explicit approximate composite label rather than fabricated exactness."""
    # Deterministic test: Even if external Open Food Facts returns unrelated popular products like Fromage Blanc Nature,
    # candidate relevance verification must reject it and mark the food as an approximate estimate.
    mock_off_resp = MagicMock()
    mock_off_resp.status_code = 200
    mock_off_resp.json.return_value = {
        "products": [
            {
                "product_name": "Fromage Blanc Nature",
                "generic_name": "Fromage Blanc",
                "nutriments": {
                    "energy-kcal_100g": 75.0,
                    "proteins_100g": 8.0,
                    "carbohydrates_100g": 4.0,
                    "fat_100g": 3.0
                }
            }
        ]
    }
    with patch("requests.get", return_value=mock_off_resp):
        res = NutritionCalculationService.calculate_food_nutrition("xyz_unknown_alien_food_999", "1 serving")
        assert res.is_estimated is True
        assert "Approximate Food Composite Estimate" in res.source
        assert res.health_score >= 1 and res.health_score <= 10


# ================= 5. MULTIMODAL VISION RECOGNITION TESTS =================
def test_image_preprocessing_and_decompression_safety():
    """Verify PIL image verification, decompression protection, and JPEG normalization."""
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data_uri = ai_service._preprocess_image_for_vision(buf.getvalue())
    assert data_uri.startswith("data:image/jpeg;base64,")

    # Invalid image bytes should raise ValueError
    with pytest.raises(ValueError, match="Invalid or corrupted image format"):
        ai_service._preprocess_image_for_vision(b"not_an_image_corrupted_bytes")


def test_analyze_food_image_mocked_success():
    """Verify vision service handles multi-food plates and portions using mocked response."""
    img = Image.new("RGB", (300, 300), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = json.dumps({
        "detected_items": [
            {
                "food_name": "Dal Tadka",
                "visible_portion": "1 bowl (approx 150g)",
                "visible_ingredients": ["Toor dal", "Tomatoes", "Ghee"],
                "confidence": "High"
            },
            {
                "food_name": "Roti",
                "visible_portion": "2 rotis (approx 80g)",
                "visible_ingredients": ["Whole wheat flour"],
                "confidence": "High"
            }
        ],
        "summary": "Nutritious traditional plate featuring yellow dal and 2 rotis.",
        "nutritionist_recommendations": ["Great balance of complex carbs and lentil protein."]
    })

    with patch.object(ai_service.client.chat.completions, "create", return_value=mock_vision_resp):
        result = ai_service.analyze_food_image(jpeg_bytes)
        assert len(result.detected_items) == 2
        assert result.total_calories > 0
        assert result.total_protein > 0


def test_analyze_food_image_fails_safely_when_no_food_detected():
    """Verify endpoint rejects images when vision AI detects no distinct food dishes."""
    img = Image.new("RGB", (100, 100), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = json.dumps({"detected_items": []})

    with patch.object(ai_service.client.chat.completions, "create", return_value=mock_vision_resp):
        with pytest.raises(ValueError, match="No recognizable food items could be detected"):
            ai_service.analyze_food_image(jpeg_bytes)


# ================= 6. DATABASE PERSISTENCE HEALTH =================
def test_database_health_check():
    """Verify database health probe returns valid metrics."""
    health = check_database_health()
    assert "status" in health
    assert "backend" in health
    assert health["status"] in ["healthy", "development_fallback"]
