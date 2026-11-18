from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date

# ================= AUTH SCHEMAS =================
class UserRegisterRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8)

class UserLoginRequest(BaseModel):
    username_or_email: str
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: str
    created_at: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 3600
    user: UserResponse

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None

class PasswordResetRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)

# ================= PROFILE SCHEMAS =================
class ProfileUpdateRequest(BaseModel):
    age: int = Field(..., ge=10, le=120)
    gender: str = Field("unspecified", description="male, female, other")
    height_cm: float = Field(..., ge=50, le=280)
    weight_kg: float = Field(..., ge=20, le=350)
    activity_level: str = Field(
        "moderate", 
        description="sedentary (desk job), light (1-3 days/wk), moderate (3-5 days/wk), active (6-7 days/wk), very_active (hard labor/athlete)"
    )
    dietary_preference: str = Field(
        "vegetarian", 
        description="vegetarian, non-vegetarian, vegan, eggetarian, jain"
    )
    fitness_goal: str = Field(
        "maintenance", 
        description="weight_loss, mild_weight_loss, maintenance, mild_muscle_gain, muscle_gain"
    )
    allergies: List[str] = Field(default_factory=list)
    dietary_restrictions: List[str] = Field(default_factory=list)
    preferred_cuisine: List[str] = Field(default_factory=lambda: ["Indian"])
    custom_calorie_target: Optional[float] = None

class CalculatedTargets(BaseModel):
    bmr: float
    tdee: float
    target_calories: float
    target_protein_g: float
    target_carbs_g: float
    target_fat_g: float
    target_fiber_g: float
    target_water_liters: float
    formula_used: str = "Mifflin-St Jeor Equation (Validated Clinical Standard)"
    disclaimer: str = (
        "Nutrition estimates and calorie targets are for informational and educational "
        "purposes only and do not replace personalized medical advice from a doctor or registered dietitian."
    )

class ProfileResponse(BaseModel):
    user_id: str
    profile: ProfileUpdateRequest
    targets: CalculatedTargets
    updated_at: str

# ================= FOOD & NUTRITION ANALYSIS SCHEMAS =================
class NutritionBreakdown(BaseModel):
    calories: float = 0.0
    protein: float = 0.0
    carbohydrates: float = 0.0
    total_fat: float = 0.0
    saturated_fat: Optional[float] = 0.0
    dietary_fiber: float = 0.0
    sugar: Optional[float] = 0.0
    sodium_mg: Optional[float] = 0.0

class FoodItemDetail(BaseModel):
    food_name: str
    detected_ingredients: List[str] = Field(default_factory=list)
    serving_size: str = "1 serving (approx 100g)"
    serving_weight_g: float = 100.0
    calories: float = 0.0
    protein: float = 0.0
    carbohydrates: float = 0.0
    total_fat: float = 0.0
    saturated_fat: Optional[float] = 0.0
    dietary_fiber: float = 0.0
    sugar: Optional[float] = 0.0
    sodium_mg: Optional[float] = 0.0
    health_score: int = Field(7, ge=1, le=10)
    confidence_level: str = "High (Verified Database)"
    source: str = "ICMR-NIN / IFCT & USDA FoodData Central"
    is_estimated: bool = False
    nutritional_highlights: List[str] = Field(default_factory=list)
    suggested_pairing: Optional[str] = None
    explanation: str = ""

class TextFoodAnalysisRequest(BaseModel):
    food_query: str
    portion_hint: Optional[str] = None
    notes: Optional[str] = None

class MultiFoodAnalysisResponse(BaseModel):
    query_or_source: str
    detected_items: List[FoodItemDetail]
    total_calories: float
    total_protein: float
    total_carbohydrates: float
    total_fat: float
    total_fiber: float
    total_sodium_mg: float
    overall_health_score: int
    meal_summary: str
    recommendations: List[str]
    disclaimer: str = (
        "Nutritional values are calculated based on verified food composition databases (ICMR/IFCT, USDA, Open Food Facts). "
        "Portion sizes and image recognitions are estimates and subject to cooking variation."
    )

class FoodComparisonRequest(BaseModel):
    food_a: str
    food_b: str
    serving_a: Optional[str] = "100g"
    serving_b: Optional[str] = "100g"

class FoodComparisonResponse(BaseModel):
    food_a: FoodItemDetail
    food_b: FoodItemDetail
    comparison_summary: str
    higher_protein: str
    lower_calorie: str
    higher_fiber: str
    winner_for_weight_loss: str
    winner_for_muscle_gain: str

class FoodSubstitutionRequest(BaseModel):
    food_name: str
    goal_or_reason: str = Field(..., description="e.g. lower carb, higher protein, vegan, gluten-free, diabetic-friendly")

