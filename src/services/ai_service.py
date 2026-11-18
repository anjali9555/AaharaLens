import os
import json
import base64
from typing import List, Dict, Any, Optional
from loguru import logger
from groq import Groq
from src.core.config import settings
from src.schemas.nutrition_schemas import (
    FoodItemDetail, MultiFoodAnalysisResponse,
    LabelScannerResponse, FoodSubstitutionResponse, SubstitutionOption,
    FoodComparisonResponse, RecipeGeneratorResponse, RecipeItem
)
from src.services.nutrition_service import NutritionCalculationService

class AIService:
    """Multimodal Vision & Intelligence Service powered by Groq and verified nutrition engines."""

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.client = None
        if self.api_key:
            try:
                self.client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
        self.model_name = settings.GROQ_MODEL
        self.vision_model_name = settings.GROQ_VISION_MODEL

    def _call_llm(self, messages: list, json_mode: bool = True, max_tokens: int = 1500) -> Optional[str]:
        """Robust LLM invocation with model fallback and error trapping."""
        if not self.client:
            logger.warning("Groq client not configured.")
            return None
            
        models_to_try = [self.model_name] + [m for m in settings.FALLBACK_MODELS if m != self.model_name]
        
        for model in models_to_try:
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.2
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                    
                resp = self.client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"Groq invocation failed on {model}: {e}")
                
        return None

    def analyze_food_text(self, food_query: str, portion_hint: Optional[str] = None) -> MultiFoodAnalysisResponse:
        """Parses multi-item food query (e.g. '2 rotis, 1 bowl dal tadka, and cucumber salad') and returns verified macros."""
        system_prompt = """You are an expert Indian & International food parsing engine.
Given a user query describing food, split it into individual food items with their portion/quantity hints.
Respond ONLY in valid JSON format:
{
  "items": [
    {"food_name": "Roti", "portion": "2 rotis"},
    {"food_name": "Dal Tadka", "portion": "1 bowl"}
  ],
  "meal_summary": "Balanced Indian vegetarian meal with wholesome grains and lentil protein.",
  "recommendations": ["Add a lemon wedge to increase iron absorption from the dal", "Include raw salad for enzymes"]
}"""
        raw = self._call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Parse the following foods: {food_query}. Portion hint: {portion_hint or 'Standard'}"}
        ], json_mode=True)

        items_parsed = []
        meal_summary = "Nutritional analysis of requested food."
        recommendations = ["Drink plenty of water", "Maintain balanced macro proportions"]

        if raw:
            try:
                parsed_json = json.loads(raw)
                items_parsed = parsed_json.get("items", [])
                meal_summary = parsed_json.get("meal_summary", meal_summary)
                recommendations = parsed_json.get("recommendations", recommendations)
            except Exception as e:
                logger.error(f"Error parsing LLM food text response: {e}")

        if not items_parsed:
            # Fallback direct split by comma or 'and'
            parts = [p.strip() for p in food_query.replace(" and ", ",").split(",") if p.strip()]
            items_parsed = [{"food_name": p, "portion": p} for p in parts] or [{"food_name": food_query, "portion": "1 serving"}]

        # Compute verified nutrition for every item
        detected_details: List[FoodItemDetail] = []
        tot_cals = 0.0
        tot_protein = 0.0
        tot_carbs = 0.0
        tot_fat = 0.0
        tot_fiber = 0.0
        tot_sodium = 0.0
        health_scores = []

        for it in items_parsed:
            name = it.get("food_name", food_query)
            portion = it.get("portion", portion_hint)
            detail = NutritionCalculationService.calculate_food_nutrition(name, portion)
            detected_details.append(detail)
            tot_cals += detail.calories
            tot_protein += detail.protein
            tot_carbs += detail.carbohydrates
            tot_fat += detail.total_fat
            tot_fiber += detail.dietary_fiber
            tot_sodium += (detail.sodium_mg or 0.0)
            health_scores.append(detail.health_score)

        avg_health = round(sum(health_scores) / max(1, len(health_scores)))

        return MultiFoodAnalysisResponse(
            query_or_source=food_query,
            detected_items=detected_details,
            total_calories=round(tot_cals, 1),
            total_protein=round(tot_protein, 1),
            total_carbohydrates=round(tot_carbs, 1),
            total_fat=round(tot_fat, 1),
            total_fiber=round(tot_fiber, 1),
            total_sodium_mg=round(tot_sodium, 1),
            overall_health_score=avg_health,
            meal_summary=meal_summary,
            recommendations=recommendations
        )

    def _preprocess_image_for_vision(self, image_bytes: bytes) -> str:
        """
        Normalizes any input image (PNG, WEBP, RGBA, high-res) into an optimized RGB JPEG data URI.
        Enforces decompression-bomb protection, format validation, and caps dimensions to 1280x1280.
        """
        try:
            from PIL import Image
            import io
            
            # Enforce max pixel safety to protect against decompression bombs
            Image.MAX_IMAGE_PIXELS = 25_000_000

            probe = Image.open(io.BytesIO(image_bytes))
            if probe.format not in ["JPEG", "PNG", "WEBP"]:
                raise ValueError(f"Unsupported image format: {probe.format}. Only JPEG, PNG, and WEBP are supported.")
            probe.verify()

            # Re-open after verify
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
        except Exception as e:
            logger.error(f"Image preprocessing failed: {e}")
            raise ValueError(f"Invalid or corrupted image format: {e}")

    def analyze_food_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> MultiFoodAnalysisResponse:
        """Genuine vision-capable AI recognition for food images (Indian meals, bowls, plates)."""
        data_uri = self._preprocess_image_for_vision(image_bytes)

        system_prompt = """You are a senior clinical nutritionist and food vision AI.
Analyze the food image carefully.
Recognize all distinct food dishes and items visible on the plate, table or bowl (such as Dal, Roti, Rice, Paneer, Biryani, Curd, Salad, etc.).
Estimate reasonable portions ONLY based on visible cues (e.g. '1 bowl (approx 150g)', '2 rotis', '1 cup rice').
Detect visible ingredients and calculate an overall health score (1 to 10).
You MUST respond ONLY in valid JSON format:
{
  "detected_items": [
    {
      "food_name": "Dal Tadka",
      "visible_portion": "1 small bowl (approx 150g)",
      "visible_ingredients": ["Yellow lentils", "Tomatoes", "Cumin", "Ghee"],
      "confidence": "High"
    }
  ],
  "meal_type": "Lunch / Dinner",
  "summary": "Nutritious traditional plate featuring lentils and whole grains.",
  "nutritionist_recommendations": [
    "Great protein balance from lentils",
    "Pair with raw greens to increase micronutrient density"
  ]
}"""
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze the foods visible in this meal image with utmost precision."},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]
            }
        ]

        raw = None
        try:
            raw = self.client.chat.completions.create(
                model=self.vision_model_name,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=1500
            ).choices[0].message.content
        except Exception as e:
            logger.error(f"Vision AI call failed: {e}")

        detected_raw = []
        summary = "Image-based visual food analysis."
        recommendations = ["Confirm portion weights before logging to your meal diary."]

        if raw:
            try:
                parsed = json.loads(raw)
                detected_raw = parsed.get("detected_items", [])
                summary = parsed.get("summary", summary)
                recommendations = parsed.get("nutritionist_recommendations", recommendations)
            except Exception as e:
                logger.error(f"Error parsing vision response: {e}")

        if not detected_raw:
            raise ValueError(
                "No recognizable food items could be detected in this image. "
                "Please ensure clear lighting and that food is clearly visible, or input your items manually."
            )

        # Compute verified nutrition from verified database
        detected_details: List[FoodItemDetail] = []
        tot_cals = 0.0
        tot_protein = 0.0
        tot_carbs = 0.0
        tot_fat = 0.0
        tot_fiber = 0.0
        tot_sodium = 0.0
        health_scores = []

        for it in detected_raw:
            name = it.get("food_name", "Meal item")
            portion = it.get("visible_portion", "100g")
            detail = NutritionCalculationService.calculate_food_nutrition(name, portion)
            # Enhance with detected visual ingredients if available
            if it.get("visible_ingredients"):
                detail.detected_ingredients = it.get("visible_ingredients")
            detail.confidence_level = f"{it.get('confidence', 'Moderate')} (Visual Detection)"
            detail.is_estimated = True
            
            detected_details.append(detail)
            tot_cals += detail.calories
            tot_protein += detail.protein
            tot_carbs += detail.carbohydrates
            tot_fat += detail.total_fat
            tot_fiber += detail.dietary_fiber
            tot_sodium += (detail.sodium_mg or 0.0)
            health_scores.append(detail.health_score)

        avg_health = round(sum(health_scores) / max(1, len(health_scores)))

        return MultiFoodAnalysisResponse(
            query_or_source="Image Upload / Camera Capture",
            detected_items=detected_details,
            total_calories=round(tot_cals, 1),
            total_protein=round(tot_protein, 1),
            total_carbohydrates=round(tot_carbs, 1),
            total_fat=round(tot_fat, 1),
            total_fiber=round(tot_fiber, 1),
            total_sodium_mg=round(tot_sodium, 1),
            overall_health_score=avg_health,
            meal_summary=summary,
            recommendations=recommendations
        )

    def scan_food_label(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> LabelScannerResponse:
        """Extracts and verifies packaged nutrition facts labels via Vision AI."""
        data_uri = self._preprocess_image_for_vision(image_bytes)

        system_prompt = """You are an OCR and Nutrition Label Inspection specialist.
Read the packaged food nutrition facts panel and ingredient list from the image.
Extract exact numerical values per serving.
Check for red flags: high added sugars, high sodium (>400mg/serving), palm oil, trans fats, artificial sweeteners.

SCORING & DETECTION RULES:
1. If the image is blank, unreadable, corrupt, or does NOT contain a legible nutrition facts label:
   - "product_name": "No Label Detected"
   - "serving_size": "N/A"
   - "servings_per_container": 0.0
   - "calories": 0.0, "protein": 0.0, "carbohydrates": 0.0, "total_fat": 0.0
   - "saturated_fat": 0.0, "dietary_fiber": 0.0, "sugars": 0.0, "added_sugars": 0.0, "sodium_mg": 0.0
   - "key_ingredients": []
   - "allergens": []
   - "health_rating_score": 0 (DO NOT assign a minimum score of 1 to missing or unreadable labels)
   - "nutritionist_verdict": "Image contains no legible text or nutrition label information to analyze."
   - "flags": ["No label detected"]
2. If a valid, readable nutrition facts label is present:
   - Extract numerical facts accurately.
   - Provide an objective health rating score from 1 to 10.
   - List key ingredients, allergens, and health/additive red flags.

Respond ONLY in valid JSON format:
{
  "product_name": "Identified product or 'Packaged Food Item'",
  "serving_size": "e.g. 30g / 1 cup",
  "servings_per_container": 2.0,
  "calories": 150.0,
  "protein": 3.0,
  "carbohydrates": 22.0,
  "total_fat": 6.0,
  "saturated_fat": 1.5,
  "dietary_fiber": 2.0,
  "sugars": 8.0,
  "added_sugars": 6.0,
  "sodium_mg": 180.0,
  "key_ingredients": ["Wheat flour", "Sugar", "Cocoa"],
  "allergens": ["Gluten", "Soy"],
  "health_rating_score": 5,
  "nutritionist_verdict": "Moderate nutritional value. Contains added sugar.",
  "flags": ["Contains 6g added sugar", "Refined flour base"]
}"""
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Scan and extract the nutrition facts panel from this image."},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]
            }
        ]

        raw = None
        try:
            raw = self.client.chat.completions.create(
                model=self.vision_model_name,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=1200
            ).choices[0].message.content
        except Exception as e:
            logger.error(f"Label scan error: {e}")

        if raw:
            try:
                data = json.loads(raw)
                
                # Normalize key fields for inspection
                prod_name = str(data.get("product_name", "")).strip()
                prod_name_lower = prod_name.lower()
                flags = [str(f).strip() for f in data.get("flags", [])]
                flags_lower = [f.lower() for f in flags]
                verdict = str(data.get("nutritionist_verdict", "")).strip()
                verdict_lower = verdict.lower()
                
                cals = float(data.get("calories", 0.0) or 0.0)
                protein = float(data.get("protein", 0.0) or 0.0)
                carbs = float(data.get("carbohydrates", 0.0) or 0.0)
                fat = float(data.get("total_fat", 0.0) or 0.0)
                raw_score = int(data.get("health_rating_score", 0) or 0)

                # Explicit early-return path for blank, unreadable, or missing nutrition-label information
                is_missing_or_unreadable = (
                    any("no label" in f for f in flags_lower)
                    or "no label detected" in prod_name_lower
                    or "no legible text" in verdict_lower
                    or "no nutrition" in verdict_lower
                    or (
                        cals == 0.0 and protein == 0.0 and carbs == 0.0 and fat == 0.0
                        and (
                            raw_score <= 1
                            or "no label" in flags_lower
                            or not data.get("key_ingredients")
                            or "packaged food" in prod_name_lower
                            or "unknown" in prod_name_lower
                        )
                    )
                )

                if is_missing_or_unreadable:
                    # Clean unreadable response with explicit health_rating_score = 0
                    out_flags = [f for f in flags if "no label" in f.lower()]
                    if not out_flags:
                        out_flags = ["No label detected"]
                    return LabelScannerResponse(
                        product_name="No Label Detected",
                        serving_size="N/A",
                        servings_per_container=0.0,
                        calories=0.0,
                        protein=0.0,
                        carbohydrates=0.0,
                        total_fat=0.0,
                        saturated_fat=0.0,
                        dietary_fiber=0.0,
                        sugars=0.0,
                        added_sugars=0.0,
                        sodium_mg=0.0,
                        key_ingredients=[],
                        allergens=[],
                        health_rating_score=0,
                        nutritionist_verdict=verdict if "no legible text" in verdict_lower else "Image contains no legible text or nutrition label information to analyze.",
                        flags=out_flags
                    )

                # Valid nutrition label: preserve 1-10 scoring logic and flags
                data["health_rating_score"] = max(1, min(10, raw_score if raw_score > 0 else 5))
                return LabelScannerResponse(**data)
            except Exception as e:
                logger.error(f"Error parsing label json: {e}")

        # Fallback response when no legible label is detected or scan fails
        return LabelScannerResponse(
            product_name="No Label Detected",
            serving_size="N/A",
            servings_per_container=0.0,
            calories=0.0,
            protein=0.0,
            carbohydrates=0.0,
            total_fat=0.0,
            saturated_fat=0.0,
            dietary_fiber=0.0,
            sugars=0.0,
            added_sugars=0.0,
            sodium_mg=0.0,
            key_ingredients=[],
            allergens=[],
            health_rating_score=0,
            nutritionist_verdict="Image contains no legible text or nutrition label information to analyze.",
            flags=["No label detected"]
        )

    def suggest_substitutions(self, food_name: str, goal: str) -> FoodSubstitutionResponse:
        """Smart food substitution engine suggesting healthier alternatives based on preferences."""
        system_prompt = """You are a functional nutrition consultant.
Provide 2-3 genuine, practical healthier food substitutes for the given food item, tailored to the user's specific goal (e.g. lower carb, higher protein, vegan, lower sodium).
Respond ONLY in valid JSON format:
{
  "substitutions": [
    {
      "substitute_name": "Tofu Scramble",
      "why_it_works": "Matches texture while offering 100% plant-based protein with zero cholesterol.",
      "macro_difference": "Higher protein, lower saturated fat.",
      "culinary_tips": "Season with kala namak (black salt) and turmeric for an authentic egg-like flavor.",
      "calories": 140.0,
      "protein": 14.0,
      "carbs": 3.0,
      "fat": 8.0
    }
  ]
}"""
        raw = self._call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Suggest substitutes for: {food_name}. Goal / Preference: {goal}"}
        ], json_mode=True)

        subs = []
        if raw:
            try:
                parsed = json.loads(raw)
                subs = [SubstitutionOption(**s) for s in parsed.get("substitutions", [])]
            except Exception as e:
                logger.error(f"Error parsing substitution response: {e}")

        if not subs:
            subs = [
                SubstitutionOption(
                    substitute_name=f"Healthier alternative to {food_name}",
                    why_it_works=f"Nutrient-dense alternative aligned with {goal}.",
                    macro_difference="Optimized macronutrient ratio with higher fiber.",
                    culinary_tips="Cook with minimal cold-pressed oil and aromatic spices.",
                    calories=120.0,
                    protein=6.0,
                    carbs=18.0,
                    fat=2.5
                )
            ]

        return FoodSubstitutionResponse(
            original_food=food_name,
            reason=goal,
            substitutions=subs
        )

    def compare_foods(self, food_a: str, food_b: str, serving_a: str = "100g", serving_b: str = "100g") -> FoodComparisonResponse:
        """Accurately compares two foods based on verified database macros."""
        detail_a = NutritionCalculationService.calculate_food_nutrition(food_a, serving_a)
        detail_b = NutritionCalculationService.calculate_food_nutrition(food_b, serving_b)

        higher_prot = detail_a.food_name if detail_a.protein >= detail_b.protein else detail_b.food_name
        lower_cal = detail_a.food_name if detail_a.calories <= detail_b.calories else detail_b.food_name
        higher_fib = detail_a.food_name if detail_a.dietary_fiber >= detail_b.dietary_fiber else detail_b.food_name
        winner_wl = lower_cal if (detail_a.dietary_fiber > 1 or detail_b.dietary_fiber > 1) else lower_cal
        winner_mg = higher_prot

        summary = (
            f"{detail_a.food_name} delivers {detail_a.calories} kcal & {detail_a.protein}g protein, "
            f"while {detail_b.food_name} delivers {detail_b.calories} kcal & {detail_b.protein}g protein. "
            f"{higher_prot} leads in protein density by {abs(round(detail_a.protein - detail_b.protein, 1))}g."
        )

        return FoodComparisonResponse(
            food_a=detail_a,
            food_b=detail_b,
            comparison_summary=summary,
            higher_protein=higher_prot,
            lower_calorie=lower_cal,
            higher_fiber=higher_fib,
            winner_for_weight_loss=winner_wl,
            winner_for_muscle_gain=winner_mg
        )

    def generate_leftover_recipes(
        self,
        ingredients: List[str],
        dietary_preference: str = "vegetarian",
        fitness_goal: str = "healthy"
    ) -> RecipeGeneratorResponse:
        """Suggests delicious, wholesome recipes from available kitchen ingredients."""
        system_prompt = """You are a creative culinary nutritionist specializing in home-cooked healthy meals.
Given available ingredients, generate 2 practical, delicious recipes.
For each recipe, include instructions, macros per serving, and health benefits.
Respond ONLY in valid JSON format:
{
  "recipes": [
    {
      "title": "Quick Paneer & Bell Pepper Bhurji Wrap",
      "prep_time": "15 mins",
      "ingredients_used": ["Paneer", "Bell pepper", "Onion"],
      "pantry_items_needed": ["Roti / Wrap", "Turmeric", "Cumin", "Salt"],
      "instructions": [
        "Heat 1 tsp oil in a pan and temper with cumin seeds.",
        "Saute chopped onions and bell peppers for 3 minutes.",
        "Crumble paneer and fold gently with spices for 2 minutes."
      ],
      "calories_per_serving": 240.0,
      "protein_g": 16.0,
      "carbs_g": 12.0,
      "fat_g": 14.0,
      "fiber_g": 3.0,
      "health_benefit": "Rich in lean calcium, complete protein, and Vitamin C."
    }
  ],
  "tips": "Utilize fresh herbs like coriander to elevate antioxidant value."
}"""
        raw = self._call_llm([
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Ingredients available: {', '.join(ingredients)}. Dietary preference: {dietary_preference}. Goal: {fitness_goal}."
            }
        ], json_mode=True)

        recipes = []
        tips = "Cook on medium flame to retain heat-sensitive nutrients."
        if raw:
            try:
                parsed = json.loads(raw)
                recipes = [RecipeItem(**r) for r in parsed.get("recipes", [])]
                tips = parsed.get("tips", tips)
            except Exception as e:
                logger.error(f"Error parsing recipe generator: {e}")

        if not recipes:
            recipes = [
                RecipeItem(
                    title="Nutritious Sautéed Vegetable Bowl",
                    prep_time="20 mins",
                    ingredients_used=ingredients,
                    pantry_items_needed=["Olive oil / Ghee", "Black pepper", "Salt"],
                    instructions=["Wash and chop all vegetables uniformly.", "Sauté lightly in a warm skillet for 6 minutes.", "Season with salt, lemon, and pepper."],
                    calories_per_serving=180.0,
                    protein_g=5.0,
                    carbs_g=22.0,
                    fat_g=8.0,
                    fiber_g=4.5,
                    health_benefit="Packed with dietary fiber and phytonutrients."
                )
            ]

        return RecipeGeneratorResponse(recipes=recipes, tips=tips)

    def decide_next_meal(
        self,
        target_calories: float,
        consumed_calories: float,
        target_protein: float,
        consumed_protein: float,
        target_carbs: float,
        consumed_carbs: float,
        dietary_pref: str = "vegetarian"
    ) -> str:
        """AI Meal Decision Engine: analyzes daily progress and prescribes the optimal next meal."""
        rem_cals = round(target_calories - consumed_calories, 1)
        rem_prot = round(target_protein - consumed_protein, 1)
        rem_carbs = round(target_carbs - consumed_carbs, 1)

        system_prompt = """You are an intelligent clinical nutrition decision engine.
Analyze the user's remaining calories, protein, and carbohydrates for today.
Recommend the exact next meal (Dinner or Snack) to satisfy their deficit without overshooting.
Include dish recommendation, portion size, and why it's optimal.
Keep response concise, motivating, and actionable (2-3 sentences)."""
        prompt = (
            f"User Target: {target_calories} kcal, {target_protein}g protein, {target_carbs}g carbs.\n"
            f"Consumed Today: {consumed_calories} kcal, {consumed_protein}g protein, {consumed_carbs}g carbs.\n"
            f"Remaining: {rem_cals} kcal, {rem_prot}g protein deficit, {rem_carbs}g carbs.\n"
            f"Dietary preference: {dietary_pref}."
        )

        res = self._call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ], json_mode=False, max_tokens=250)

        if res:
            return res.strip()
            
        if rem_prot > 15:
            return f"You are currently {rem_prot}g behind your protein target. Opt for a high-protein dinner like 150g grilled paneer/tofu or 3 boiled eggs with a green salad ({max(200, int(rem_cals))} kcal)."
        return f"You have {rem_cals} kcal remaining today. Choose a light, wholesome meal like Moong Dal Khichdi or a bowl of vegetable soup with 1 whole wheat roti."

ai_service = AIService()
