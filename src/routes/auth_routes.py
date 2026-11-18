import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends, Request
from loguru import logger

from src.core.config import settings
from src.core.limiter import limiter
from src.schemas.nutrition_schemas import (
    UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse,
    RefreshTokenRequest, LogoutRequest, PasswordResetRequest, PasswordResetConfirmRequest
)
from src.core.security import (
    hash_password, verify_and_check_rehash, create_access_token,
    create_refresh_token, hash_token, validate_password_strength
)
from src.repositories.database import (
    users_collection, profiles_collection, refresh_tokens_collection
)
from src.routes.deps import get_current_user
from src.services.nutrition_service import NutritionCalculationService

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def register_user(req: UserRegisterRequest, request: Request = None):
    # Password strength check
    is_strong, err_msg = validate_password_strength(req.password)
    if not is_strong:
        raise HTTPException(status_code=400, detail=err_msg)

    # Check if email exists
    if users_collection.find_one({"email": req.email.lower()}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
        
    # Check if username exists
    if users_collection.find_one({"username": req.username.lower()}):
        raise HTTPException(status_code=400, detail="This username is already taken.")

    user_id = str(uuid.uuid4())
    hashed_pwd = hash_password(req.password)
    now_iso = datetime.now(timezone.utc).isoformat()

    user_doc = {
        "id": user_id,
        "email": req.email.lower(),
        "username": req.username.lower(),
        "full_name": req.full_name,
        "password_hash": hashed_pwd,
        "created_at": now_iso
    }
    users_collection.insert_one(user_doc)

    # Initialize default profile
    default_targets = NutritionCalculationService.calculate_personalized_targets(
        age=25, gender="male", height_cm=172.0, weight_kg=68.0,
        activity_level="moderate", fitness_goal="maintenance"
    )
    profile_doc = {
        "user_id": user_id,
        "profile": {
            "age": 25,
            "gender": "male",
            "height_cm": 172.0,
            "weight_kg": 68.0,
            "activity_level": "moderate",
            "dietary_preference": "vegetarian",
            "fitness_goal": "maintenance",
            "allergies": [],
            "dietary_restrictions": [],
            "preferred_cuisine": ["Indian"]
        },
        "targets": default_targets.model_dump(),
        "updated_at": now_iso
    }
    profiles_collection.insert_one(profile_doc)

    # Issue access and refresh tokens
    access_token = create_access_token(user_id)
    raw_rt, rt_hash, rt_expires = create_refresh_token(user_id)
    
    refresh_tokens_collection.insert_one({
        "token_hash": rt_hash,
        "user_id": user_id,
        "expires_at": rt_expires.isoformat(),
        "revoked": False,
        "created_at": now_iso
    })

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_rt,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user_id,
            email=user_doc["email"],
            username=user_doc["username"],
            full_name=user_doc["full_name"],
            created_at=user_doc["created_at"]
        )
    )

@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login_user(req: UserLoginRequest, request: Request = None):
    ident = req.username_or_email.lower().strip()
    user = users_collection.find_one({"email": ident}) or users_collection.find_one({"username": ident})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    is_valid, needs_rehash = verify_and_check_rehash(req.password, user.get("password_hash", ""))
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Auto-migrate password hash to modern Argon2id if it was legacy PBKDF2
    if needs_rehash:
        try:
            new_hash = hash_password(req.password)
            users_collection.update_one({"id": user["id"]}, {"password_hash": new_hash})
            logger.info(f"Seamlessly migrated password hash to Argon2id for user {user['id']}")
        except Exception as e:
            logger.warning(f"Password rehash update failed: {e}")

    access_token = create_access_token(user["id"])
    raw_rt, rt_hash, rt_expires = create_refresh_token(user["id"])
    
    refresh_tokens_collection.insert_one({
        "token_hash": rt_hash,
        "user_id": user["id"],
        "expires_at": rt_expires.isoformat(),
        "revoked": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_rt,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            username=user["username"],
            full_name=user["full_name"],
            created_at=user["created_at"]
        )
    )

@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def refresh_token(req: RefreshTokenRequest, request: Request = None):
    """
    Refresh Token Rotation:
    Verifies refresh token, invalidates it immediately, and issues a fresh token pair.
    """
    rt_hash = hash_token(req.refresh_token)
    stored_rt = refresh_tokens_collection.find_one({"token_hash": rt_hash})
    
    if not stored_rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unrecognized refresh token."
        )

    # Replay Attack Detection: If an already-revoked refresh token is re-submitted,
    # consider the token family compromised and immediately revoke ALL tokens for this user.
    if stored_rt.get("revoked", False):
        compromised_user_id = stored_rt.get("user_id")
        logger.critical(
            f"SECURITY ALERT: Refresh token replay attack detected for user_id={compromised_user_id}. "
            "Invalidating all active sessions for this user family."
        )
        if compromised_user_id:
            refresh_tokens_collection.update_many({"user_id": compromised_user_id}, {"revoked": True})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compromised or revoked refresh token. All active sessions have been invalidated."
        )

    # Check expiry
    expires_str = stored_rt.get("expires_at")
    if expires_str:
        expires_dt = datetime.fromisoformat(expires_str)
        if datetime.now(timezone.utc) > expires_dt:
            refresh_tokens_collection.update_one({"token_hash": rt_hash}, {"revoked": True})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired. Please log in again."
            )

    # Revoke current refresh token (one-time use / rotation)
    refresh_tokens_collection.update_one({"token_hash": rt_hash}, {"revoked": True})

    user_id = stored_rt["user_id"]
    user = users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    # Generate new token pair
    new_access_token = create_access_token(user_id)
    new_raw_rt, new_rt_hash, new_rt_expires = create_refresh_token(user_id)
    
    refresh_tokens_collection.insert_one({
        "token_hash": new_rt_hash,
        "user_id": user_id,
        "expires_at": new_rt_expires.isoformat(),
        "revoked": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_raw_rt,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            username=user["username"],
            full_name=user["full_name"],
            created_at=user["created_at"]
        )
    )

@router.post("/logout", status_code=status.HTTP_200_OK)
def logout_user(req: LogoutRequest, current_user: dict = Depends(get_current_user)):
    """Revokes the user's refresh token on logout, effectively invalidating their session."""
    user_id = current_user.get("id")
    if req.refresh_token:
        rt_hash = hash_token(req.refresh_token)
        refresh_tokens_collection.update_one({"token_hash": rt_hash}, {"revoked": True})
    elif user_id:
        refresh_tokens_collection.update_many({"user_id": user_id}, {"revoked": True})
    return {"message": "Logged out successfully. Tokens invalidated."}

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=current_user["id"],
        email=current_user["email"],
        username=current_user["username"],
        full_name=current_user["full_name"],
        created_at=current_user["created_at"]
    )
