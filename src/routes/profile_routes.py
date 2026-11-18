from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from src.schemas.nutrition_schemas import (
    ProfileUpdateRequest, ProfileResponse, CalculatedTargets
)
from src.routes.deps import get_current_user
from src.repositories.database import profiles_collection
from src.services.nutrition_service import NutritionCalculationService

router = APIRouter(prefix="/profile", tags=["User Profile"])

@router.get("", response_model=ProfileResponse)
def get_user_profile(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    prof_doc = profiles_collection.find_one({"user_id": user_id})
    if not prof_doc:
        # Generate default
        targets = NutritionCalculationService.calculate_personalized_targets(
            age=25, gender="male", height_cm=172.0, weight_kg=68.0,
            activity_level="moderate", fitness_goal="maintenance"
        )
        default_req = ProfileUpdateRequest(
            age=25, gender="male", height_cm=172.0, weight_kg=68.0,
            activity_level="moderate", dietary_preference="vegetarian",
            fitness_goal="maintenance"
        )
        prof_doc = {
            "user_id": user_id,
            "profile": default_req.model_dump(),
            "targets": targets.model_dump(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        profiles_collection.insert_one(prof_doc)

    return ProfileResponse(
        user_id=user_id,
        profile=ProfileUpdateRequest(**prof_doc["profile"]),
        targets=CalculatedTargets(**prof_doc["targets"]),
        updated_at=prof_doc["updated_at"]
    )

@router.put("", response_model=ProfileResponse)
def update_user_profile(req: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    
    # Calculate updated targets using Mifflin-St Jeor validated clinical standard
    targets = NutritionCalculationService.calculate_personalized_targets(
        age=req.age,
        gender=req.gender,
        height_cm=req.height_cm,
        weight_kg=req.weight_kg,
        activity_level=req.activity_level,
        fitness_goal=req.fitness_goal,
        custom_calories=req.custom_calorie_target
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    updated_doc = {
        "user_id": user_id,
        "profile": req.model_dump(),
        "targets": targets.model_dump(),
        "updated_at": now_iso
    }

    if profiles_collection.find_one({"user_id": user_id}):
        profiles_collection.update_one({"user_id": user_id}, updated_doc)
    else:
        profiles_collection.insert_one(updated_doc)

    return ProfileResponse(
        user_id=user_id,
        profile=req,
        targets=targets,
        updated_at=now_iso
    )
