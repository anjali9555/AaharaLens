import pytest
import json
import gc
from unittest.mock import MagicMock
from src.services.ai_service import ai_service
from src.core.limiter import limiter

# Disable rate limiter for unit/integration route tests by default
limiter.enabled = False

@pytest.fixture(autouse=True)
def clean_memory_after_test():
    """Reclaims memory and garbage-collects large test buffers automatically."""
    yield
    gc.collect()

@pytest.fixture(autouse=True)
def mock_groq_llm(monkeypatch):
    """Mocks external AI API calls so tests run offline and fast."""
    def fake_call_llm(messages, json_mode=True, max_tokens=1500):
        # Inspect system prompt to provide tailored mock response
        sys_content = messages[0]["content"] if messages else ""
        user_content = messages[-1]["content"] if messages else ""

        if "parsing engine" in sys_content or "Parse the following" in str(user_content):
            return json.dumps({
                "items": [
                    {"food_name": "Roti", "portion": "2 rotis"},
                    {"food_name": "Dal Tadka", "portion": "1 bowl"}
                ],
                "meal_summary": "Balanced meal of whole grains and lentils.",
                "recommendations": ["Add a lemon slice", "Include fresh greens"]
            })
        elif "replacement" in str(user_content).lower() or "regenerate" in str(user_content).lower():
            return json.dumps({
                "dish_name": "Warm Spiced Oats Porridge",
                "portion_size": "1 bowl (200g)",
                "calories": 280.0,
                "protein_g": 11.0,
                "carbs_g": 48.0,
                "fat_g": 6.0,
                "fiber_g": 7.0,
                "key_ingredients": ["Rolled oats", "Almond milk", "Cinnamon", "Flaxseeds"],
                "why_recommended": "Easily digestible wholesome warm breakfast.",
                "affordable_substitute": "Vegetable Dalia"
            })
        elif "substitution" in sys_content or "substitute" in str(user_content).lower():
            return json.dumps({
                "substitutions": [
                    {
                        "substitute_name": "Tofu Scramble",
                        "why_it_works": "High plant protein",
                        "macro_difference": "Lower calories",
                        "culinary_tips": "Cook with turmeric and black pepper",
                        "calories": 140.0,
                        "protein": 14.0,
                        "carbs": 3.0,
                        "fat": 8.0
                    }
                ]
            })
        elif "decision engine" in sys_content:
            return "Based on your remaining macros, consider having 150g grilled paneer and a green salad."
        elif json_mode:
            return json.dumps({
                "summary": "Mocked test response",
                "recommendations": ["Follow standard nutrition"]
            })
        else:
            return "Oats are packed with beta-glucan soluble fiber which actively binds cholesterol in the digestive tract.\n\nFollow-up: What is a high-protein recipe for oats?\nFollow-up: How do oats fit into a diabetic diet?"

    monkeypatch.setattr(ai_service, "_call_llm", fake_call_llm)
