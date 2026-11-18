import io
import json
import pytest
from PIL import Image
from datetime import datetime, date, timedelta, timezone
from fastapi import HTTPException
from starlette.requests import Request

from src.main import app, custom_rate_limit_exceeded_handler, TimingASGIMiddleware
from src.ai_model import get_nutrition_info, query_nutrition_knowledge
from src.routes.planner_routes import generate_meal_plan, regenerate_meal
from src.routes.profile_routes import get_user_profile, update_user_profile
from src.routes.auth_routes import login_user, refresh_token
from src.schemas.nutrition_schemas import (
    MealPlanRequest, UserLoginRequest, RefreshTokenRequest, ProfileUpdateRequest
)
from src.services.ai_service import ai_service
from src.services.meal_planner_service import MealPlannerService
from src.services.nutrition_service import NutritionCalculationService
from src.repositories.database import (
    users_collection, profiles_collection, meal_plans_collection, refresh_tokens_collection
)
from src.core.security import hash_password, create_refresh_token, hash_token
from slowapi.errors import RateLimitExceeded
from limits import parse
from slowapi.wrappers import Limit

def test_legacy_ai_model_bridge():
    """Verify legacy ai_model.py bridge exports and functions correctly."""
    nutr = get_nutrition_info("Dal Tadka")
    assert "protein" in nutr
    assert nutr["protein"] > 5.0
    assert "carbohydrates" in nutr

    rag_ans = query_nutrition_knowledge("What is beta-glucan in oats?")
    assert isinstance(rag_ans, str)
    assert len(rag_ans) > 10
    assert "beta-glucan" in rag_ans.lower() or "oats" in rag_ans.lower()

def test_planner_routes_profile_context_and_regeneration():
    """Verify planner routes pre-populate user profile goals and regenerate meals."""
    user_id = "test-planner-ctx-user"
    user_ctx = {"id": user_id, "email": "planner_ctx@test.com"}

    # Set up user profile
    profiles_collection.insert_one({
        "user_id": user_id,
        "profile": {
            "age": 27,
            "dietary_preference": "vegetarian",
            "allergies": ["peanut", "dairy"],
            "fitness_goal": "weight_loss"
        },
        "targets": {"target_calories": 1750.0}
    })

    # Generate plan with empty overrides (should pull from profile)
    plan_req = MealPlanRequest(duration_days=1)
    plan_res = generate_meal_plan(plan_req, current_user=user_ctx)
    assert plan_res.duration_days == 1
    assert len(plan_res.daily_plans) == 1

    # Regenerate single meal
    regen = regenerate_meal(
        plan_id=plan_res.id,
        day_number=1,
        meal_type="breakfast",
        reason="Prefer a warm porridge",
        current_user=user_ctx
    )
    assert regen is not None
    assert regen.dish_name is not None

    # Regenerate on non-existent plan raises 404
    with pytest.raises(HTTPException) as exc:
        regenerate_meal(plan_id="non-existent-plan-id", day_number=1, meal_type="lunch", current_user=user_ctx)
    assert exc.value.status_code == 404

