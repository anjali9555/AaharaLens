import io
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request, status
from PIL import Image
from loguru import logger
from src.core.config import settings
from src.core.limiter import limiter
from src.schemas.nutrition_schemas import (
    TextFoodAnalysisRequest, MultiFoodAnalysisResponse,
    LabelScannerResponse, FoodComparisonRequest, FoodComparisonResponse,
    FoodSubstitutionRequest, FoodSubstitutionResponse,
    RecipeGeneratorRequest, RecipeGeneratorResponse
)
from src.services.ai_service import ai_service
from src.routes.deps import get_optional_current_user
from src.repositories.database import food_analysis_collection

router = APIRouter(prefix="/food", tags=["Multimodal Food Intelligence"])

# Image validation constraints
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024 # 10 MB
ALLOWED_MIME_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]

def validate_image_upload(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file.content_type}'. Please upload JPG, PNG or WEBP images."
        )
    content = file.file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size exceeds maximum limit of 10 MB."
        )
    try:
        # Validate that image is intact and not corrupted
        image = Image.open(io.BytesIO(content))
        image.verify()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is corrupted or not a valid image."
        )
    return content

@router.post("/analyze-text", response_model=MultiFoodAnalysisResponse)
@limiter.limit(settings.RATE_LIMIT_AI)
def analyze_food_text(
    req: TextFoodAnalysisRequest, 
    request: Request = None,
    user: Optional[dict] = Depends(get_optional_current_user)
):
    """Analyzes single or multi-item food text descriptions (e.g. '2 rotis and 1 bowl dal tadka')."""
    if not req.food_query.strip():
        raise HTTPException(status_code=400, detail="Food query cannot be empty.")
    
    result = ai_service.analyze_food_text(req.food_query, req.portion_hint)
    
    # Store in history if user is logged in
    if user:
        food_analysis_collection.insert_one({
            "user_id": user["id"],
            "type": "text",
            "query": req.food_query,
            "result": result.model_dump()
        })
        
    return result

@router.post("/analyze-image", response_model=MultiFoodAnalysisResponse)
@limiter.limit(settings.RATE_LIMIT_IMAGE)
async def analyze_food_image(
    file: UploadFile = File(...),
    request: Request = None,
    portion_hint: Optional[str] = Form(None),
    user: Optional[dict] = Depends(get_optional_current_user)
):
    """Multimodal vision recognition for food plates, bowls, and meal photos."""
    content = validate_image_upload(file)
    try:
        result = ai_service.analyze_food_image(content, file.content_type)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Image analysis failure: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Vision recognition service is currently unavailable or encountered an unexpected processing error."
        )
    
    if user:
        food_analysis_collection.insert_one({
            "user_id": user["id"],
            "type": "image",
            "filename": file.filename,
            "result": result.model_dump()
        })
        
    return result

@router.post("/scan-label", response_model=LabelScannerResponse)
@limiter.limit(settings.RATE_LIMIT_IMAGE)
async def scan_packaged_label(file: UploadFile = File(...), request: Request = None):
    """Extracts and verifies packaged nutrition facts labels using Vision AI."""
    content = validate_image_upload(file)
    result = ai_service.scan_food_label(content, file.content_type)
    return result

@router.post("/compare", response_model=FoodComparisonResponse)
@limiter.limit(settings.RATE_LIMIT_AI)
def compare_foods(req: FoodComparisonRequest, request: Request = None):
    """Head-to-head nutritional comparison of two foods using verified databases."""
    if not req.food_a.strip() or not req.food_b.strip():
        raise HTTPException(status_code=400, detail="Both food names must be provided.")
    return ai_service.compare_foods(req.food_a, req.food_b, req.serving_a or "100g", req.serving_b or "100g")

@router.post("/substitute", response_model=FoodSubstitutionResponse)
@limiter.limit(settings.RATE_LIMIT_AI)
def suggest_substitution(req: FoodSubstitutionRequest, request: Request = None):
    """Recommends healthier food substitutes tailored to a specific dietary goal."""
    return ai_service.suggest_substitutions(req.food_name, req.goal_or_reason)

@router.post("/recipe-generator", response_model=RecipeGeneratorResponse)
@limiter.limit(settings.RATE_LIMIT_AI)
def generate_leftover_recipes(req: RecipeGeneratorRequest, request: Request = None):
    """Generates nutritious recipes with macros from available kitchen ingredients."""
    if not req.ingredients:
        raise HTTPException(status_code=400, detail="Please provide at least one available ingredient.")
    return ai_service.generate_leftover_recipes(
        ingredients=req.ingredients,
        dietary_preference=req.dietary_preference or "vegetarian",
        fitness_goal=req.fitness_goal or "healthy"
    )
