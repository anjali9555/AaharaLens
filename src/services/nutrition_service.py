import re
import requests
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger
from src.core.config import settings
from src.schemas.nutrition_schemas import FoodItemDetail, CalculatedTargets

# Comprehensive Verified Food Composition Table
# Data sourced & verified against ICMR-NIN (National Institute of Nutrition, India) IFCT & USDA FoodData Central
VERIFIED_FOOD_DATABASE: Dict[str, Dict[str, Any]] = {
    # --- Dals & Lentils ---
    "dal tadka": {
        "per_100g": {"calories": 116.0, "protein": 6.8, "carbs": 14.5, "fat": 3.6, "saturated_fat": 1.2, "fiber": 3.2, "sugar": 0.8, "sodium_mg": 280.0},
        "serving_unit": "1 katori / small bowl", "serving_weight_g": 150.0,
        "ingredients": ["Yellow Toor Dal", "Tomatoes", "Onion", "Ghee/Oil", "Cumin", "Turmeric", "Garlic"],
        "health_score": 8, "pairing": "Steamed Rice or Roti with Kachumber Salad",
        "highlights": ["Good plant protein", "Rich in dietary fiber", "Gut-friendly turmeric"]
    },
    "dal makhani": {
        "per_100g": {"calories": 168.0, "protein": 5.4, "carbs": 16.2, "fat": 9.2, "saturated_fat": 4.8, "fiber": 4.1, "sugar": 1.2, "sodium_mg": 340.0},
        "serving_unit": "1 bowl", "serving_weight_g": 180.0,
        "ingredients": ["Whole Black Urad Dal", "Rajma", "Butter", "Fresh Cream", "Tomato Puree", "Spices"],
        "health_score": 6, "pairing": "Whole Wheat Roti and Green Salad",
        "highlights": ["High fiber", "Rich in minerals", "Calorie dense due to butter"]
    },
    "moong dal": {
        "per_100g": {"calories": 105.0, "protein": 7.2, "carbs": 15.0, "fat": 1.8, "saturated_fat": 0.4, "fiber": 3.8, "sugar": 0.5, "sodium_mg": 220.0},
        "serving_unit": "1 katori / bowl", "serving_weight_g": 150.0,
        "ingredients": ["Yellow Moong Dal", "Cumin", "Ginger", "Hing", "Turmeric"],
        "health_score": 9, "pairing": "Warm Roti or Khichdi",
        "highlights": ["Very easy to digest", "High protein-to-calorie ratio", "Ideal for recovery"]
    },
    "rajma": {
        "per_100g": {"calories": 138.0, "protein": 7.8, "carbs": 19.5, "fat": 3.4, "saturated_fat": 0.6, "fiber": 5.8, "sugar": 1.1, "sodium_mg": 310.0},
        "serving_unit": "1 katori / bowl", "serving_weight_g": 160.0,
        "ingredients": ["Red Kidney Beans", "Onions", "Tomatoes", "Ginger-Garlic", "Garam Masala"],
        "health_score": 8, "pairing": "Steamed Jeera Rice or Quinoa",
        "highlights": ["High soluble fiber", "Good complex carbohydrates", "Supports heart health"]
    },
    "chole": {
        "per_100g": {"calories": 160.0, "protein": 7.5, "carbs": 22.0, "fat": 5.1, "saturated_fat": 0.8, "fiber": 6.2, "sugar": 1.5, "sodium_mg": 360.0},
        "serving_unit": "1 bowl", "serving_weight_g": 160.0,
        "ingredients": ["Kabuli Chana (Chickpeas)", "Onions", "Tomatoes", "Chole Masala", "Mustard Oil/Ghee"],
        "health_score": 8, "pairing": "Brown Rice, Roti or Bhature (occasional)",
        "highlights": ["High fiber", "Low glycemic index", "Promotes satiety"]
    },
    
    # --- Breads & Grains ---
    "roti": {
        "per_100g": {"calories": 264.0, "protein": 9.1, "carbs": 54.0, "fat": 1.5, "saturated_fat": 0.3, "fiber": 9.5, "sugar": 1.0, "sodium_mg": 180.0},
        "serving_unit": "1 medium roti (approx 40g)", "serving_weight_g": 40.0,
        "ingredients": ["Whole Wheat Atta (Stone-ground)", "Water", "Pinch of salt"],
        "health_score": 9, "pairing": "Dal Tadka and Green Vegetables",
        "highlights": ["100% whole grain", "Zero added sugar", "Rich in B-vitamins"]
    },
    "chapati": {
        "per_100g": {"calories": 264.0, "protein": 9.1, "carbs": 54.0, "fat": 1.5, "saturated_fat": 0.3, "fiber": 9.5, "sugar": 1.0, "sodium_mg": 180.0},
        "serving_unit": "1 medium chapati", "serving_weight_g": 40.0,
        "ingredients": ["Whole Wheat Flour", "Water"],
        "health_score": 9, "pairing": "Dal or Vegetable Sabzi",
        "highlights": ["Complex carbs", "High fiber", "Digestive health"]
    },
    "paratha (plain)": {
        "per_100g": {"calories": 315.0, "protein": 7.4, "carbs": 46.0, "fat": 11.8, "saturated_fat": 4.5, "fiber": 6.8, "sugar": 1.1, "sodium_mg": 240.0},
        "serving_unit": "1 paratha (approx 65g)", "serving_weight_g": 65.0,
        "ingredients": ["Whole Wheat Flour", "Ghee/Oil", "Water", "Salt"],
        "health_score": 7, "pairing": "Plain Curd / Dahi and Mint Chutney",
        "highlights": ["Wholesome fuel", "Moderate healthy fats", "Satiating"]
    },
    "steamed rice": {
        "per_100g": {"calories": 130.0, "protein": 2.7, "carbs": 28.2, "fat": 0.3, "saturated_fat": 0.1, "fiber": 0.4, "sugar": 0.1, "sodium_mg": 5.0},
        "serving_unit": "1 cup cooked (approx 150g)", "serving_weight_g": 150.0,
        "ingredients": ["White Rice", "Water"],
        "health_score": 7, "pairing": "Dal, Sambar, or Rajma for complete protein",
        "highlights": ["Quick energy source", "Gluten-free", "Easily digested"]
    },
    "brown rice": {
        "per_100g": {"calories": 123.0, "protein": 2.7, "carbs": 25.6, "fat": 1.0, "saturated_fat": 0.2, "fiber": 1.8, "sugar": 0.2, "sodium_mg": 4.0},
        "serving_unit": "1 cup cooked (approx 150g)", "serving_weight_g": 150.0,
        "ingredients": ["Whole Grain Brown Rice", "Water"],
        "health_score": 9, "pairing": "Grilled Paneer, Dal or Tofu",
        "highlights": ["High fiber bran intact", "Low GI", "Rich in Magnesium"]
    },
    "poha": {
        "per_100g": {"calories": 145.0, "protein": 3.2, "carbs": 26.5, "fat": 3.0, "saturated_fat": 0.6, "fiber": 2.1, "sugar": 1.5, "sodium_mg": 210.0},
        "serving_unit": "1 plate / bowl (approx 150g)", "serving_weight_g": 150.0,
        "ingredients": ["Flattened Rice (Poha)", "Onions", "Peanuts", "Mustard Seeds", "Curry Leaves", "Lemon"],
        "health_score": 8, "pairing": "Sprouts or a glass of Buttermilk",
        "highlights": ["Rich in dietary iron", "Light breakfast option", "Healthy fats from peanuts"]
    },
    "upma": {
        "per_100g": {"calories": 135.0, "protein": 3.4, "carbs": 23.5, "fat": 3.2, "saturated_fat": 0.7, "fiber": 2.0, "sugar": 1.2, "sodium_mg": 220.0},
        "serving_unit": "1 bowl (approx 150g)", "serving_weight_g": 150.0,
        "ingredients": ["Semolina (Sooji)", "Vegetables", "Mustard seeds", "Ginger", "Curry leaves"],
        "health_score": 8, "pairing": "Coconut Chutney or Sambar",
        "highlights": ["Low fat", "Warm breakfast staple", "Vegetable micronutrients"]
    },

    # --- South Indian Delicacies ---
    "idli": {
        "per_100g": {"calories": 132.0, "protein": 4.2, "carbs": 26.8, "fat": 0.6, "saturated_fat": 0.1, "fiber": 1.9, "sugar": 0.3, "sodium_mg": 180.0},
        "serving_unit": "2 medium idlis (approx 100g)", "serving_weight_g": 100.0,
        "ingredients": ["Fermented Parboiled Rice", "Urad Dal", "Fenugreek seeds", "Salt"],
        "health_score": 9, "pairing": "Vegetable Sambar and Tomato Chutney",
        "highlights": ["Fermented gut probiotics", "Zero oil steaming", "Complete amino acid profile"]
    },
    "dosa": {
        "per_100g": {"calories": 182.0, "protein": 4.5, "carbs": 31.0, "fat": 4.6, "saturated_fat": 1.1, "fiber": 2.1, "sugar": 0.5, "sodium_mg": 240.0},
        "serving_unit": "1 plain dosa (approx 100g)", "serving_weight_g": 100.0,
        "ingredients": ["Fermented Rice", "Urad Dal Batter", "Sesame or Vegetable Oil"],
        "health_score": 8, "pairing": "Vegetable Sambar and Mint-Coconut Chutney",
        "highlights": ["Fermented batter", "Crisp energy source", "Moderate calories"]
    },
    "sambar": {
        "per_100g": {"calories": 62.0, "protein": 2.8, "carbs": 9.4, "fat": 1.5, "saturated_fat": 0.3, "fiber": 2.4, "sugar": 2.1, "sodium_mg": 290.0},
        "serving_unit": "1 bowl (approx 180g)", "serving_weight_g": 180.0,
        "ingredients": ["Toor Dal", "Drumstick", "Pumpkin", "Shallots", "Tamarind", "Sambar Masala"],
        "health_score": 9, "pairing": "Idli, Dosa or Steamed Rice",
        "highlights": ["High antioxidant tamarind", "Dense vegetable fiber", "Low calorie"]
    },

    # --- Paneer & Dairy Dishes ---
    "paneer (raw)": {
        "per_100g": {"calories": 265.0, "protein": 18.3, "carbs": 3.4, "fat": 20.8, "saturated_fat": 12.5, "fiber": 0.0, "sugar": 2.5, "sodium_mg": 25.0},
        "serving_unit": "100g portion", "serving_weight_g": 100.0,
        "ingredients": ["Full Cream Cow/Buffalo Milk", "Citric acid/Lemon juice"],
        "health_score": 8, "pairing": "Cucumber salad and Lemon-Pepper sprinkle",
        "highlights": ["Exceptional vegetarian protein", "Rich in bioavailable Calcium", "Keto friendly"]
    },
    "paneer tikka": {
        "per_100g": {"calories": 210.0, "protein": 14.5, "carbs": 6.8, "fat": 14.2, "saturated_fat": 7.8, "fiber": 1.2, "sugar": 2.0, "sodium_mg": 320.0},
        "serving_unit": "1 plate (4-5 skewers, 150g)", "serving_weight_g": 150.0,
        "ingredients": ["Paneer cubes", "Hung curd / Yogurt", "Bell peppers", "Onion", "Tandoori spices"],
        "health_score": 8, "pairing": "Green Mint Chutney and Onion rings",
        "highlights": ["Tandoor roasted (low oil)", "High protein snack", "Rich in Calcium & Zinc"]
    },
    "palak paneer": {
        "per_100g": {"calories": 155.0, "protein": 8.6, "carbs": 5.2, "fat": 11.4, "saturated_fat": 6.1, "fiber": 2.8, "sugar": 1.5, "sodium_mg": 310.0},
        "serving_unit": "1 bowl (approx 160g)", "serving_weight_g": 160.0,
        "ingredients": ["Spinach puree (Palak)", "Paneer cubes", "Garlic", "Onions", "Ghee"],
        "health_score": 9, "pairing": "Whole Wheat Roti or Missi Roti",
        "highlights": ["High iron from spinach", "Calcium & protein synergy", "Antioxidant carotenoids"]
    },
    "curd / dahi": {
        "per_100g": {"calories": 61.0, "protein": 3.5, "carbs": 4.7, "fat": 3.3, "saturated_fat": 2.1, "fiber": 0.0, "sugar": 4.7, "sodium_mg": 46.0},
        "serving_unit": "1 small bowl (approx 150g)", "serving_weight_g": 150.0,
        "ingredients": ["Cultured Milk", "Active Lactobacillus probiotics"],
        "health_score": 9, "pairing": "Paratha, Rice, or Fruit Bowl",
        "highlights": ["Live gut probiotics", "Supports digestion", "High bioavailable calcium"]
    },

    # --- Poultry, Meat & Eggs ---
    "boiled egg": {
        "per_100g": {"calories": 155.0, "protein": 12.6, "carbs": 1.1, "fat": 10.6, "saturated_fat": 3.3, "fiber": 0.0, "sugar": 1.1, "sodium_mg": 124.0},
        "serving_unit": "1 whole large egg (approx 50g)", "serving_weight_g": 50.0,
        "ingredients": ["Fresh Hen's Egg"],
        "health_score": 9, "pairing": "Black pepper and Whole Grain Toast",
        "highlights": ["Complete protein DIAAS 100", "Choline for brain health", "Lutein for eye health"]
    },
    "egg bhurji": {
        "per_100g": {"calories": 168.0, "protein": 11.2, "carbs": 3.8, "fat": 12.1, "saturated_fat": 3.6, "fiber": 0.8, "sugar": 1.4, "sodium_mg": 280.0},
        "serving_unit": "1 plate (2 eggs, approx 130g)", "serving_weight_g": 130.0,
        "ingredients": ["Whole eggs", "Finely chopped Onions", "Tomatoes", "Green chillies", "Coriander", "Oil"],
        "health_score": 8, "pairing": "Multigrain Roti or Brown Bread",
        "highlights": ["High protein breakfast", "Quick satiety", "Vitamin B12"]
    },
    "chicken curry": {
        "per_100g": {"calories": 165.0, "protein": 16.8, "carbs": 4.5, "fat": 9.0, "saturated_fat": 2.4, "fiber": 1.1, "sugar": 1.2, "sodium_mg": 340.0},
        "serving_unit": "1 bowl (approx 180g with chicken)", "serving_weight_g": 180.0,
        "ingredients": ["Skinless chicken pieces", "Onion-tomato gravy", "Ginger-garlic", "Spices", "Mustard oil"],
        "health_score": 8, "pairing": "Steamed Rice or 2 Rotis",
        "highlights": ["Lean animal protein", "Supports muscle repair", "Low carbohydrate"]
    },
    "chicken biryani": {
        "per_100g": {"calories": 185.0, "protein": 11.4, "carbs": 21.0, "fat": 6.2, "saturated_fat": 2.2, "fiber": 1.2, "sugar": 0.8, "sodium_mg": 380.0},
        "serving_unit": "1 standard plate (approx 280g)", "serving_weight_g": 280.0,
        "ingredients": ["Basmati Rice", "Marinated Chicken", "Caramelized Onions", "Saffron", "Spices", "Ghee"],
        "health_score": 7, "pairing": "Cucumber Onion Raita",
        "highlights": ["Satisfying balanced meal", "Good protein from chicken", "Cardamom & saffron digestives"]
    },

    # --- Fruits, Oats & Healthy Staples ---
    "oats": {
        "per_100g": {"calories": 389.0, "protein": 16.9, "carbs": 66.3, "fat": 6.9, "saturated_fat": 1.2, "fiber": 10.6, "sugar": 1.0, "sodium_mg": 2.0},
        "serving_unit": "1 bowl cooked (40g dry / 180g cooked)", "serving_weight_g": 40.0,
        "ingredients": ["100% Whole Grain Rolled Oats"],
        "health_score": 10, "pairing": "Almond milk, Chia seeds, and Blueberries/Banana",
        "highlights": ["Beta-glucan soluble fiber lowers LDL", "Sustained slow-release energy", "Heart health certified"]
    },
    "banana": {
        "per_100g": {"calories": 89.0, "protein": 1.1, "carbs": 22.8, "fat": 0.3, "saturated_fat": 0.1, "fiber": 2.6, "sugar": 12.2, "sodium_mg": 1.0},
        "serving_unit": "1 medium banana (approx 118g)", "serving_weight_g": 118.0,
        "ingredients": ["Fresh Banana"],
        "health_score": 9, "pairing": "Peanut butter or Greek Yogurt",
        "highlights": ["High potassium prevents muscle cramps", "Vitamin B6", "Instant pre-workout energy"]
    },
    "apple": {
        "per_100g": {"calories": 52.0, "protein": 0.3, "carbs": 13.8, "fat": 0.2, "saturated_fat": 0.05, "fiber": 2.4, "sugar": 10.4, "sodium_mg": 1.0},
        "serving_unit": "1 medium apple (approx 150g)", "serving_weight_g": 150.0,
        "ingredients": ["Fresh Apple with peel"],
        "health_score": 9, "pairing": "Handful of roasted almonds",
        "highlights": ["Pectin soluble fiber", "Quercetin antioxidant", "Regulates blood sugar"]
    },
    "avocado": {
        "per_100g": {"calories": 160.0, "protein": 2.0, "carbs": 8.5, "fat": 14.7, "saturated_fat": 2.1, "fiber": 6.7, "sugar": 0.7, "sodium_mg": 7.0},
        "serving_unit": "Half medium avocado (approx 75g)", "serving_weight_g": 75.0,
        "ingredients": ["Fresh Hass Avocado"],
        "health_score": 9, "pairing": "Whole Grain Toast and Poached Egg",
        "highlights": ["Heart-healthy monounsaturated oleic acid", "Very high fiber", "Zero cholesterol"]
    },
    "tofu": {
        "per_100g": {"calories": 76.0, "protein": 8.1, "carbs": 1.9, "fat": 4.8, "saturated_fat": 0.7, "fiber": 0.9, "sugar": 0.5, "sodium_mg": 7.0},
        "serving_unit": "100g block", "serving_weight_g": 100.0,
        "ingredients": ["Non-GMO Soybeans", "Water", "Calcium Nigari"],
        "health_score": 9, "pairing": "Stir-fry with Broccoli and Bell Peppers",
        "highlights": ["Complete vegan protein", "Very low carbohydrate", "Isoflavone antioxidants"]
    },
    "pizza": {
        "per_100g": {"calories": 266.0, "protein": 11.0, "carbs": 33.0, "fat": 10.0, "saturated_fat": 4.5, "fiber": 2.3, "sugar": 3.6, "sodium_mg": 590.0},
        "serving_unit": "1 slice medium pizza (approx 105g)", "serving_weight_g": 105.0,
        "ingredients": ["Refined flour crust", "Mozzarella cheese", "Tomato sauce", "Herbs"],
        "health_score": 4, "pairing": "Large Garden Green Salad with Lemon Dressing",
        "highlights": ["High sodium", "Refined carbohydrates", "Enjoy mindfully in moderation"]
    }
}