def test_auth_password_auto_migration_on_login():
    """Verify legacy PBKDF2 user login seamlessly migrates password to Argon2id in DB."""
    import hashlib, os
    user_id = "test-legacy-mig-user"
    email = "legacy_mig@test.com"
    pwd = "LegacySecret2026!"
    
    # Store legacy PBKDF2 hash
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac('sha256', pwd.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    legacy_hash = f"{salt}${key}"
    
    users_collection.insert_one({
        "id": user_id,
        "email": email,
        "username": "legacymig",
        "full_name": "Legacy Migration",
        "password_hash": legacy_hash,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # Login triggers auto-migration
    res = login_user(UserLoginRequest(username_or_email=email, password=pwd))
    assert res.access_token is not None
    assert res.user.email == email

    # Verify user record in database now has Argon2id hash!
    migrated_user = users_collection.find_one({"id": user_id})
    assert migrated_user["password_hash"].startswith("$argon2id$")

def test_refresh_token_expired_rejection():
    """Verify expired refresh tokens are rejected and marked revoked."""
    user_id = "test-expired-rt-user"
    users_collection.insert_one({
        "id": user_id,
        "email": "expired_rt@test.com",
        "username": "expiredrt",
        "full_name": "Expired RT",
        "password_hash": "dummy"
    })
    
    raw_rt, rt_hash, _ = create_refresh_token(user_id)
    # Stored with past expiration date
    past_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    refresh_tokens_collection.insert_one({
        "token_hash": rt_hash,
        "user_id": user_id,
        "expires_at": past_date,
        "revoked": False,
        "created_at": past_date
    })

    with pytest.raises(HTTPException) as exc:
        refresh_token(RefreshTokenRequest(refresh_token=raw_rt))
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()

    # Must be marked revoked
    doc = refresh_tokens_collection.find_one({"token_hash": rt_hash})
    assert doc["revoked"] is True

def test_rate_limiter_exceeded_handler_rfc_compliance():
    """Verify rate limit handler formats RFC 6585 response with Retry-After header."""
    import asyncio
    lim = Limit(
        parse("10/15minutes"),
        key_func=lambda request: "127.0.0.1",
        scope="auth_route",
        per_method=False,
        methods=None,
        error_message=None,
        exempt_when=None,
        cost=1,
        override_defaults=False
    )
    exc = RateLimitExceeded(lim)
    req = Request({"type": "http", "headers": []})
    resp = custom_rate_limit_exceeded_handler(req, exc)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    body = json.loads(resp.body.decode())
    assert body["status_code"] == 429
    assert "Rate limit exceeded" in body["detail"]

def test_ai_service_label_scanner_blank_or_unreadable_image():
    """TEST A: Verify unreadable or blank image safely returns zero health score and no fabricated values."""
    img = Image.new("RGB", (300, 300), color=(240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    
    res = ai_service.scan_food_label(buf.getvalue(), mime_type="image/jpeg")
    assert res.product_name is not None
    assert res.health_rating_score == 0
    assert res.calories == 0.0
    assert res.protein == 0.0
    assert res.carbohydrates == 0.0
    assert res.total_fat == 0.0
    assert "No label detected" in res.flags
    assert "no legible text" in res.nutritionist_verdict.lower()


def test_ai_service_label_scanner_mocked():
    """TEST B: Verify valid packaged nutrition label extraction with structured mocked Groq Vision response."""
    from unittest.mock import MagicMock, patch

    img = Image.new("RGB", (300, 300), color=(200, 220, 240))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")

    mock_label_data = {
        "product_name": "Organic Almond Butter",
        "serving_size": "2 tbsp (32g)",
        "servings_per_container": 14.0,
        "calories": 190.0,
        "protein": 7.0,
        "carbohydrates": 6.0,
        "total_fat": 17.0,
        "saturated_fat": 1.5,
        "dietary_fiber": 3.0,
        "sugars": 2.0,
        "added_sugars": 0.0,
        "sodium_mg": 5.0,
        "key_ingredients": ["Dry Roasted Organic Almonds", "Sea Salt"],
        "allergens": ["Tree Nuts (Almonds)"],
        "health_rating_score": 8,
        "nutritionist_verdict": "Nutrient-dense whole food rich in monounsaturated fats and plant protein.",
        "flags": ["Zero added sugars", "Low sodium (<140mg)"]
    }

    mock_chat_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(mock_label_data)
    mock_chat_completion.choices = [mock_choice]

    with patch.object(ai_service.client.chat.completions, "create", return_value=mock_chat_completion):
        res = ai_service.scan_food_label(buf.getvalue(), mime_type="image/jpeg")
        assert res.product_name == "Organic Almond Butter"
        assert res.serving_size == "2 tbsp (32g)"
        assert res.calories == 190.0
        assert res.protein == 7.0
        assert res.carbohydrates == 6.0
        assert res.total_fat == 17.0
        assert res.health_rating_score == 8
        assert res.health_rating_score >= 1
        assert "Zero added sugars" in res.flags
        assert "Tree Nuts (Almonds)" in res.allergens
