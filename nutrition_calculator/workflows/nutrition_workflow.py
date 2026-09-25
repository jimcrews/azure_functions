"""Fan-out / fan-in: look up every ingredient in parallel, then combine the results.

    get_meal_ingredients
            |
      +-----+------+------+        fan out: one lookup per ingredient, all at once
      v     v      v      v
    lookup lookup lookup lookup     (lookup_ingredient_nutrition)
      +-----+------+------+
            |                       fan in: context.task_all waits for every lookup
            v
    total_nutrition

Orchestrator code is replayed by the framework, so it must be deterministic:
no random numbers, no datetime.now(), no I/O. Put that in activities.
"""

import asyncio
import logging

import azure.durable_functions as df

bp = df.Blueprint()
logger = logging.getLogger(__name__)

API_LATENCY_SECONDS = 2  # pretend each nutrition API call takes a while

MEALS = {
    "spaghetti": ["pasta", "tomato", "beef", "onion"],
    "salad": ["lettuce", "tomato", "cucumber", "olive oil", "feta"],
    "omelette": ["egg", "cheese", "spinach", "butter"],
}

# Fake "API" data: per-serving values.
NUTRITION_DB = {
    "pasta": {"calories": 200, "protein_g": 7, "carbs_g": 42, "fat_g": 1},
    "tomato": {"calories": 22, "protein_g": 1, "carbs_g": 5, "fat_g": 0},
    "beef": {"calories": 250, "protein_g": 26, "carbs_g": 0, "fat_g": 15},
    "onion": {"calories": 44, "protein_g": 1, "carbs_g": 10, "fat_g": 0},
    "lettuce": {"calories": 8, "protein_g": 1, "carbs_g": 2, "fat_g": 0},
    "cucumber": {"calories": 16, "protein_g": 1, "carbs_g": 4, "fat_g": 0},
    "olive oil": {"calories": 119, "protein_g": 0, "carbs_g": 0, "fat_g": 14},
    "feta": {"calories": 75, "protein_g": 4, "carbs_g": 1, "fat_g": 6},
    "egg": {"calories": 78, "protein_g": 6, "carbs_g": 1, "fat_g": 5},
    "cheese": {"calories": 113, "protein_g": 7, "carbs_g": 0, "fat_g": 9},
    "spinach": {"calories": 7, "protein_g": 1, "carbs_g": 1, "fat_g": 0},
    "butter": {"calories": 102, "protein_g": 0, "carbs_g": 0, "fat_g": 12},
}
UNKNOWN_INGREDIENT = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}


@bp.orchestration_trigger(context_name="context")
def nutrition_orchestrator(context: df.DurableOrchestrationContext):
    meal: str = context.get_input() or "spaghetti"

    # Step 1 (chained): find out which ingredients the meal needs.
    ingredients = yield context.call_activity("get_meal_ingredients", meal)

    # Step 2 (fan out): schedule one lookup per ingredient. Nothing is awaited
    # yet, so every lookup starts immediately and they run in parallel.
    lookups = [
        context.call_activity("lookup_ingredient_nutrition", ingredient)
        for ingredient in ingredients
    ]

    # Step 3 (fan in): task_all waits until ALL lookups finish and returns their
    # results as a list, in the same order as `lookups`.
    per_ingredient = yield context.task_all(lookups)

    # Step 4: combine the results.
    return (yield context.call_activity("total_nutrition", {
        "meal": meal,
        "items": per_ingredient,
    }))


@bp.activity_trigger(input_name="meal")
def get_meal_ingredients(meal: str) -> list:
    logger.info("Looking up ingredients for %s", meal)
    # Unknown meals fall back to a default so the demo never fails on input.
    return MEALS.get(meal, ["mystery vegetable", "salt", "water"])


# async so many lookups can wait on their "API" at the same time.
@bp.activity_trigger(input_name="ingredient")
async def lookup_ingredient_nutrition(ingredient: str) -> dict:
    logger.info("Calling nutrition API for %s", ingredient)
    await asyncio.sleep(API_LATENCY_SECONDS)
    logger.info("Nutrition API returned for %s", ingredient)
    return {"ingredient": ingredient, **NUTRITION_DB.get(ingredient, UNKNOWN_INGREDIENT)}


@bp.activity_trigger(input_name="meal_data")
def total_nutrition(meal_data: dict) -> dict:
    items = meal_data["items"]
    totals = {
        key: sum(item[key] for item in items)
        for key in ("calories", "protein_g", "carbs_g", "fat_g")
    }
    return {"meal": meal_data["meal"], "ingredients": items, "totals": totals}
