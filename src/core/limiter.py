from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from loguru import logger
from src.core.config import settings
from src.core.security import decode_access_token

def rate_limit_key_builder(request: Request) -> str:
    """
    Dynamic rate limiter key:
    If client presents a valid Bearer token, limit by user identity so switching IPs doesn't bypass.
    Otherwise, limit by remote client IP.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split("Bearer ", 1)[1].strip()
        user_id = decode_access_token(token)
        if user_id:
            return f"user:{user_id}"
            
    return get_remote_address(request) or "127.0.0.1"

# Redis storage for distributed rate limiting across backend workers
storage_uri = None
storage_options = {}

if settings.REDIS_URL:
    try:
        import redis
        # Fast 0.5s ping check to ensure Redis is genuinely responsive before configuring SlowAPI storage
        r_client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.5, socket_connect_timeout=0.5)
        r_client.ping()
        storage_uri = settings.REDIS_URL
        storage_options = {
            "socket_timeout": 2.5,
            "socket_connect_timeout": 2.5,
            "retry_on_timeout": True
        }
        logger.info(f"Configuring distributed rate limiter storage via Redis: {storage_uri}")
    except Exception as re:
        if settings.ENVIRONMENT == "production":
            logger.critical(f"FATAL: Redis rate limiting storage failed to respond in production: {re}")
            raise
        logger.warning(f"Redis rate limiter storage unavailable ({re}). Using high-performance memory storage (development mode).")
        storage_uri = None
        storage_options = {}

limiter = Limiter(
    key_func=rate_limit_key_builder,
    default_limits=[settings.RATE_LIMIT_GENERAL],
    storage_uri=storage_uri,
    storage_options=storage_options
)
