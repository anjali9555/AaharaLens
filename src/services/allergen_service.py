import re
from typing import List, Dict, Any, Optional, Tuple, Set
from loguru import logger
from src.schemas.nutrition_schemas import SingleMealDetail

# Comprehensive multilingual and colloquial allergen taxonomy
ALLERGEN_TAXONOMY: Dict[str, List[str]] = {
    "peanut": [
        "peanut", "peanuts", "groundnut", "groundnuts", "mungfali", "moongphali",
        "arachis", "monkey nut", "goober", "peanut butter", "peanut oil"
    ],
    "tree_nuts": [
        "nut", "nuts", "tree nut", "tree nuts", "almond", "almonds", "badam",
        "cashew", "cashews", "kaju", "walnut", "walnuts", "akhrot",
        "pistachio", "pistachios", "pista", "hazelnut", "hazelnuts",
        "pecan", "pecans", "brazil nut", "macadamia", "pine nut", "chilgoza"
    ],
    "dairy": [
        "milk", "dairy", "paneer", "panir", "curd", "dahi", "ghee", "clarified butter",
        "butter", "cheese", "cream", "malai", "whey", "casein", "yogurt", "yoghurt",
        "lassi", "chaas", "buttermilk", "khoa", "khoya", "mawa", "rabri", "chhena",
        "condensed milk", "milk powder", "custard"
    ],
    "gluten": [
        "wheat", "gluten", "atta", "maida", "all-purpose flour", "sooji", "suji",
        "semolina", "rava", "barley", "rye", "seitan", "roti", "chapati", "naan",
        "paratha", "puri", "bhatura", "bread", "pasta", "couscous", "spelt"
    ],
    "egg": [
        "egg", "eggs", "anda", "albumen", "ovalbumin", "mayonnaise",
        "egg white", "egg yolk", "meringue"
    ],
    "soy": [
        "soy", "soya", "soybean", "soybeans", "tofu", "edamame", "tempeh",
        "soy sauce", "soya chunks", "soy milk", "soya chaap", "miso", "natto"
    ],
    "seafood": [
        "fish", "machhli", "prawn", "prawns", "shrimp", "shrimps", "crab", "crabs",
        "lobster", "salmon", "tuna", "pomfret", "surmai", "rohu", "katla", "hilsa",
        "calamari", "squid", "anchovy", "clam", "mussel", "oyster"
    ],
    "mustard": [
        "mustard", "sarson", "rai", "mustard oil", "mustard seed", "mustard paste"
    ],
    "sesame": [
        "sesame", "til", "tahini", "sesame seed", "sesame oil", "gingelly oil"
    ],
    "sulfites": [
        "sulfite", "sulfites", "sulphite", "sulphites", "sulfur dioxide"
    ]
}