class SubstitutionOption(BaseModel):
    substitute_name: str
    why_it_works: str
    macro_difference: str
    culinary_tips: str
    calories: float
    protein: float
    carbs: float
    fat: float

class FoodSubstitutionResponse(BaseModel):
    original_food: str
    reason: str
    substitutions: List[SubstitutionOption]

class RecipeGeneratorRequest(BaseModel):
    ingredients: List[str]
    dietary_preference: Optional[str] = "vegetarian"
    fitness_goal: Optional[str] = "healthy"
    max_cooking_time_minutes: Optional[int] = 30

class RecipeItem(BaseModel):
    title: str
    prep_time: str
    ingredients_used: List[str]
    pantry_items_needed: List[str]
    instructions: List[str]
    calories_per_serving: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    health_benefit: str

class RecipeGeneratorResponse(BaseModel):
    recipes: List[RecipeItem]
    tips: str

class LabelScannerResponse(BaseModel):
    product_name: str
    serving_size: str
    servings_per_container: Optional[float] = 1.0
    calories: float
    protein: float
    carbohydrates: float
    total_fat: float
    saturated_fat: Optional[float] = 0.0
    dietary_fiber: Optional[float] = 0.0
    sugars: Optional[float] = 0.0
    added_sugars: Optional[float] = 0.0
    sodium_mg: Optional[float] = 0.0
    key_ingredients: List[str] = Field(default_factory=list)
    allergens: List[str] = Field(default_factory=list)
    health_rating_score: int
    nutritionist_verdict: str
    flags: List[str] = Field(default_factory=list)

# ================= MEAL TRACKING SCHEMAS =================
class MealEntryCreate(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    meal_type: str = Field(..., description="breakfast, lunch, dinner, snacks")
    food_name: str
    serving_size: str = "1 serving"
    serving_weight_g: float = 100.0
    calories: float
    protein: float
    carbohydrates: float
    fat: float
    fiber: float = 0.0
    notes: Optional[str] = None

class MealEntryResponse(BaseModel):
    id: str
    user_id: str
    date: str
    meal_type: str
    food_name: str
    serving_size: str
    serving_weight_g: float
    calories: float
    protein: float
    carbohydrates: float
    fat: float
    fiber: float
    notes: Optional[str]
    created_at: str

class DailyDashboardResponse(BaseModel):
    date: str
    target_calories: float
    consumed_calories: float
    remaining_calories: float
    target_protein: float
    consumed_protein: float
    remaining_protein: float
    target_carbs: float
    consumed_carbs: float
    target_fat: float
    consumed_fat: float
    target_fiber: float
    consumed_fiber: float
    meals_by_type: Dict[str, List[MealEntryResponse]]
    calorie_adherence_percent: float
    protein_adherence_percent: float
    ai_meal_decision: Optional[str] = None

class WeeklyNutritionReport(BaseModel):
    start_date: str
    end_date: str
    average_daily_calories: float
    average_daily_protein: float
    average_daily_carbs: float
    average_daily_fat: float
    macro_distribution: Dict[str, float]
    total_meals_logged: int
    most_frequent_foods: List[Dict[str, Any]]
    progress_status: str
    key_trends: List[str]
    strengths: List[str]
    areas_for_improvement: List[str]
    actionable_ai_recommendations: List[str]

# ================= MEAL PLANNER SCHEMAS =================
class MealPlanRequest(BaseModel):
    duration_days: int = Field(1, ge=1, le=7)
    custom_calories: Optional[float] = None
    dietary_preference: Optional[str] = None
    allergies: Optional[List[str]] = None
    focus_cuisine: Optional[str] = "Indian"
    budget_friendly: bool = True

class SingleMealDetail(BaseModel):
    meal_type: str
    dish_name: str
    portion_size: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    key_ingredients: List[str]
    why_recommended: str
    affordable_substitute: Optional[str] = None

class DayMealPlan(BaseModel):
    day_number: int
    day_name: str
    breakfast: SingleMealDetail
    lunch: SingleMealDetail
    dinner: SingleMealDetail
    snack: SingleMealDetail
    total_calories: float
    total_protein: float
    total_carbs: float
    total_fat: float

class MealPlanResponse(BaseModel):
    id: str
    user_id: str
    duration_days: int
    created_at: str
    daily_plans: List[DayMealPlan]
    grocery_shopping_list: Dict[str, List[str]]
    nutritionist_notes: str

# ================= RAG CHAT SCHEMAS =================
class ChatMessageRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    include_user_context: bool = True

class ChatMessageResponse(BaseModel):
    answer: str
    sources: List[str] = Field(default_factory=list)
    suggested_followups: List[str] = Field(default_factory=list)
    conversation_id: str
    model_used: str
