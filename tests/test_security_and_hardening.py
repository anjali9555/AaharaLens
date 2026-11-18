import io
import pytest
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from PIL import Image

from src.core.security import (
    hash_password, verify_password, verify_and_check_rehash,
    create_access_token, decode_access_token, create_refresh_token,
    hash_token, validate_password_strength, _verify_pbkdf2_legacy
)
from src.schemas.nutrition_schemas import (
    UserRegisterRequest, UserLoginRequest, RefreshTokenRequest, LogoutRequest,
    MealPlanRequest, SingleMealDetail, MealEntryCreate
)
from src.routes.auth_routes import register_user, login_user, refresh_token, logout_user
from src.routes.meal_routes import log_meal, get_daily_dashboard, delete_meal
from src.services.meal_planner_service import MealPlannerService
from src.services.ai_service import ai_service
from src.repositories.database import users_collection, refresh_tokens_collection, meal_entries_collection

def test_argon2id_and_legacy_pbkdf2_compatibility():
    """Verify that modern Argon2id and legacy PBKDF2 hashes both verify accurately."""
    pwd = "StrongPassword2026!"
    
    # Modern Argon2id
    argon_hash = hash_password(pwd)
    assert argon_hash.startswith("$argon2id$")
    assert verify_password(pwd, argon_hash) is True
    assert verify_password("WrongPassword", argon_hash) is False
    
    valid, needs_rehash = verify_and_check_rehash(pwd, argon_hash)
    assert valid is True
    assert needs_rehash is False
    
    # Simulate legacy PBKDF2 hash (salt$key)
    import hashlib, os
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac('sha256', pwd.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    legacy_hash = f"{salt}${key}"
    
    assert verify_password(pwd, legacy_hash) is True
    assert verify_password("WrongPassword", legacy_hash) is False
    
    # Verify migration detection: legacy hash should signal needs_rehash = True
    valid, needs_rehash = verify_and_check_rehash(pwd, legacy_hash)
    assert valid is True
    assert needs_rehash is True

def test_password_strength_enforcement():
    """Verify password strength validation rules."""
    # Too short (< 8 chars)
    valid, err = validate_password_strength("Short1!")
    assert valid is False
    assert "at least 8 characters" in err

    # No numbers or special characters
    valid, err = validate_password_strength("AllLettersOnly")
    assert valid is False
    assert "number or special character" in err

    # No letters
    valid, err = validate_password_strength("1234567890!")
    assert valid is False
    assert "at least one letter" in err

    # Valid strong passwords
    valid, err = validate_password_strength("Secure1234#")
    assert valid is True
    assert err is None

def test_refresh_token_lifecycle_and_rotation():
    """Verify refresh token generation, hashing, one-time rotation, and revocation."""
    user_id = "test-refresh-user-888"
    users_collection.insert_one({
        "id": user_id,
        "email": "refresh_tester@test.com",
        "username": "refresh_tester",
        "full_name": "Refresh Tester",
        "password_hash": "dummyhash",
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    raw_rt, rt_hash, expires_at = create_refresh_token(user_id)
    
    assert raw_rt.startswith("rt_")
    assert len(raw_rt) > 40
    assert hash_token(raw_rt) == rt_hash
    assert expires_at > datetime.now(timezone.utc)

    # Store in database
    refresh_tokens_collection.insert_one({
        "token_hash": rt_hash,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
        "revoked": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # Test refresh token rotation
    req = RefreshTokenRequest(refresh_token=raw_rt)
    new_tokens = refresh_token(req)
    assert new_tokens.access_token is not None
    assert new_tokens.refresh_token is not None
    assert new_tokens.refresh_token != raw_rt

    # The old refresh token MUST be marked revoked
    old_doc = refresh_tokens_collection.find_one({"token_hash": rt_hash})
    assert old_doc["revoked"] is True

    # Re-using the same old refresh token should be rejected (replay attack prevention)
    with pytest.raises(HTTPException) as exc:
        refresh_token(req)
    assert exc.value.status_code == 401

def test_logout_revocation():
    """Verify that logging out revokes the active refresh token."""
    user_id = "test-logout-user-999"
    raw_rt, rt_hash, expires_at = create_refresh_token(user_id)
    refresh_tokens_collection.insert_one({
        "token_hash": rt_hash,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
        "revoked": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    user_context = {"id": user_id, "email": "logout@test.com"}
    res = logout_user(LogoutRequest(refresh_token=raw_rt), current_user=user_context)
    assert "Logged out successfully" in res["message"]

    # Check revoked in DB
    revoked_doc = refresh_tokens_collection.find_one({"token_hash": rt_hash})
    assert revoked_doc["revoked"] is True

def test_deterministic_allergen_filtering():
    """Verify that meals violating user allergies are deterministically substituted."""
    meal = SingleMealDetail(
        meal_type="breakfast",
        dish_name="Peanut Butter Toast with Banana",
        portion_size="2 slices",
        calories=320.0,
        protein_g=10.0,
        carbs_g=40.0,
        fat_g=14.0,
        fiber_g=4.0,
        key_ingredients=["Whole wheat bread", "Peanut butter", "Banana"],
        why_recommended="Energy dense breakfast.",
        affordable_substitute="Almond Butter Toast or Sprouted Moong Bowl"
    )

    # User allergic to peanut
    sanitized, was_changed = MealPlannerService._sanitize_meal_allergens(meal, ["peanut"])
    assert was_changed is True
    assert "peanut" not in sanitized.dish_name.lower()
    assert all("peanut" not in i.lower() for i in sanitized.key_ingredients)
    assert "Allergen-Safe" in sanitized.dish_name

def test_image_preprocessing_normalizes_to_jpeg():
    """Verify image preprocessing converts non-JPEG or RGBA images into safe JPEG URIs."""
    # Create an RGBA PNG in memory
    img = Image.new("RGBA", (2000, 1500), color=(255, 100, 50, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    data_uri = ai_service._preprocess_image_for_vision(png_bytes)
    assert data_uri.startswith("data:image/jpeg;base64,")
    
    # Decode and check that dimensions are resized under 1280x1280
    import base64
    b64_part = data_uri.split(",", 1)[1]
    decoded_img = Image.open(io.BytesIO(base64.b64decode(b64_part)))
    assert decoded_img.format == "JPEG"
    assert decoded_img.width <= 1280
    assert decoded_img.height <= 1280

def test_cross_user_isolation():
    """Verify User A cannot delete or access User B's diary entries."""
    user_a = {"id": "user-alice-101", "email": "alice@test.com"}
    user_b = {"id": "user-bob-202", "email": "bob@test.com"}

    # Alice logs a meal
    req = MealEntryCreate(
        date="2026-11-01",
        meal_type="lunch",
        food_name="Steamed Rice with Dal",
        serving_size="1 plate",
        serving_weight_g=250.0,
        calories=350.0,
        protein=12.0,
        carbohydrates=60.0,
        fat=4.0,
        fiber=6.0
    )
    meal_entry = log_meal(req, current_user=user_a)
    entry_id = meal_entry.id

    # Bob attempts to delete Alice's meal entry
    with pytest.raises(HTTPException) as exc:
        delete_meal(meal_id=entry_id, current_user=user_b)
    assert exc.value.status_code == 404

    # Alice can successfully delete her own entry
    del_res = delete_meal(meal_id=entry_id, current_user=user_a)
    assert del_res["status"] == "success"

def test_duplicate_registration_protection():
    """Verify duplicate email and username are rejected."""
    email = "unique_tester_99@test.com"
    username = "unique_user_99"
    pwd = "StrongPassword123!"

    req = UserRegisterRequest(email=email, username=username, full_name="Unique User", password=pwd)
    
    # First registration succeeds or user exists
    if not users_collection.find_one({"email": email}):
        res = register_user(req)
        assert res.user.email == email

    # Duplicate registration should raise HTTP 400
    with pytest.raises(HTTPException) as exc:
        register_user(req)
    assert exc.value.status_code == 400
    assert "already exists" in exc.value.detail or "taken" in exc.value.detail

def test_invalid_login_credentials():
    """Verify invalid password or non-existent username returns 401."""
    with pytest.raises(HTTPException) as exc:
        login_user(UserLoginRequest(username_or_email="nonexistent_user_xyz", password="SomePassword123!"))
    assert exc.value.status_code == 401

def test_expired_access_token_handling():
    """Verify decode_access_token returns None when token is expired."""
    user_id = "test-expired-user-555"
    # Token expired 1 hour ago
    expired_token = create_access_token(user_id, expires_delta=timedelta(minutes=-60))
    decoded = decode_access_token(expired_token)
    assert decoded is None

def test_rate_limiter_key_building():
    """Verify rate limiter key extracts user ID for authenticated requests and IP for guests."""
    from src.core.limiter import rate_limit_key_builder
    from starlette.requests import Request
    
    # Guest request with IP
    guest_scope = {"type": "http", "client": ("192.168.1.100", 5000), "headers": []}
    guest_req = Request(guest_scope)
    key_guest = rate_limit_key_builder(guest_req)
    assert key_guest == "192.168.1.100"

    # Authenticated request with Bearer token
    user_token = create_access_token("alice-99")
    auth_scope = {
        "type": "http",
        "client": ("192.168.1.100", 5000),
        "headers": [(b"authorization", f"Bearer {user_token}".encode())]
    }
    auth_req = Request(auth_scope)
    key_auth = rate_limit_key_builder(auth_req)
    assert key_auth == "user:alice-99"