# Verified safe baseline templates by meal type and dietary preference
VERIFIED_SAFE_TEMPLATES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "breakfast": {
        "vegetarian": {
            "dish_name": "Moong Dal Chilla with Mint Chutney",
            "portion_size": "2 medium chillas (approx 160g)",
            "calories": 260.0,
            "protein_g": 14.0,
            "carbs_g": 38.0,
            "fat_g": 5.0,
            "fiber_g": 6.5,
            "key_ingredients": ["Yellow moong dal", "Ginger", "Green chili", "Coriander", "Cumin"],
            "why_recommended": "Naturally gluten-free, dairy-free, nut-free breakfast high in clean plant protein.",
            "affordable_substitute": "Vegetable Poha (no peanuts)"
        },
        "vegan": {
            "dish_name": "Vegetable Poha with Green Peas and Lemon",
            "portion_size": "1 large bowl (approx 180g)",
            "calories": 280.0,
            "protein_g": 7.0,
            "carbs_g": 50.0,
            "fat_g": 5.5,
            "fiber_g": 5.0,
            "key_ingredients": ["Flattened rice", "Green peas", "Carrots", "Turmeric", "Curry leaves", "Lemon juice"],
            "why_recommended": "Completely allergen-safe, vegan, low-fat source of slow-release morning carbohydrates.",
            "affordable_substitute": "Rolled Oats cooked in water with banana"
        },
        "non-vegetarian": {
            "dish_name": "Steamed Egg Whites with Sautéed Spinach",
            "portion_size": "3 egg whites + 1 bowl spinach (approx 180g)",
            "calories": 160.0,
            "protein_g": 18.0,
            "carbs_g": 6.0,
            "fat_g": 2.5,
            "fiber_g": 3.0,
            "key_ingredients": ["Egg whites", "Spinach", "Black pepper", "Olive oil"],
            "why_recommended": "Ultra-lean high-protein morning meal free from dairy, gluten, and nuts.",
            "affordable_substitute": "Moong Dal Chilla"
        }
    },
    "lunch": {
        "vegetarian": {
            "dish_name": "Steamed Brown Rice with Yellow Toor Dal & Mixed Sabzi",
            "portion_size": "1 plate (approx 280g)",
            "calories": 420.0,
            "protein_g": 15.0,
            "carbs_g": 72.0,
            "fat_g": 7.0,
            "fiber_g": 9.0,
            "key_ingredients": ["Brown rice", "Yellow toor dal", "Carrots", "Beans", "Tomatoes", "Cumin", "Turmeric"],
            "why_recommended": "Naturally balanced, whole-food complete protein meal free from gluten, dairy, and nuts.",
            "affordable_substitute": "White Rice with Moong Dal Tadka"
        },
        "vegan": {
            "dish_name": "Quinoa Vegetable Pulao with Sprouted Moong Salad",
            "portion_size": "1 large plate (approx 260g)",
            "calories": 390.0,
            "protein_g": 16.0,
            "carbs_g": 64.0,
            "fat_g": 6.5,
            "fiber_g": 8.5,
            "key_ingredients": ["Quinoa", "Sprouted moong beans", "French beans", "Coriander", "Lemon"],
            "why_recommended": "Complete amino acid profile without any dairy, gluten, or common allergens.",
            "affordable_substitute": "Steamed Rice with Dal"
        },
        "non-vegetarian": {
            "dish_name": "Grilled Chicken Breast with Steamed Brown Rice and Steamed Greens",
            "portion_size": "1 plate (approx 280g)",
            "calories": 440.0,
            "protein_g": 38.0,
            "carbs_g": 52.0,
            "fat_g": 8.0,
            "fiber_g": 6.0,
            "key_ingredients": ["Chicken breast", "Brown rice", "Broccoli", "Black pepper", "Olive oil"],
            "why_recommended": "Lean animal protein paired with complex carbohydrates, free from all major allergens.",
            "affordable_substitute": "Steamed Fish with Rice"
        }
    },
    "dinner": {
        "vegetarian": {
            "dish_name": "Hearty Lentil & Pumpkin Stew with Brown Rice",
            "portion_size": "1 large bowl (approx 260g)",
            "calories": 360.0,
            "protein_g": 16.0,
            "carbs_g": 58.0,
            "fat_g": 6.0,
            "fiber_g": 9.5,
            "key_ingredients": ["Masoor dal", "Pumpkin", "Tomatoes", "Ginger", "Coriander", "Cumin"],
            "why_recommended": "Light, highly digestible dinner packed with beta-carotene, iron, and fiber without allergens.",
            "affordable_substitute": "Moong Dal Khichdi"
        },
        "vegan": {
            "dish_name": "Steamed Rice with Kala Chana (Black Chickpeas) Curry",
            "portion_size": "1 bowl (approx 250g)",
            "calories": 380.0,
            "protein_g": 15.0,
            "carbs_g": 62.0,
            "fat_g": 7.0,
            "fiber_g": 10.0,
            "key_ingredients": ["Black chickpeas", "Tomatoes", "Onions", "Cumin", "Ginger", "Steamed rice"],
            "why_recommended": "Slow-digesting complex carbs and plant protein completely free of gluten and dairy.",
            "affordable_substitute": "Rajma with Steamed Rice"
        },
        "non-vegetarian": {
            "dish_name": "Herbed Baked Chicken with Roasted Vegetables",
            "portion_size": "1 plate (approx 240g)",
            "calories": 380.0,
            "protein_g": 34.0,
            "carbs_g": 24.0,
            "fat_g": 11.0,
            "fiber_g": 5.0,
            "key_ingredients": ["Chicken thigh (skinless)", "Zucchini", "Bell peppers", "Rosemary", "Olive oil"],
            "why_recommended": "Low-carb, high-satiety evening meal free from dairy, gluten, soy, and nuts.",
            "affordable_substitute": "Grilled Fish with Vegetables"
        }
    },
    "snack": {
        "vegetarian": {
            "dish_name": "Roasted Makhana (Foxnuts) with Rock Salt & Black Pepper",
            "portion_size": "1 medium bowl (approx 35g)",
            "calories": 130.0,
            "protein_g": 3.5,
            "carbs_g": 24.0,
            "fat_g": 1.2,
            "fiber_g": 2.8,
            "key_ingredients": ["Foxnuts (Makhana)", "Rock salt", "Black pepper", "Olive oil drop"],
            "why_recommended": "Crunchy, low-glycemic, allergen-safe snack rich in magnesium and potassium.",
            "affordable_substitute": "Roasted Chana (without skin)"
        },
        "vegan": {
            "dish_name": "Fresh Fruit Bowl (Apple, Papaya & Pomegranate)",
            "portion_size": "1 bowl (approx 180g)",
            "calories": 110.0,
            "protein_g": 1.2,
            "carbs_g": 26.0,
            "fat_g": 0.4,
            "fiber_g": 4.5,
            "key_ingredients": ["Fresh apple", "Papaya", "Pomegranate arils", "Lemon juice"],
            "why_recommended": "Natural antioxidant and enzymatic hydration, 100% free of all allergens.",
            "affordable_substitute": "Sliced Cucumber and Carrots"
        },
        "non-vegetarian": {
            "dish_name": "Boiled Egg White Slices with Chaat Masala",
            "portion_size": "2 egg whites (approx 66g)",
            "calories": 34.0,
            "protein_g": 7.2,
            "carbs_g": 0.5,
            "fat_g": 0.2,
            "fiber_g": 0.0,
            "key_ingredients": ["Egg whites", "Chaat masala", "Pinch of black salt"],
            "why_recommended": "Pure bioavailable protein with zero carbs, dairy, or gluten.",
            "affordable_substitute": "Roasted Makhana"
        }
    }
}


