import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from loguru import logger

from src.core.config import settings
from src.core.limiter import limiter
from src.routes.auth_routes import router as auth_router
from src.routes.profile_routes import router as profile_router
from src.routes.food_routes import router as food_router
from src.routes.meal_routes import router as meal_router
from src.routes.planner_routes import router as planner_router
from src.routes.chat_routes import router as chat_router

from src.services.nutrition_service import NutritionCalculationService
from src.services.rag_service import rag_service
from src.repositories.database import check_database_health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan Context Manager:
    Manages single-owner application resources, warms up local Qdrant persistence,
    and guarantees graceful shutdown to release all storage locks.
    """
    logger.info("Initializing AaharaLens backend application (Windows-native)...")
    try:
        rag_service.ensure_ready()
    except Exception as e:
        logger.warning(f"RAG service warmup warning: {e}")
    
    yield

    logger.info("Gracefully shutting down AaharaLens backend application...")
    try:
        rag_service.close()
    except Exception as e:
        logger.warning(f"Error during RAG service shutdown: {e}")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Production-grade AI nutrition analysis, multimodal food recognition, personalized meal planning, and RAG knowledge platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Attach SlowAPI Rate Limiter
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Production-hardened HTTP 429 handler.
    Guarantees standard RFC 6585 response with Retry-After header regardless of internal state variations.
    """
    view_rate_limit = getattr(request.state, "view_rate_limit", None)
    retry_after = 60
    if view_rate_limit and isinstance(view_rate_limit, (tuple, list)) and len(view_rate_limit) > 0:
        lim_item = view_rate_limit[0]
        try:
            if hasattr(lim_item, "get_expiry"):
                retry_after = max(1, int(lim_item.get_expiry()))
            elif hasattr(lim_item, "amount"):
                retry_after = max(1, int(getattr(lim_item, "get_expiry", lambda: 60)()))
        except Exception:
            retry_after = 60

    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {exc.detail}",
            "status_code": 429,
            "retry_after": retry_after
        },
        headers={"Retry-After": str(retry_after)}
    )

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Timing Middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = (time.time() - start_time) * 1000
    response.headers["x-process-time-ms"] = f"{duration:.2f}"
    return response

TimingASGIMiddleware = add_process_time_header

# Centralized Exception Handler
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code}
    )

# Routers Mounting
api_v1_prefix = settings.API_V1_STR
app.include_router(auth_router, prefix=api_v1_prefix)
app.include_router(profile_router, prefix=api_v1_prefix)
app.include_router(food_router, prefix=api_v1_prefix)
app.include_router(meal_router, prefix=api_v1_prefix)
app.include_router(planner_router, prefix=api_v1_prefix)
app.include_router(chat_router, prefix=api_v1_prefix)

# Health Check Endpoints
@app.get("/", tags=["Health"])
def root():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/health", tags=["Health"])
@app.get(f"{api_v1_prefix}/health", tags=["Health"])
def health_check():
    from src.services.cache_service import cache_service
    db_health = check_database_health()
    rag_health = rag_service.get_health_status()
    cache_diag = cache_service.get_diagnostics()

    return {
        "status": "healthy",
        "service": "AaharaLens API",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "runtime": "Windows-Native",
        "groq_configured": bool(settings.GROQ_API_KEY),
        "groq_model": settings.GROQ_MODEL,
        "rate_limiting": "active",
        "storage": "operational",
        "database": db_health,
        "vector_db": rag_health,
        "rag": rag_health,
        "cache": cache_diag,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ================= BACKWARD COMPATIBILITY ENDPOINTS =================
# Preserves backward compatibility with legacy app endpoints
@app.get("/analyze/{food_item}", tags=["Legacy Endpoints"])
def legacy_analyze_food(food_item: str):
    """Legacy GET endpoint for single food analysis."""
    detail = NutritionCalculationService.calculate_food_nutrition(food_item)
    return {
        "food": food_item,
        "data": {
            "protein": detail.protein,
            "fat": detail.total_fat,
            "carbohydrates": detail.carbohydrates,
            "fiber": detail.dietary_fiber,
            "health_score": detail.health_score,
            "suggested_pairing": detail.suggested_pairing or "Salad & Water",
            "explanation": detail.explanation
        }
    }

@app.get("/ask/{question}", tags=["Legacy Endpoints"])
def legacy_ask_question(question: str):
    """Legacy GET endpoint for RAG queries."""
    result = rag_service.answer_query(question=question)
    return {
        "question": question,
        "answer": result.answer,
        "sources": result.sources
    }
