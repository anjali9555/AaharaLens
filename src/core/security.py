import os
import re
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Tuple
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash
from src.core.config import settings

# Initialize Argon2id hasher with secure RFC 9106 recommended parameters
# Uses 19MB in development/testing (RFC 9106 recommended first profile) and 64MB in production
_argon_memory = 65536 if settings.ENVIRONMENT == "production" and not os.getenv("TESTING") else 19456

_ph = PasswordHasher(
    time_cost=2,
    memory_cost=_argon_memory,
    parallelism=1,
    hash_len=32,
    salt_len=16
)

def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """Enforces minimum 8 chars, at least one letter, and at least one digit or special symbol."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter."
    if not re.search(r'[\d!@#$%^&*()_+\-=\[\]{}|;:,.<>?]', password):
        return False, "Password must contain at least one number or special character."
    return True, None

def hash_password(password: str) -> str:
    """Argon2id password hashing (OWASP recommended gold standard)."""
    return _ph.hash(password)

def _verify_pbkdf2_legacy(plain_password: str, hashed_password: str) -> bool:
    """Backward compatibility verifier for legacy PBKDF2-HMAC-SHA256 hashes."""
    try:
        if "$" not in hashed_password:
            return False
        salt, expected_key = hashed_password.split("$", 1)
        actual_key = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        return hmac.compare_digest(actual_key, expected_key)
    except Exception:
        return False

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plain password against Argon2id or legacy PBKDF2 hash."""
    if not hashed_password or not plain_password:
        return False
        
    # Check if Argon2id format
    if hashed_password.startswith("$argon2"):
        try:
            return _ph.verify(hashed_password, plain_password)
        except (VerifyMismatchError, VerificationError, InvalidHash):
            return False
        except Exception:
            return False
            
    # Legacy PBKDF2 fallback
    return _verify_pbkdf2_legacy(plain_password, hashed_password)

def verify_and_check_rehash(plain_password: str, hashed_password: str) -> Tuple[bool, bool]:
    """
    Returns (is_valid, needs_rehash).
    If True, needs_rehash indicates the password was in legacy format (or deprecated Argon2 parameters)
    and should be rehashed to current Argon2id settings upon successful authentication.
    """
    if not hashed_password or not plain_password:
        return False, False

    if hashed_password.startswith("$argon2"):
        try:
            is_valid = _ph.verify(hashed_password, plain_password)
            needs_rehash = _ph.check_needs_rehash(hashed_password)
            return is_valid, needs_rehash
        except Exception:
            return False, False

    # Legacy PBKDF2 verification
    if _verify_pbkdf2_legacy(plain_password, hashed_password):
        return True, True  # Valid, but needs upgrade to Argon2id
        
    return False, False

def hash_token(raw_token: str) -> str:
    """Cryptographic SHA-256 hash for storing refresh tokens securely in database."""
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

def create_access_token(subject: str | Any, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_refresh_token(subject: str | Any) -> Tuple[str, str, datetime]:
    """
    Generates a cryptographically strong refresh token.
    Returns: (raw_token, token_hash, expires_at_datetime)
    """
    raw_token = f"rt_{secrets.token_urlsafe(48)}"
    token_h = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return raw_token, token_h, expires_at

def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") and payload.get("type") != "access":
            return None
        return payload.get("sub")
    except Exception:
        return None
