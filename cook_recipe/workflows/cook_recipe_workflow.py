"""Function chaining: each cooking step feeds its result into the next step.

    gather_ingredients -> prep_ingredients -> cook -> plate

The orchestrator only decides the ORDER of steps. The actual work happens in
activity functions. Orchestrator code is replayed by the framework, so it must be
deterministic: no random numbers, no datetime.now(), no I/O. Put that in activities.
"""

import logging
import time

import azure.durable_functions as df

bp = df.Blueprint()
logger = logging.getLogger(__name__)

STEP_SECONDS = 5  # pretend each step takes a while


@bp.orchestration_trigger(context_name="context")
def cook_recipe_orchestrator(context: df.DurableOrchestrationContext):
    recipe_name: str = context.get_input() or "pancakes"

    # Each call_activity is a checkpoint. If the host restarts mid-way, the
    # orchestrator replays and finished steps return their saved results
    # instead of running again.
    ingredients = yield context.call_activity("gather_ingredients", recipe_name)
    prepped = yield context.call_activity("prep_ingredients", ingredients)
    cooked = yield context.call_activity("cook", prepped)
    plated = yield context.call_activity("plate", cooked)

    return plated


@bp.activity_trigger(input_name="recipe")
def gather_ingredients(recipe: str) -> dict:
    logger.info("Gathering ingredients for %s", recipe)
    time.sleep(STEP_SECONDS)
    pantry = {
        "pancakes": ["flour", "milk", "eggs", "butter"],
        "omelette": ["eggs", "cheese", "spinach", "butter"],
    }
    return {
        "recipe": recipe,
        "ingredients": pantry.get(recipe, ["salt", "water", "mystery vegetable"]),
    }


@bp.activity_trigger(input_name="gathered")
def prep_ingredients(gathered: dict) -> dict:
    logger.info("Prepping %s", gathered["ingredients"])
    time.sleep(STEP_SECONDS)
    return {
        "recipe": gathered["recipe"],
        "prepped": [f"chopped {item}" for item in gathered["ingredients"]],
    }


@bp.activity_trigger(input_name="prepped")
def cook(prepped: dict) -> dict:
    logger.info("Cooking %s", prepped["recipe"])
    time.sleep(STEP_SECONDS)
    return {
        "recipe": prepped["recipe"],
        "cooked_from": prepped["prepped"],
        "doneness": "golden brown",
    }


@bp.activity_trigger(input_name="cooked")
def plate(cooked: dict) -> str:
    logger.info("Plating %s", cooked["recipe"])
    time.sleep(STEP_SECONDS)
    return (
        f"Your {cooked['recipe']} is ready: {cooked['doneness']}, "
        f"made from {len(cooked['cooked_from'])} ingredients. Enjoy!"
    )
