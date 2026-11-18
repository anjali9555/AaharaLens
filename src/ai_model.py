"""
Legacy compatibility wrapper for ai_model.py.
Delegates to modular services in src/services/.
"""
from typing import Dict, Any
from src.services.nutrition_service import NutritionCalculationService
from src.services.rag_service import rag_service
from src.services.ai_service import ai_service

def get_nutrition_info(food_item: str) -> Dict[str, Any]:
    """Legacy helper returning nutritional breakdown dictionary."""
    detail = NutritionCalculationService.calculate_food_nutrition(food_item)
    return {
        "protein": detail.protein,
        "fat": detail.total_fat,
        "carbohydrates": detail.carbohydrates,
        "fiber": detail.dietary_fiber,
        "health_score": detail.health_score,
        "suggested_pairing": detail.suggested_pairing or "Green Salad",
        "explanation": detail.explanation
    }

def query_nutrition_knowledge(question: str) -> str:
    """Legacy helper returning RAG knowledge query answer."""
    resp = rag_service.answer_query(question)
    return resp.answer
