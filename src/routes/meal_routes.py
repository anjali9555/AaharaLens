from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, status
from src.schemas.nutrition_schemas import (
    MealEntryCreate, MealEntryResponse, DailyDashboardResponse, WeeklyNutritionReport
)
from src.routes.deps import get_current_user
from src.services.meal_service import meal_service

router = APIRouter(prefix="/meals", tags=["Meal Tracking & Dashboard"])

@router.post("", response_model=MealEntryResponse, status_code=status.HTTP_201_CREATED)
def log_meal(entry: MealEntryCreate, current_user: dict = Depends(get_current_user)):
    """Logs breakfast, lunch, dinner, or snacks to user's daily diary."""
    return meal_service.create_meal_entry(current_user["id"], entry)

@router.get("", response_model=List[MealEntryResponse])
def get_meals(
    date: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Retrieves paginated meal history for current authenticated user."""
    return meal_service.list_user_meals(current_user["id"], date_filter=date, skip=int(skip), limit=int(limit))

@router.put("/{meal_id}", response_model=MealEntryResponse)
def update_meal(meal_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    """Updates an existing meal entry (e.g. adjust portion size or food name)."""
    updated = meal_service.update_meal_entry(current_user["id"], meal_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Meal entry not found or unauthorized.")
    return updated

@router.delete("/{meal_id}", status_code=status.HTTP_200_OK)
def delete_meal(meal_id: str, current_user: dict = Depends(get_current_user)):
    """Removes a meal entry from the user's diary."""
    success = meal_service.delete_meal_entry(current_user["id"], meal_id)
    if not success:
        raise HTTPException(status_code=404, detail="Meal entry not found or unauthorized.")
    return {"status": "success", "message": "Meal entry deleted successfully."}

@router.get("/dashboard", response_model=DailyDashboardResponse)
@router.get("/dashboard/{date_str}", response_model=DailyDashboardResponse)
def get_daily_dashboard(date_str: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Fetches full daily nutrition dashboard with targets, consumed macros, and AI next-meal decision."""
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    return meal_service.get_daily_dashboard(current_user["id"], target_date)

@router.get("/weekly-report", response_model=WeeklyNutritionReport)
def get_weekly_nutrition_report(
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Generates personalized 7-day nutritional intelligence report with trends, strengths, and AI tips."""
    return meal_service.get_weekly_report(current_user["id"], end_date)
