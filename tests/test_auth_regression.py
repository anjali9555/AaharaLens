import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.repositories.database import users_collection, refresh_tokens_collection
from src.routes.auth_routes import register_user, login_user
from src.schemas.nutrition_schemas import UserRegisterRequest, UserLoginRequest

def test_auth_registration_and_immediate_login_regression():
    """Verify that immediately following successful registration, login succeeds with 200 OK and valid JWT tokens."""
    email = "regression_user@aaharalens.test"
    username = "regresstestuser"
    password = "SecurePassword123!@"

    # Clean up any residual test record
    users_collection.delete_one({"email": email})
    users_collection.delete_one({"username": username})

    # 1. Register user
    reg_req = UserRegisterRequest(
        email=email,
        username=username,
        full_name="Regression Test User",
        password=password
    )
    reg_res = register_user(reg_req)
    assert reg_res.user.email == email
    assert reg_res.user.username == username

    # 2. Immediate Login via Email
    login_req_email = UserLoginRequest(
        username_or_email=email,
        password=password
    )
    login_res_email = login_user(login_req_email)
    assert login_res_email.access_token is not None
    assert login_res_email.refresh_token is not None
    assert login_res_email.token_type.lower() == "bearer"

    # 3. Immediate Login via Username
    login_req_user = UserLoginRequest(
        username_or_email=username,
        password=password
    )
    login_res_user = login_user(login_req_user)
    assert login_res_user.access_token is not None
    assert login_res_user.refresh_token is not None

    # Cleanup
    users_collection.delete_one({"email": email})
