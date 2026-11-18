from fastapi import APIRouter, HTTPException, Depends, Request
from src.core.config import settings
from src.core.limiter import limiter
from src.schemas.nutrition_schemas import (
    MealPlanRequest, MealPlanResponse, SingleMealDetail
)
from src.routes.deps import get_current_user
from src.services.meal_planner_service import MealPlannerService
from src.repositories.database import profiles_collection

router = APIRouter(prefix="/planner", tags=["AI Meal Planner"])

@router.post("/generate", response_model=MealPlanResponse)
@limiter.limit(settings.RATE_LIMIT_AI)
def generate_meal_plan(
    req: MealPlanRequest, 
    request: Request = None,
    current_user: dict = Depends(get_current_user)
):
    """Generates personalized 1-day or 7-day Indian meal plan with grocery list & macro targets."""
    user_id = current_user["id"]
    prof_doc = profiles_collection.find_one({"user_id": user_id})
    
    # Pre-populate preferences from user profile if not explicitly overridden
    if prof_doc:
        p = prof_doc.get("profile", {})
        t = prof_doc.get("targets", {})
        if not req.dietary_preference:
            req.dietary_preference = p.get("dietary_preference", "vegetarian")
        if not req.allergies:
            req.allergies = p.get("allergies", [])
        if not req.custom_calories:
            req.custom_calories = t.get("target_calories", 2000.0)

    return MealPlannerService.generate_plan(user_id, req)

@router.post("/regenerate-meal", response_model=SingleMealDetail)
@limiter.limit(settings.RATE_LIMIT_AI)
def regenerate_meal(
    plan_id: str,
    day_number: int,
    meal_type: str,
    request: Request = None,
    reason: str = "Need a different dish",
    current_user: dict = Depends(get_current_user)
):
    """Regenerates a single meal in an existing plan without re-rolling the rest."""
    res = MealPlannerService.regenerate_single_meal(
        user_id=current_user["id"],
        plan_id=plan_id,
        day_number=day_number,
        meal_type=meal_type,
        reason=reason
    )
    if not res:
        raise HTTPException(status_code=404, detail="Could not regenerate meal or plan not found.")
    return res
