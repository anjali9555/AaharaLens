import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Tuple
from loguru import logger
from src.schemas.nutrition_schemas import (
    MealPlanRequest, MealPlanResponse, DayMealPlan, SingleMealDetail
)
from src.services.ai_service import ai_service
from src.services.nutrition_service import NutritionCalculationService
from src.services.allergen_service import AllergenValidationService
from src.repositories.database import meal_plans_collection, profiles_collection

class MealPlannerService:
    """Intelligent meal planning engine generating balanced Indian & global plans with strict allergen safety."""

    @staticmethod
    def _expand_allergens(allergies: List[str]) -> List[str]:
        """Backward-compatible alias delegating to centralized AllergenValidationService."""
        return list(AllergenValidationService.expand_allergens(allergies))

    @staticmethod
    def _sanitize_meal_allergens(meal: SingleMealDetail, allergies: List[str]) -> Tuple[SingleMealDetail, bool]:
        """Backward-compatible alias delegating to centralized AllergenValidationService."""
        return AllergenValidationService.sanitize_meal_plan_item(meal, allergies, "vegetarian")

    @classmethod
    def generate_plan(cls, user_id: str, request: MealPlanRequest) -> MealPlanResponse:
        cals = request.custom_calories or 2000.0
        diet_pref = request.dietary_preference or "vegetarian"
        allergies_list = [a.strip() for a in request.allergies if a.strip()] if request.allergies else []
        allergens_str = ", ".join(allergies_list) if allergies_list else "None"
        cuisine = request.focus_cuisine or "Indian"
        days_count = min(7, max(1, request.duration_days))

        system_prompt = f"""You are a master clinical dietitian and culinary planner specializing in {cuisine} cuisine.
Create a personalized meal plan for {days_count} day(s).
Target Daily Calorie Budget: approximately {cals} kcal per day.
Dietary Preference: {diet_pref}.
Strict Allergies to AVOID AT ALL COSTS: {allergens_str}.
Budget friendly: {request.budget_friendly}.

For EACH day, provide:
1. Breakfast (approx 25% cals)
2. Lunch (approx 35% cals)
3. Dinner (approx 30% cals)
4. Snack (approx 10% cals)
Each meal must specify: dish_name, portion_size, calories, protein_g, carbs_g, fat_g, fiber_g, key_ingredients, why_recommended, and affordable_substitute.

Also compile a consolidated grocery shopping list categorized into:
- produce (fresh vegetables & fruits)
- grains_and_staples (flour, rice, oats, lentils)
- proteins_and_dairy (paneer, tofu, milk, eggs/chicken if non-veg)
- pantry_and_spices

CRITICAL RULE: NEVER include any allergen listed ({allergens_str}).

Respond ONLY in valid JSON matching this structure:
{{
  "days": [
    {{
      "day_number": 1,
      "day_name": "Day 1",
      "breakfast": {{
        "dish_name": "Vegetable Poha with Roasted Peanuts",
        "portion_size": "1 large bowl (200g)",
        "calories": 320.0,
        "protein_g": 8.0,
        "carbs_g": 52.0,
        "fat_g": 9.0,
        "fiber_g": 4.5,
        "key_ingredients": ["Flattened rice", "Peanuts", "Onions", "Green peas"],
        "why_recommended": "Iron-rich, easy to digest, and delivers sustained morning energy.",
        "affordable_substitute": "Vegetable Dalia or Sooji Upma"
      }},
      "lunch": {{ ... }},
      "dinner": {{ ... }},
      "snack": {{ ... }}
    }}
  ],
  "grocery_list": {{
    "produce": ["Spinach", "Tomatoes", "Onions", "Coriander", "Lemon"],
    "grains_and_staples": ["Whole Wheat Atta", "Brown Rice", "Moong Dal"],
    "proteins_and_dairy": ["Low-fat Paneer", "Fresh Curd"],
    "pantry_and_spices": ["Turmeric", "Cumin seeds", "Mustard oil"]
  }},
  "nutritionist_notes": "Hydrate with at least 2.5L water daily."
}}"""

        raw = ai_service._call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate {days_count}-day {cuisine} meal plan for {cals} kcal/day ({diet_pref})."}
        ], json_mode=True, max_tokens=3000)

        daily_plans: List[DayMealPlan] = []
        grocery_list: Dict[str, List[str]] = {
            "produce": ["Tomatoes", "Onions", "Spinach", "Carrots", "Lemon"],
            "grains_and_staples": ["Brown rice", "Toor dal", "Yellow moong dal", "Rolled oats"],
            "proteins_and_dairy": ["Low-fat Paneer / Tofu", "Curd / Dahi"],
            "pantry_and_spices": ["Cumin", "Turmeric", "Cold-pressed oil"]
        }
        notes = "Follow balanced macro distribution and hydrate adequately."

        if raw:
            try:
                parsed = json.loads(raw)
                days_data = parsed.get("days", [])
                for d in days_data:
                    b = SingleMealDetail(meal_type="breakfast", **d["breakfast"])
                    l = SingleMealDetail(meal_type="lunch", **d["lunch"])
                    dn = SingleMealDetail(meal_type="dinner", **d["dinner"])
                    s = SingleMealDetail(meal_type="snack", **d["snack"])
                    
                    # Deterministic post-generation allergen sanitization via centralized service
                    b, _ = AllergenValidationService.sanitize_meal_plan_item(b, allergies_list, diet_pref)
                    l, _ = AllergenValidationService.sanitize_meal_plan_item(l, allergies_list, diet_pref)
                    dn, _ = AllergenValidationService.sanitize_meal_plan_item(dn, allergies_list, diet_pref)
                    s, _ = AllergenValidationService.sanitize_meal_plan_item(s, allergies_list, diet_pref)
                    
                    tot_c = b.calories + l.calories + dn.calories + s.calories
                    tot_p = b.protein_g + l.protein_g + dn.protein_g + s.protein_g
                    tot_cb = b.carbs_g + l.carbs_g + dn.carbs_g + s.carbs_g
                    tot_f = b.fat_g + l.fat_g + dn.fat_g + s.fat_g
                    
                    daily_plans.append(DayMealPlan(
                        day_number=d.get("day_number", len(daily_plans) + 1),
                        day_name=d.get("day_name", f"Day {len(daily_plans) + 1}"),
                        breakfast=b,
                        lunch=l,
                        dinner=dn,
                        snack=s,
                        total_calories=round(tot_c, 1),
                        total_protein=round(tot_p, 1),
                        total_carbs=round(tot_cb, 1),
                        total_fat=round(tot_f, 1)
                    ))
                if "grocery_list" in parsed:
                    grocery_list = parsed["grocery_list"]
                if "nutritionist_notes" in parsed:
                    notes = parsed["nutritionist_notes"]
            except Exception as e:
                logger.error(f"Error parsing meal planner json: {e}")

        # Deterministic fallback plan if LLM generation failed
        if not daily_plans:
            for day_idx in range(1, days_count + 1):
                b = AllergenValidationService.get_allergen_safe_fallback("breakfast", allergies_list, diet_pref)
                l = AllergenValidationService.get_allergen_safe_fallback("lunch", allergies_list, diet_pref)
                dn = AllergenValidationService.get_allergen_safe_fallback("dinner", allergies_list, diet_pref)
                s = AllergenValidationService.get_allergen_safe_fallback("snack", allergies_list, diet_pref)

                tot_c = b.calories + l.calories + dn.calories + s.calories
                tot_p = b.protein_g + l.protein_g + dn.protein_g + s.protein_g
                tot_cb = b.carbs_g + l.carbs_g + dn.carbs_g + s.carbs_g
                tot_f = b.fat_g + l.fat_g + dn.fat_g + s.fat_g

                daily_plans.append(DayMealPlan(
                    day_number=day_idx,
                    day_name=f"Day {day_idx}",
                    breakfast=b,
                    lunch=l,
                    dinner=dn,
                    snack=s,
                    total_calories=round(tot_c, 1),
                    total_protein=round(tot_p, 1),
                    total_carbs=round(tot_cb, 1),
                    total_fat=round(tot_f, 1)
                ))

        # Filter grocery shopping list using centralized allergen service
        cleaned_grocery, _ = AllergenValidationService.filter_grocery_list(grocery_list, allergies_list)
        disclaimer = AllergenValidationService.get_cross_contamination_disclaimer()
        full_notes = f"{notes} {disclaimer}".strip()

        plan_id = str(uuid.uuid4())
        plan_doc = {
            "id": plan_id,
            "user_id": user_id,
            "duration_days": days_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "daily_plans": [d.model_dump() for d in daily_plans],
            "grocery_shopping_list": cleaned_grocery,
            "nutritionist_notes": full_notes,
            "allergies": allergies_list,
            "dietary_preference": diet_pref
        }
        meal_plans_collection.insert_one(plan_doc)

        return MealPlanResponse(
            id=plan_id,
            user_id=user_id,
            duration_days=days_count,
            created_at=plan_doc["created_at"],
            daily_plans=daily_plans,
            grocery_shopping_list=cleaned_grocery,
            nutritionist_notes=full_notes
        )

    @staticmethod
    def regenerate_single_meal(
        user_id: str,
        plan_id: str,
        day_number: int,
        meal_type: str,
        reason: Optional[str] = None
    ) -> Optional[SingleMealDetail]:
        """
        Regenerates a single meal inside an existing plan, rigorously validating
        the replacement dish against the user's recorded allergies and dietary preference.
        """
        plan_doc = meal_plans_collection.find_one({"id": plan_id, "user_id": user_id})
        if not plan_doc:
            return None

        # Retrieve user allergies from plan or user profile
        allergies = plan_doc.get("allergies", [])
        if not allergies and user_id:
            user_prof = profiles_collection.find_one({"user_id": user_id})
            if user_prof and "profile" in user_prof:
                allergies = user_prof["profile"].get("allergies", [])
        diet_pref = plan_doc.get("dietary_preference", "vegetarian")
        allergens_str = ", ".join(allergies) if allergies else "None"

        prompt = (
            f"Generate a replacement {meal_type} meal for an Indian nutrition plan ({diet_pref}). "
            f"Reason for replacement: {reason or 'Variety'}. "
            f"STRICT ALLERGIES TO AVOID: {allergens_str}. "
            "Provide dish_name, portion_size, calories, protein_g, carbs_g, fat_g, fiber_g, key_ingredients, why_recommended, affordable_substitute."
        )

        system_prompt = f"""Respond ONLY in valid JSON matching:
{{
  "dish_name": "Tofu & Vegetable Stir Fry",
  "portion_size": "1 bowl (200g)",
  "calories": 280.0,
  "protein_g": 18.0,
  "carbs_g": 16.0,
  "fat_g": 14.0,
  "fiber_g": 5.0,
  "key_ingredients": ["Tofu", "Broccoli", "Soy sauce", "Sesame"],
  "why_recommended": "High protein vegan alternative.",
  "affordable_substitute": "Soy chunk curry with brown rice"
}}
CRITICAL: Do NOT include any of these allergens: {allergens_str}."""

        raw = ai_service._call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ], json_mode=True)

        new_meal: Optional[SingleMealDetail] = None
        if raw:
            try:
                data = json.loads(raw)
                candidate = SingleMealDetail(meal_type=meal_type, **data)
                # Rigorously sanitize against allergies
                candidate, _ = AllergenValidationService.sanitize_meal_plan_item(candidate, allergies, diet_pref)
                new_meal = candidate
            except Exception as e:
                logger.error(f"Error parsing regenerated meal json: {e}")

        # If LLM generation failed or was invalid, generate verified allergen-safe fallback
        if not new_meal:
            new_meal = AllergenValidationService.get_allergen_safe_fallback(meal_type, allergies, diet_pref)

        # Update in plan and database
        days = plan_doc.get("daily_plans", [])
        for d in days:
            if d.get("day_number") == day_number:
                d[meal_type] = new_meal.model_dump()
                # Recalculate daily totals
                b = d.get("breakfast", {})
                l = d.get("lunch", {})
                dn = d.get("dinner", {})
                s = d.get("snack", {})
                d["total_calories"] = round(sum(m.get("calories", 0) for m in [b, l, dn, s]), 1)
                d["total_protein"] = round(sum(m.get("protein_g", 0) for m in [b, l, dn, s]), 1)
                d["total_carbs"] = round(sum(m.get("carbs_g", 0) for m in [b, l, dn, s]), 1)
                d["total_fat"] = round(sum(m.get("fat_g", 0) for m in [b, l, dn, s]), 1)
                break

        meal_plans_collection.update_one({"id": plan_id}, {"daily_plans": days})
        return new_meal
