import uuid
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional
from collections import Counter
from loguru import logger
from src.schemas.nutrition_schemas import (
    MealEntryCreate, MealEntryResponse, DailyDashboardResponse, WeeklyNutritionReport
)
from src.repositories.database import meal_entries_collection, profiles_collection
from src.services.ai_service import ai_service
from src.services.nutrition_service import NutritionCalculationService

class MealService:
    """Manages meal logging, daily dashboard adherence, and weekly nutrition intelligence."""

    @staticmethod
    def create_meal_entry(user_id: str, entry: MealEntryCreate) -> MealEntryResponse:
        # Check duplicate
        existing = meal_entries_collection.find_one({
            "user_id": user_id,
            "date": entry.date,
            "meal_type": entry.meal_type.lower(),
            "food_name": entry.food_name
        })
        
        entry_id = str(uuid.uuid4())
        doc = {
            "id": entry_id,
            "user_id": user_id,
            "date": entry.date,
            "meal_type": entry.meal_type.lower(),
            "food_name": entry.food_name,
            "serving_size": entry.serving_size,
            "serving_weight_g": entry.serving_weight_g,
            "calories": round(entry.calories, 1),
            "protein": round(entry.protein, 1),
            "carbohydrates": round(entry.carbohydrates, 1),
            "fat": round(entry.fat, 1),
            "fiber": round(entry.fiber, 1),
            "notes": entry.notes,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        meal_entries_collection.insert_one(doc)
        from src.services.cache_service import cache_service
        cache_service.invalidate_user_cache(user_id)
        return MealEntryResponse(**doc)

    @staticmethod
    def list_user_meals(user_id: str, date_filter: Optional[str] = None, limit: int = 50, skip: int = 0) -> List[MealEntryResponse]:
        query = {"user_id": user_id}
        if date_filter:
            query["date"] = date_filter
        docs = meal_entries_collection.find_many(query, skip=skip, limit=limit, sort_by="created_at", reverse=True)
        return [MealEntryResponse(**d) for d in docs]

    @staticmethod
    def update_meal_entry(user_id: str, meal_id: str, update_fields: Dict[str, Any]) -> Optional[MealEntryResponse]:
        doc = meal_entries_collection.find_one({"id": meal_id, "user_id": user_id})
        if not doc:
            return None
            
        allowed = ["food_name", "serving_size", "serving_weight_g", "calories", "protein", "carbohydrates", "fat", "fiber", "notes"]
        clean_update = {k: v for k, v in update_fields.items() if k in allowed and v is not None}
        
        meal_entries_collection.update_one({"id": meal_id}, clean_update)
        from src.services.cache_service import cache_service
        cache_service.invalidate_user_cache(user_id)
        doc.update(clean_update)
        return MealEntryResponse(**doc)

    @staticmethod
    def delete_meal_entry(user_id: str, meal_id: str) -> bool:
        deleted = meal_entries_collection.delete_one({"id": meal_id, "user_id": user_id})
        if deleted:
            from src.services.cache_service import cache_service
            cache_service.invalidate_user_cache(user_id)
        return deleted

    @staticmethod
    def get_daily_dashboard(user_id: str, target_date: str) -> DailyDashboardResponse:
        # Fetch targets from profile
        prof = profiles_collection.find_one({"user_id": user_id})
        targ = prof.get("targets", {}) if prof else {}
        t_cal = targ.get("target_calories", 2000.0)
        t_prot = targ.get("target_protein_g", 75.0)
        t_carbs = targ.get("target_carbs_g", 250.0)
        t_fat = targ.get("target_fat_g", 55.0)
        t_fib = targ.get("target_fiber_g", 28.0)

        # Fetch meals for date
        meals = meal_entries_collection.find_many({"user_id": user_id, "date": target_date}, limit=100)
        
        by_type: Dict[str, List[MealEntryResponse]] = {
            "breakfast": [],
            "lunch": [],
            "dinner": [],
            "snacks": []
        }

        c_cal = 0.0
        c_prot = 0.0
        c_carbs = 0.0
        c_fat = 0.0
        c_fib = 0.0

        for m in meals:
            m_resp = MealEntryResponse(**m)
            m_type = m.get("meal_type", "snacks").lower()
            if m_type not in by_type:
                by_type[m_type] = []
            by_type[m_type].append(m_resp)

            c_cal += m_resp.calories
            c_prot += m_resp.protein
            c_carbs += m_resp.carbohydrates
            c_fat += m_resp.fat
            c_fib += m_resp.fiber

        r_cal = max(0.0, round(t_cal - c_cal, 1))
        r_prot = max(0.0, round(t_prot - c_prot, 1))

        cal_adherence = round((c_cal / max(1.0, t_cal)) * 100, 1)
        prot_adherence = round((c_prot / max(1.0, t_prot)) * 100, 1)

        # AI Next Meal Decision
        ai_suggestion = None
        if meals:
            diet_pref = prof.get("profile", {}).get("dietary_preference", "vegetarian") if prof else "vegetarian"
            ai_suggestion = ai_service.decide_next_meal(
                target_calories=t_cal,
                consumed_calories=c_cal,
                target_protein=t_prot,
                consumed_protein=c_prot,
                target_carbs=t_carbs,
                consumed_carbs=c_carbs,
                dietary_pref=diet_pref
            )

        return DailyDashboardResponse(
            date=target_date,
            target_calories=round(t_cal, 1),
            consumed_calories=round(c_cal, 1),
            remaining_calories=r_cal,
            target_protein=round(t_prot, 1),
            consumed_protein=round(c_prot, 1),
            remaining_protein=r_prot,
            target_carbs=round(t_carbs, 1),
            consumed_carbs=round(c_carbs, 1),
            target_fat=round(t_fat, 1),
            consumed_fat=round(c_fat, 1),
            target_fiber=round(t_fib, 1),
            consumed_fiber=round(c_fib, 1),
            meals_by_type=by_type,
            calorie_adherence_percent=cal_adherence,
            protein_adherence_percent=prot_adherence,
            ai_meal_decision=ai_suggestion
        )

    @staticmethod
    def get_weekly_report(user_id: str, end_date_str: Optional[str] = None) -> WeeklyNutritionReport:
        from src.services.cache_service import cache_service
        if not end_date_str:
            end_date_str = datetime.now().strftime("%Y-%m-%d")

        # Check analytics cache
        cache_key = f"weekly_report:{end_date_str}"
        cached = cache_service.get_cached_analytics(user_id, cache_key)
        if cached:
            return WeeklyNutritionReport(**cached)
        
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=6)
        start_date_str = start_dt.strftime("%Y-%m-%d")

        # Targeted MongoDB aggregation filter
        pipeline = [
            {"$match": {"user_id": user_id, "date": {"$gte": start_date_str, "$lte": end_date_str}}},
            {"$sort": {"date": 1}}
        ]
        week_meals = meal_entries_collection.aggregate(pipeline)

        tot_cal = sum(m.get("calories", 0) for m in week_meals)
        tot_prot = sum(m.get("protein", 0) for m in week_meals)
        tot_carbs = sum(m.get("carbohydrates", 0) for m in week_meals)
        tot_fat = sum(m.get("fat", 0) for m in week_meals)

        days_count = 7
        avg_cal = round(tot_cal / days_count, 1)
        avg_prot = round(tot_prot / days_count, 1)
        avg_carbs = round(tot_carbs / days_count, 1)
        avg_fat = round(tot_fat / days_count, 1)

        # Macro percentage
        cals_from_p = avg_prot * 4
        cals_from_c = avg_carbs * 4
        cals_from_f = avg_fat * 9
        total_macro_cals = max(1.0, cals_from_p + cals_from_c + cals_from_f)

        macro_split = {
            "protein_percent": round((cals_from_p / total_macro_cals) * 100, 1),
            "carbs_percent": round((cals_from_c / total_macro_cals) * 100, 1),
            "fat_percent": round((cals_from_f / total_macro_cals) * 100, 1)
        }

        # Most frequent foods
        foods_counter = Counter([m.get("food_name", "").title() for m in week_meals if m.get("food_name")])
        top_foods = [{"food": f, "frequency": count} for f, count in foods_counter.most_common(5)]

        # AI-derived clinical trends
        trends = []
        strengths = []
        improvements = []
        tips = []

        if len(week_meals) == 0:
            status = "No meal entries logged this week."
            trends = ["Start logging your breakfast, lunch and dinner to uncover dietary trends."]
            strengths = ["Ready to begin your health journey."]
            improvements = ["Log at least 3 meals consistently per day."]
            tips = ["Use the camera or food text input for quick 10-second logging."]
        else:
            status = f"Analyzed {len(week_meals)} meals over the past 7 days."
            if avg_prot >= 65:
                strengths.append(f"Strong protein foundation: Averaged {avg_prot}g daily, supporting muscle preservation.")
            else:
                improvements.append(f"Suboptimal protein intake ({avg_prot}g/day). Aim for at least 70-80g through dals, paneer, tofu, or eggs.")

            if macro_split["carbs_percent"] > 60:
                trends.append(f"High carbohydrate reliance ({macro_split['carbs_percent']}% of caloric intake).")
                improvements.append("Replace refined grains with high-fiber millets (ragi, jowar) or extra vegetables.")
            else:
                strengths.append(f"Balanced carbohydrate intake ({macro_split['carbs_percent']}%).")

            tips.append("Drink 500ml water 30 minutes before main meals to aid digestion and natural portion control.")
            tips.append("Add a raw vegetable salad (cucumber, carrots, tomato) before lunch to boost prebiotic fiber.")

        report = WeeklyNutritionReport(
            start_date=start_date_str,
            end_date=end_date_str,
            average_daily_calories=avg_cal,
            average_daily_protein=avg_prot,
            average_daily_carbs=avg_carbs,
            average_daily_fat=avg_fat,
            macro_distribution=macro_split,
            total_meals_logged=len(week_meals),
            most_frequent_foods=top_foods,
            progress_status=status,
            key_trends=trends,
            strengths=strengths,
            areas_for_improvement=improvements,
            actionable_ai_recommendations=tips
        )

        try:
            cache_service.cache_analytics(user_id, cache_key, report.model_dump())
        except Exception:
            pass

        return report

meal_service = MealService()