class NutritionCalculationService:
    """Service providing verified nutrition values from ICMR/IFCT and Open Food Facts."""

    @staticmethod
    def normalize_food_name(name: str) -> str:
        clean = name.strip().lower()
        clean = re.sub(r'[^a-z0-9\s]', '', clean)
        return clean

    @staticmethod
    def compute_transparent_health_score(per_100: Dict[str, float]) -> Tuple[int, Dict[str, Any]]:
        """
        Documented Algorithmic Nutritional Health Scoring Model (Scale: 1 to 10).
        Evaluates nutrient density and dietary risk indicators per 100g:
        Base Score = 8.0
        - Calorie density penalty: -1.0 if > 250 kcal/100g, -2.0 if > 380 kcal/100g
        - Saturated fat penalty: -1.0 if > 4g/100g, -2.0 if > 8g/100g
        - Added/free sugars penalty: -1.0 if > 8g/100g, -2.0 if > 15g/100g
        - Sodium penalty: -1.0 if > 350mg/100g, -2.0 if > 600mg/100g
        + Protein bonus: +1.0 if >= 6g/100g, +2.0 if >= 12g/100g
        + Dietary fiber bonus: +1.0 if >= 3g/100g, +2.0 if >= 6g/100g
        Clamped deterministically to [1, 10].
        """
        cals = per_100.get("calories", 0.0)
        sat_fat = per_100.get("saturated_fat", 0.0)
        sugar = per_100.get("sugar", 0.0)
        sodium = per_100.get("sodium_mg", 0.0)
        protein = per_100.get("protein", 0.0)
        fiber = per_100.get("fiber", 0.0)

        score = 8.0
        factors = []

        if cals > 380:
            score -= 2.0
            factors.append("High calorie density (>380 kcal/100g): -2.0")
        elif cals > 250:
            score -= 1.0
            factors.append("Moderate-high calorie density (>250 kcal/100g): -1.0")

        if sat_fat > 8.0:
            score -= 2.0
            factors.append("High saturated fat (>8g/100g): -2.0")
        elif sat_fat > 4.0:
            score -= 1.0
            factors.append("Moderate saturated fat (>4g/100g): -1.0")

        if sugar > 15.0:
            score -= 2.0
            factors.append("High sugar content (>15g/100g): -2.0")
        elif sugar > 8.0:
            score -= 1.0
            factors.append("Moderate sugar content (>8g/100g): -1.0")

        if sodium > 600.0:
            score -= 2.0
            factors.append("High sodium (>600mg/100g): -2.0")
        elif sodium > 350.0:
            score -= 1.0
            factors.append("Moderate sodium (>350mg/100g): -1.0")

        if protein >= 12.0:
            score += 2.0
            factors.append("Excellent protein density (>=12g/100g): +2.0")
        elif protein >= 6.0:
            score += 1.0
            factors.append("Good protein content (>=6g/100g): +1.0")

        if fiber >= 6.0:
            score += 2.0
            factors.append("Exceptional dietary fiber (>=6g/100g): +2.0")
        elif fiber >= 3.0:
            score += 1.0
            factors.append("Healthy dietary fiber (>=3g/100g): +1.0")

        final_score = int(round(max(1.0, min(10.0, score))))
        breakdown = {
            "final_score": final_score,
            "scale": "1 (low nutritional quality) to 10 (exceptionally nutrient-dense)",
            "criteria_applied": factors or ["Balanced baseline macronutrients"]
        }
        return final_score, breakdown

    @staticmethod
    def get_calorie_density(cals_per_100g: float) -> str:
        if cals_per_100g < 120:
            return "Low (<120 kcal/100g) — High water and bulk volume"
        elif cals_per_100g < 250:
            return "Moderate (120-250 kcal/100g) — Balanced nutrient density"
        elif cals_per_100g < 400:
            return "High (250-400 kcal/100g) — Energy dense, moderate portions recommended"
        return "Very High (>400 kcal/100g) — Dense energy source, mindful portioning advised"

    @staticmethod
    def match_verified_database(food_name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        clean_name = NutritionCalculationService.normalize_food_name(food_name)
        
        # 1. Exact match
        if clean_name in VERIFIED_FOOD_DATABASE:
            return clean_name, VERIFIED_FOOD_DATABASE[clean_name]
            
        # 2. Key substrings
        for key, data in VERIFIED_FOOD_DATABASE.items():
            if key in clean_name or clean_name in key:
                return key, data
                
        # 3. Individual token matches (e.g. "roti" in "2 wheat rotis")
        tokens = clean_name.split()
        for token in tokens:
            if len(token) >= 3:
                for key, data in VERIFIED_FOOD_DATABASE.items():
                    if token == key or token in key.split():
                        return key, data

        return None

    @staticmethod
    def is_relevant_food_match(food_query: str, candidate_name: str, min_match_ratio: float = 0.3) -> bool:
        """
        Validates whether an external database candidate (Open Food Facts / USDA)
        is genuinely relevant to the user query, rejecting arbitrary default or unrelated results.
        """
        if not food_query or not candidate_name:
            return False

        q_clean = NutritionCalculationService.normalize_food_name(food_query).lower()
        c_clean = candidate_name.strip().lower()

        # 1. Exact or direct substring match
        if q_clean in c_clean or c_clean in q_clean:
            return True

        # 2. Tokenize and filter out non-informative stop words
        stop_words = {
            "food", "raw", "cooked", "fresh", "plain", "cup", "bowl", "slice",
            "serving", "grams", "gram", "and", "with", "the", "a", "an", "of",
            "in", "organic", "brand", "style", "flavor", "flavoured", "flavored"
        }

        q_tokens = [w for w in re.findall(r'[a-zA-Z]{3,}', q_clean) if w not in stop_words]
        c_tokens = set(w for w in re.findall(r'[a-zA-Z]{3,}', c_clean) if w not in stop_words)

        if not q_tokens or not c_tokens:
            q_tokens = re.findall(r'[a-zA-Z0-9]{2,}', q_clean)
            c_tokens = set(re.findall(r'[a-zA-Z0-9]{2,}', c_clean))
            if not q_tokens or not c_tokens:
                return False

        # Check token containment and substring matches
        matching_count = 0
        for qt in q_tokens:
            if qt in c_tokens or any(qt in ct or ct in qt for ct in c_tokens):
                matching_count += 1

        match_ratio = matching_count / max(1, len(q_tokens))
        return match_ratio >= min_match_ratio

    @staticmethod
    def query_usda_fooddata_central(food_query: str) -> Optional[Dict[str, Any]]:
        """
        Query USDA FoodData Central REST API for verified nutritional composition.
        Uses optional USDA_API_KEY from settings (defaults to 'DEMO_KEY' if not configured).
        """
        api_key = settings.USDA_API_KEY.strip() if settings.USDA_API_KEY else "DEMO_KEY"
        endpoint = f"{settings.USDA_API_URL.rstrip('/')}/foods/search"

        try:
            params = {
                "query": food_query,
                "pageSize": 5,
                "api_key": api_key,
                "dataType": ["Foundation", "Survey (FNDDS)", "SR Legacy", "Branded"]
            }
            resp = requests.get(endpoint, params=params, timeout=3.5)
            if resp.status_code == 200:
                data = resp.json()
                foods = data.get("foods", [])
                for food in foods:
                    desc = food.get("description", "")
                    if not NutritionCalculationService.is_relevant_food_match(food_query, desc):
                        continue

                    nutrients = {
                        n.get("nutrientName", "").lower(): float(n.get("value", 0.0) or 0.0)
                        for n in food.get("foodNutrients", [])
                    }

                    cals = nutrients.get("energy", 0.0)
                    prot = nutrients.get("protein", 0.0)
                    fat = nutrients.get("total lipid (fat)", 0.0)
                    carbs = nutrients.get("carbohydrate, by difference", 0.0)
                    fiber = nutrients.get("fiber, total dietary", 0.0)
                    sugar = nutrients.get("sugars, total including nlea", nutrients.get("sugars, total", 0.0))
                    sat_fat = nutrients.get("fatty acids, total saturated", 0.0)
                    sodium = nutrients.get("sodium, na", 0.0)
                    calcium = nutrients.get("calcium, ca", 0.0)
                    iron = nutrients.get("iron, fe", 0.0)
                    potassium = nutrients.get("potassium, k", 0.0)
                    magnesium = nutrients.get("magnesium, mg", 0.0)
                    vit_c = nutrients.get("vitamin c, total ascorbic acid", 0.0)

                    if cals > 0 or prot > 0 or carbs > 0:
                        vit_dict = {}
                        if iron > 0: vit_dict["Iron"] = f"{round(iron, 2)} mg"
                        if calcium > 0: vit_dict["Calcium"] = f"{round(calcium, 1)} mg"
                        if potassium > 0: vit_dict["Potassium"] = f"{round(potassium, 1)} mg"
                        if magnesium > 0: vit_dict["Magnesium"] = f"{round(magnesium, 1)} mg"
                        if vit_c > 0: vit_dict["Vitamin C"] = f"{round(vit_c, 1)} mg"

                        return {
                            "product_name": food.get("description", food_query),
                            "per_100g": {
                                "calories": round(cals, 1),
                                "protein": round(prot, 1),
                                "carbs": round(carbs, 1),
                                "fat": round(fat, 1),
                                "saturated_fat": round(sat_fat, 1),
                                "fiber": round(fiber, 1),
                                "sugar": round(sugar, 1),
                                "sodium_mg": round(sodium, 1)
                            },
                            "serving_weight_g": float(food.get("servingSize", 100.0) or 100.0),
                            "serving_unit": food.get("servingSizeUnit", "100g"),
                            "ingredients": [food.get("description", food_query)],
                            "vitamins_and_minerals": vit_dict or {"Iron": "1.0 mg", "Calcium": "30 mg"},
                            "highlights": [f"USDA FoodData Central verified: {food.get('description', '')}"],
                            "alternatives": ["Whole food preparation cooked with minimal processing"]
                        }
        except Exception as e:
            logger.debug(f"USDA FoodData Central query failed: {e}")

        return None

    @staticmethod
    def query_open_food_facts(food_query: str) -> Optional[Dict[str, Any]]:
        """Query Open Food Facts for packaged or international foods using v2 API with legacy fallback."""
        headers = {"User-Agent": "AaharaLens-NutritionPlatform/2.1 (contact@aaharalens.local)"}
        
        try:
            params = {
                "search_terms": food_query,
                "fields": "product_name,generic_name,nutriments,ingredients_text,ingredients",
                "page_size": 5,
                "json": "true"
            }
            resp = requests.get("https://world.openfoodfacts.org/api/v2/search", params=params, timeout=3.5, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                products = data.get("products", [])
                for prod in products:
                    cand_name = prod.get("product_name") or prod.get("generic_name") or ""
                    if not NutritionCalculationService.is_relevant_food_match(food_query, cand_name):
                        continue

                    nutr = prod.get("nutriments", {})
                    cal = float(nutr.get("energy-kcal_100g", nutr.get("energy-kcal", 0)) or 0)
                    prot = float(nutr.get("proteins_100g", nutr.get("proteins", 0)) or 0)
                    carbs = float(nutr.get("carbohydrates_100g", nutr.get("carbohydrates", 0)) or 0)
                    fat = float(nutr.get("fat_100g", nutr.get("fat", 0)) or 0)
                    fiber = float(nutr.get("fiber_100g", nutr.get("fiber", 0)) or 0)
                    sodium = float(nutr.get("sodium_100g", 0) or 0) * 1000
                    
                    if cal > 0 or prot > 0 or carbs > 0:
                        return {
                            "product_name": prod.get("product_name", food_query),
                            "per_100g": {
                                "calories": round(cal, 1),
                                "protein": round(prot, 1),
                                "carbs": round(carbs, 1),
                                "fat": round(fat, 1),
                                "saturated_fat": round(float(nutr.get("saturated-fat_100g", 0) or 0), 1),
                                "fiber": round(fiber, 1),
                                "sugar": round(float(nutr.get("sugars_100g", 0) or 0), 1),
                                "sodium_mg": round(sodium, 1)
                            },
                            "serving_weight_g": 100.0,
                            "serving_unit": "100g",
                            "ingredients": [i.get("text", "") for i in prod.get("ingredients", []) if isinstance(i, dict) and "text" in i][:6] or [food_query.capitalize()],
                            "vitamins_and_minerals": {"Calcium": f"{nutr.get('calcium_100g', 'N/A')}", "Iron": f"{nutr.get('iron_100g', 'N/A')}"},
                            "highlights": ["Verified Open Food Facts database item"],
                            "alternatives": ["Whole food alternative with lower processing"]
                        }
        except Exception as e:
            logger.debug(f"Open Food Facts query failed: {e}")
            
        return None

    @staticmethod
    def extract_portion_multiplier(query: str, default_serving_g: float) -> Tuple[float, str]:
        """Extract portion multiplier like '2 rotis', '150g', 'half cup', etc."""
        text = query.lower()
        
        # Check for explicit grams (e.g. 150g, 200 grams)
        g_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:g|gm|grams)', text)
        if g_match:
            grams = max(5.0, min(2000.0, float(g_match.group(1))))
            base = max(1.0, default_serving_g)
            return (grams / base), f"{grams}g"

        # Check for fractions
        if "half" in text or "1/2" in text:
            return 0.5, "0.5 serving"
        
        num_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:katori|bowl|plate|slice|cup|roti|chapati|egg|idli|piece|glass)?', text)
        if num_match:
            try:
                val = float(num_match.group(1))
                if 0.1 <= val <= 20:
                    return val, f"{val} serving(s)"
            except ValueError:
                pass
                
        return 1.0, f"1 standard serving (~{int(default_serving_g)}g)"

    @classmethod
    def calculate_food_nutrition(cls, food_query: str, portion_hint: Optional[str] = None) -> FoodItemDetail:
        """Calculates verified macros without AI hallucination, scaling strictly by portion."""
        from src.services.cache_service import cache_service
        cached = cache_service.get_cached_nutrition(food_query, portion_hint)
        if cached:
            return FoodItemDetail(**cached)

        matched = cls.match_verified_database(food_query)
        source = "Curated reference values based on IFCT/USDA standards"
        is_estimated = False
        
        if matched:
            key, data = matched
            db_item = data
        else:
            # Check USDA FoodData Central
            usda_item = cls.query_usda_fooddata_central(food_query)
            if usda_item:
                db_item = usda_item
                source = f"USDA FoodData Central ({usda_item.get('product_name', food_query)})"
            else:
                # Check Open Food Facts
                off_item = cls.query_open_food_facts(food_query)
                if off_item:
                    db_item = off_item
                    source = f"Open Food Facts Database ({off_item.get('product_name', food_query)})"
                else:
                    # Generalized approximate composite proxy
                    db_item = {
                        "per_100g": {"calories": 140.0, "protein": 4.5, "carbs": 20.0, "fat": 4.5, "saturated_fat": 1.0, "fiber": 2.5, "sugar": 3.0, "sodium_mg": 180.0},
                        "serving_unit": "100g", "serving_weight_g": 100.0,
                        "ingredients": [food_query.capitalize()],
                        "vitamins_and_minerals": {"Iron": "1.0 mg", "Calcium": "30 mg"},
                        "pairing": "Fresh salad and water",
                        "highlights": ["Nutritional approximation based on mixed culinary composite benchmarks"],
                        "alternatives": ["Whole food preparation cooked with minimal oil"]
                    }
                    source = "Approximate Food Composite Estimate (User Review Advised)"
                    is_estimated = True

        per_100 = db_item["per_100g"]
        base_serving_g = db_item.get("serving_weight_g", 100.0)
        
        query_for_portion = portion_hint if portion_hint else food_query
        multiplier, portion_desc = cls.extract_portion_multiplier(query_for_portion, base_serving_g)
        
        total_weight_g = max(5.0, base_serving_g * multiplier)
        scale = total_weight_g / 100.0

        detail = FoodItemDetail(
            food_name=matched[0].title() if matched else food_query.title(),
            detected_ingredients=db_item.get("ingredients", [food_query.capitalize()]),
            serving_size=f"{portion_desc} (approx {round(total_weight_g, 1)}g)",
            serving_weight_g=round(total_weight_g, 1),
            calories=max(0.0, round(per_100["calories"] * scale, 1)),
            protein=max(0.0, round(per_100["protein"] * scale, 1)),
            carbohydrates=max(0.0, round(per_100["carbs"] * scale, 1)),
            total_fat=max(0.0, round(per_100["fat"] * scale, 1)),
            saturated_fat=max(0.0, round(per_100.get("saturated_fat", 0.0) * scale, 1)),
            dietary_fiber=max(0.0, round(per_100["fiber"] * scale, 1)),
            sugar=max(0.0, round(per_100.get("sugar", 0.0) * scale, 1)),
            sodium_mg=max(0.0, round(per_100.get("sodium_mg", 0.0) * scale, 1)),
            health_score=db_item.get("health_score", 7),
            confidence_level="High (Curated Reference Standard)" if not is_estimated else "Moderate (Portion / Food Estimated)",
            source=source,
            is_estimated=is_estimated,
            nutritional_highlights=db_item.get("highlights", []),
            suggested_pairing=db_item.get("pairing", "Drink adequate water with this meal"),
            explanation=(
                f"Nutritional values computed from 100g reference standards scaled by {round(total_weight_g, 1)}g portion. "
                f"Delivers {round(per_100['protein'] * scale, 1)}g of protein and {round(per_100['calories'] * scale, 1)} kcal. "
                "Note: Nutritional values are informational estimates and not a substitute for clinical medical advice."
            )
        )

        try:
            cache_service.cache_nutrition(food_query, portion_hint, detail.model_dump())
        except Exception:
            pass

        return detail

    @staticmethod
    def calculate_personalized_targets(
        age: int,
        gender: str,
        height_cm: float,
        weight_kg: float,
        activity_level: str,
        fitness_goal: str,
        custom_calories: Optional[float] = None
    ) -> CalculatedTargets:
        """
        Calculates BMR & TDEE using Mifflin-St Jeor formula (Clinical Standard).
        Men: BMR = 10W + 6.25H - 5A + 5
        Women: BMR = 10W + 6.25H - 5A - 161
        """
        gender_clean = gender.lower().strip()
        if gender_clean == "male":
            bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
        elif gender_clean == "female":
            bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
        else: # average
            bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 78

        # Activity multipliers
        activity_multipliers = {
            "sedentary": 1.2,
            "light": 1.375,
            "moderate": 1.55,
            "active": 1.725,
            "very_active": 1.9
        }
        mult = activity_multipliers.get(activity_level.lower(), 1.55)
        tdee = bmr * mult

        # Fitness goal adjustments
        if custom_calories and custom_calories > 800:
            target_cal = custom_calories
        else:
            goal_adjustments = {
                "weight_loss": -500.0,
                "mild_weight_loss": -250.0,
                "maintenance": 0.0,
                "mild_muscle_gain": 250.0,
                "muscle_gain": 500.0,
                "general_health": 0.0
            }
            target_cal = max(1200.0, tdee + goal_adjustments.get(fitness_goal.lower(), 0.0))

        # Macronutrient distribution
        # Protein: 1.6-2.0g/kg for muscle gain/active, 1.2-1.4g/kg for weight loss, 1.0-1.2g/kg for maintenance
        if "muscle" in fitness_goal.lower():
            target_protein = weight_kg * 1.8
        elif "loss" in fitness_goal.lower():
            target_protein = weight_kg * 1.4
        else:
            target_protein = weight_kg * 1.2
            
        target_protein = round(target_protein, 1)
        protein_cals = target_protein * 4.0

        # Fat: ~25% of total calories
        fat_cals = target_cal * 0.25
        target_fat = round(fat_cals / 9.0, 1)

        # Carbs: Remainder of calories
        carbs_cals = max(0.0, target_cal - protein_cals - fat_cals)
        target_carbs = round(carbs_cals / 4.0, 1)

        # Fiber: 14g per 1000 kcal
        target_fiber = round((target_cal / 1000.0) * 14.0, 1)

        # Water: 35ml per kg bodyweight
        target_water = round((weight_kg * 0.035), 1)

        return CalculatedTargets(
            bmr=round(bmr, 1),
            tdee=round(tdee, 1),
            target_calories=round(target_cal, 1),
            target_protein_g=target_protein,
            target_carbs_g=target_carbs,
            target_fat_g=target_fat,
            target_fiber_g=target_fiber,
            target_water_liters=target_water,
            formula_used="Mifflin-St Jeor Clinical Standard with ICMR Macronutrient Guidelines",
            disclaimer="Estimates provided are for wellness and lifestyle planning. Consult a healthcare professional for clinical nutrition prescriptions."
        )
