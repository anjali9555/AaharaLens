import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "AaharaLens — Multimodal AI Personalized Nutrition Platform"
    VERSION: str = "2.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # AI / LLM Configuration
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    GROQ_VISION_MODEL: str = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    FALLBACK_MODELS: list = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]

    # Security & Auth
    # Production enforces non-default SECRET_KEY
    _default_secret = "dev-secret-key-nutrition-platform-2026-minimum-32-chars"
    SECRET_KEY: str = os.getenv("SECRET_KEY", _default_secret)
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "admin-super-secret-key-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))

    if ENVIRONMENT == "production" and SECRET_KEY == _default_secret:
        raise ValueError("CRITICAL SECURITY ERROR: SECRET_KEY must be set to a secure custom value in production.")

    # Database
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "nutrition_platform_db")
    DB_FALLBACK_DIR: str = os.getenv("DB_FALLBACK_DIR", "data/db_store")
    ALLOW_FALLBACK_IN_PROD: bool = os.getenv("ALLOW_FALLBACK_IN_PROD", "false").lower() == "true"
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # CORS
    _cors_raw = os.getenv("CORS_ORIGINS", "")
    if _cors_raw:
        CORS_ORIGINS: list = [origin.strip() for origin in _cors_raw.split(",") if origin.strip()]
    elif ENVIRONMENT == "production":
        CORS_ORIGINS: list = [
            "http://localhost:8501",
            "http://127.0.0.1:8501"
        ]
    else:
        CORS_ORIGINS: list = [
            "http://localhost:8501",
            "http://127.0.0.1:8501",
            "http://localhost:8000",
            "http://127.0.0.1:8000"
        ]

    # RAG / Storage
    STORAGE_DIR: str = "data/storage"
    KNOWLEDGE_DIR: str = "data/knowledge"

    # Qdrant Vector Database (Windows-Native Persistent Disk / Remote Server)
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "127.0.0.1")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_GRPC_PORT: int = int(os.getenv("QDRANT_GRPC_PORT", "6334"))
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
    QDRANT_STORAGE_DIR: str = os.getenv("QDRANT_STORAGE_DIR", "data/storage/qdrant_data")
    QDRANT_COLLECTION_NAME: str = "nutrition_knowledge"

    # Local FastEmbed BGE-small-en-v1.5 (CPU ONNX Inference - Zero PyTorch/TF)
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")
    EMBEDDING_CACHE_DIR: str = os.getenv("EMBEDDING_CACHE_DIR", "data/storage/models")
    EMBEDDING_DIM: int = 384

    # Advanced Redis Application Caching
    REDIS_CACHE_ENABLED: bool = os.getenv("REDIS_CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL_DEFAULT: int = int(os.getenv("CACHE_TTL_DEFAULT", "3600"))        # 1 hour
    CACHE_TTL_NUTRITION: int = int(os.getenv("CACHE_TTL_NUTRITION", "86400"))   # 24 hours
    CACHE_TTL_RAG: int = int(os.getenv("CACHE_TTL_RAG", "3600"))               # 1 hour
    CACHE_TTL_ANALYTICS: int = int(os.getenv("CACHE_TTL_ANALYTICS", "600"))     # 10 minutes

    # Open Food Facts API & USDA FoodData Central
    OPEN_FOOD_FACTS_URL: str = "https://world.openfoodfacts.org/api/v2/search"
    OPEN_FOOD_FACTS_LEGACY_URL: str = "https://world.openfoodfacts.org/cgi/search.pl"
    USDA_API_URL: str = os.getenv("USDA_API_URL", "https://api.nal.usda.gov/fdc/v1")
    USDA_API_KEY: str = os.getenv("USDA_API_KEY", "")

    # Rate Limiting
    RATE_LIMIT_GENERAL: str = os.getenv("RATE_LIMIT_GENERAL", "100/15minutes")
    RATE_LIMIT_AUTH: str = os.getenv("RATE_LIMIT_AUTH", "10/15minutes")
    RATE_LIMIT_AI: str = os.getenv("RATE_LIMIT_AI", "20/15minutes")
    RATE_LIMIT_IMAGE: str = os.getenv("RATE_LIMIT_IMAGE", "10/15minutes")
    RATE_LIMIT_CHAT: str = os.getenv("RATE_LIMIT_CHAT", "20/15minutes")

settings = Settings()
