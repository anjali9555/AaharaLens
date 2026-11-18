import hmac
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.core.config import settings
from src.core.security import decode_access_token
from src.repositories.database import users_collection

security_bearer = HTTPBearer(auto_error=False)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided or invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user = users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account does not exist or has been deleted.",
        )
    return user

def get_optional_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)) -> Optional[Dict[str, Any]]:
    if not credentials or not credentials.credentials:
        return None
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        return None
    return users_collection.find_one({"id": user_id})

def get_current_admin_user(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_current_user)
) -> Dict[str, Any]:
    """
    Authorizes administrative requests:
    1. Validates X-Admin-API-Key header against configured ADMIN_API_KEY.
    2. OR validates that the authenticated JWT user possesses role='admin' or is_admin=True.
    Raises 403 Forbidden if neither authorization criterion is satisfied.
    """
    # 1. Check API Key header
    admin_header = request.headers.get("X-Admin-API-Key")
    if settings.ADMIN_API_KEY and admin_header:
        if hmac.compare_digest(admin_header.strip(), settings.ADMIN_API_KEY.strip()):
            return {"id": "admin-system", "username": "admin", "role": "admin", "is_admin": True}

    # 2. Check JWT user claims
    if current_user:
        if current_user.get("role") == "admin" or current_user.get("is_admin") is True:
            return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrative privileges required to perform this operation."
    )