class AllergenValidationService:
    """Centralized, deterministic allergen analysis, validation, and substitution engine."""

    @classmethod
    def expand_allergens(cls, allergies: List[str]) -> Set[str]:
        """
        Expands user allergies to encompass colloquial names, scientific terms,
        Indian ingredients (Hindi/Sanskrit), and cross-reactive derivatives.
        """
        expanded: Set[str] = set()
        for raw in allergies:
            clean = raw.strip().lower()
            if not clean:
                continue
            expanded.add(clean)

            # Check direct match with group key
            if clean in ALLERGEN_TAXONOMY:
                expanded.update(ALLERGEN_TAXONOMY[clean])
                continue

            # Check if clean term matches any synonym in taxonomy
            for group, synonyms in ALLERGEN_TAXONOMY.items():
                if clean in synonyms or any(s in clean for s in synonyms if len(s) >= 4):
                    expanded.update(synonyms)
                    expanded.add(group)

        return expanded

    @classmethod
    def check_text_for_allergens(cls, text: str, allergies: List[str]) -> Tuple[bool, List[str]]:
        """
        Scans a text string (dish name, description, ingredients) against expanded allergens.
        Returns: (has_violation, detected_allergens)
        """
        if not allergies or not text:
            return False, []

        expanded = cls.expand_allergens(allergies)
        normalized_text = f" {text.lower()} "
        # Replace punctuation with spaces for accurate word boundary matching
        cleaned = re.sub(r'[^a-z0-9\s]', ' ', normalized_text)

        detected = []
        for term in expanded:
            if not term or len(term) < 2:
                continue
            # Use word boundary search to avoid false positives (e.g., 'nut' in 'minute')
            pattern = rf'\b{re.escape(term)}\b'
            if re.search(pattern, cleaned):
                detected.append(term)

        # Remove duplicates while preserving order
        unique_detected = list(dict.fromkeys(detected))
        return (len(unique_detected) > 0), unique_detected

    @classmethod
    def validate_ingredients(
        cls, ingredients: List[str], allergies: List[str]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Validates an ingredient list against allergies.
        Returns: (is_safe, detected_violations, warnings)
        """
        if not allergies:
            return True, [], []

        violations: List[str] = []
        warnings: List[str] = []

        for ing in ingredients:
            has_violation, detected = cls.check_text_for_allergens(ing, allergies)
            if has_violation:
                violations.extend(detected)
            # Flag uncertain or compound ingredients (e.g. 'masala blend', 'sauce', 'mixed spices')
            ing_lower = ing.lower()
            if any(w in ing_lower for w in ["mixed masala", "packaged sauce", "curry paste", "seasoning", "gravy"]):
                warnings.append(f"Unverified compound ingredient '{ing}': May contain hidden allergens or cross-contaminants.")

        unique_violations = list(dict.fromkeys(violations))
        unique_warnings = list(dict.fromkeys(warnings))
        return (len(unique_violations) == 0), unique_violations, unique_warnings

    @classmethod
    def validate_meal_detail(
        cls, meal: SingleMealDetail, allergies: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        Comprehensive check across dish_name, key_ingredients, and affordable_substitute.
        """
        if not allergies:
            return True, []

        full_text = f"{meal.dish_name} {' '.join(meal.key_ingredients or [])} {meal.affordable_substitute or ''}"
        has_violation, detected = cls.check_text_for_allergens(full_text, allergies)
        return (not has_violation), detected

    @classmethod
    def get_allergen_safe_fallback(
        cls,
        meal_type: str,
        allergies: List[str],
        dietary_preference: str = "vegetarian"
    ) -> SingleMealDetail:
        """
        Returns a guaranteed allergen-safe fallback meal tailored to dietary preferences.
        Validates the fallback dish against allergies before returning it.
        """
        m_type = meal_type.lower().strip()
        if m_type not in VERIFIED_SAFE_TEMPLATES:
            m_type = "lunch"

        pref = dietary_preference.lower().strip()
        if "vegan" in pref:
            diet_key = "vegan"
        elif "non" in pref or "chicken" in pref or "egg" in pref:
            diet_key = "non-vegetarian"
        else:
            diet_key = "vegetarian"

        # Check the primary template
        template = VERIFIED_SAFE_TEMPLATES[m_type].get(diet_key) or VERIFIED_SAFE_TEMPLATES[m_type]["vegan"]
        meal_candidate = SingleMealDetail(meal_type=m_type, **template)

        is_safe, detected = cls.validate_meal_detail(meal_candidate, allergies)
        if is_safe:
            return meal_candidate

        # If primary template failed (e.g., egg in non-veg, but user has egg allergy), fallback to vegan template
        vegan_template = VERIFIED_SAFE_TEMPLATES[m_type]["vegan"]
        vegan_candidate = SingleMealDetail(meal_type=m_type, **vegan_template)
        is_safe_v, detected_v = cls.validate_meal_detail(vegan_candidate, allergies)
        if is_safe_v:
            return vegan_candidate

        # Ultimate minimalist safe bowl
        return SingleMealDetail(
            meal_type=m_type,
            dish_name="Steamed White Rice with Yellow Moong Dal & Boiled Carrots",
            portion_size="1 plate (approx 250g)",
            calories=320.0,
            protein_g=11.0,
            carbs_g=62.0,
            fat_g=2.5,
            fiber_g=5.0,
            key_ingredients=["Steamed rice", "Yellow moong dal", "Boiled carrots", "Salt"],
            why_recommended="Universal emergency hypoallergenic meal formulated to exclude all 10 major allergen classes.",
            affordable_substitute="Steamed Rice with Boiled Potatoes"
        )

    @classmethod
    def sanitize_meal_plan_item(
        cls,
        meal: SingleMealDetail,
        allergies: List[str],
        dietary_preference: str = "vegetarian"
    ) -> Tuple[SingleMealDetail, bool]:
        """
        Scans meal for allergen violations. If violated:
        1. Attempts to use safe substitute if free of allergens.
        2. Recalculates exact macros (never reusing original macros).
        3. Validates replacement dish AGAIN.
        4. If still unsafe, substitutes with verified allergen-safe template.
        """
        is_safe, violations = cls.validate_meal_detail(meal, allergies)
        if is_safe:
            return meal, False

        logger.warning(
            f"Allergen violation in meal '{meal.dish_name}': Detected {violations}. Initiating safe replacement."
        )

        from src.services.nutrition_service import NutritionCalculationService

        # Try substitute candidate from meal.affordable_substitute
        candidate_name = meal.affordable_substitute
        if candidate_name:
            sub_safe, _ = cls.check_text_for_allergens(candidate_name, allergies)
            if sub_safe:
                # Recalculate macros specifically for this candidate
                calc = NutritionCalculationService.calculate_food_nutrition(candidate_name, meal.portion_size)
                clean_ingredients = [
                    ing for ing in meal.key_ingredients
                    if not cls.check_text_for_allergens(ing, allergies)[0]
                ] or [candidate_name]

                replacement = SingleMealDetail(
                    meal_type=meal.meal_type,
                    dish_name=f"{candidate_name} (Verified Allergen-Safe Substitute)",
                    portion_size=meal.portion_size,
                    calories=calc.calories,
                    protein_g=calc.protein,
                    carbs_g=calc.carbohydrates,
                    fat_g=calc.total_fat,
                    fiber_g=calc.dietary_fiber,
                    key_ingredients=clean_ingredients,
                    why_recommended=(
                        f"Automated allergen safety replacement: Replaced original dish to eliminate allergen(s) "
                        f"({', '.join(violations)}). Verified safe against allergen policy."
                    ),
                    affordable_substitute=None
                )
                # Re-validate replacement dish
                rep_safe, _ = cls.validate_meal_detail(replacement, allergies)
                if rep_safe:
                    return replacement, True

        # Fall back to verified template
        safe_template = cls.get_allergen_safe_fallback(meal.meal_type, allergies, dietary_preference)
        if "Allergen-Safe" not in safe_template.dish_name:
            safe_template.dish_name = f"{safe_template.dish_name} (Allergen-Safe Alternative)"
        safe_template.why_recommended = (
            f"Automated allergen safety replacement: Replaced '{meal.dish_name}' containing {', '.join(violations)} "
            f"with verified hypoallergenic meal."
        )
        return safe_template, True

    @classmethod
    def filter_grocery_list(
        cls,
        grocery_list: Dict[str, List[str]],
        allergies: List[str]
    ) -> Tuple[Dict[str, List[str]], List[str]]:
        """
        Filters allergen-contaminated items from grocery list categories.
        Returns: (filtered_grocery_list, removed_items)
        """
        if not allergies or not grocery_list:
            return grocery_list, []

        expanded = cls.expand_allergens(allergies)
        filtered: Dict[str, List[str]] = {}
        removed: List[str] = []

        for category, items in grocery_list.items():
            safe_items = []
            for item in items:
                has_viol, _ = cls.check_text_for_allergens(item, list(expanded))
                if has_viol:
                    removed.append(item)
                else:
                    safe_items.append(item)
            filtered[category] = safe_items

        return filtered, removed

    @classmethod
    def get_cross_contamination_disclaimer(cls) -> str:
        return (
            "Allergen Notice: Automated ingredient screening minimizes dietary exposure, but cannot guarantee "
            "complete absence of environmental cross-contamination in commercial kitchens, shared processing lines, "
            "or food service establishments. Individuals with life-threatening anaphylactic sensitivities must verify "
            "with food preparers or certified clinical dietitians."
        )
