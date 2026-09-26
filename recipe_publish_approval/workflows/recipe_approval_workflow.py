"""Human interaction: notify a person, wait for them to respond (or time out), then act.

    notify_head_chef
          |                          Notify: tell the head chef a recipe is waiting
          v
    wait_for_external_event   <-- race -->   create_timer
    ("ApprovalDecision")                     (DEFAULT_TIMEOUT_SECONDS)
          |                                        |
          +------------------ Wait ----------------+
                              |
              approved? -----+----- rejected? -----+----- timed out?
                 |                     |                       |
          publish_recipe         reject_recipe            reject_recipe
                                                        (reason="timed_out")
                              Act

Orchestrator code is replayed by the framework, so it must be deterministic:
no random numbers, no datetime.now(), no I/O. Put that in activities. The one
exception is context.current_utc_datetime, which IS safe/deterministic.
"""

import json
import logging
from datetime import timedelta

import azure.durable_functions as df

bp = df.Blueprint()
logger = logging.getLogger(__name__)

APPROVAL_EVENT_NAME = "ApprovalDecision"
DEFAULT_TIMEOUT_SECONDS = 45


@bp.orchestration_trigger(context_name="context")
def recipe_approval_orchestrator(context: df.DurableOrchestrationContext):
    recipe: dict = context.get_input()

    # Step 1 (Notify): tell the head chef a recipe is waiting for review.
    yield context.call_activity("notify_head_chef", recipe)

    # Step 2 (Wait): for an approval decision, or give up after DEFAULT_TIMEOUT_SECONDS.
    # Both tasks are created (not yielded) so they start racing immediately;
    # task_any resolves as soon as either one finishes.
    deadline = context.current_utc_datetime + timedelta(seconds=DEFAULT_TIMEOUT_SECONDS)
    timeout_task = context.create_timer(deadline)
    approval_task = context.wait_for_external_event(APPROVAL_EVENT_NAME)

    winner = yield context.task_any([approval_task, timeout_task])

    # Step 3 (Act): publish, reject, or auto-reject on timeout.
    if winner == approval_task:
        timeout_task.cancel()  # the chef answered in time; the timer is no longer needed
        decision = approval_task.result
        if isinstance(decision, str):
            # The Durable Functions client SDK double-JSON-encodes external event
            # payloads on the wire (raise_event pre-serializes, then the underlying
            # HTTP client serializes again), so what comes back here is sometimes
            # the JSON *text* of the decision instead of the decoded dict.
            decision = json.loads(decision)
        if decision.get("approved"):
            return (yield context.call_activity("publish_recipe", {"recipe": recipe, "decision": decision}))
        return (yield context.call_activity(
            "reject_recipe",
            {"recipe": recipe, "decision": decision, "reason": "rejected_by_chef"},
        ))

    # Timer won the race: the chef never responded in time.
    return (yield context.call_activity(
        "reject_recipe",
        {"recipe": recipe, "decision": None, "reason": "timed_out"},
    ))


@bp.activity_trigger(input_name="recipe")
def notify_head_chef(recipe: dict) -> bool:
    # Stand-in for a real notification (email, Slack, push). Logging it is
    # enough to demonstrate the pattern.
    logger.info(
        "Notifying head chef: recipe '%s' submitted by %s is awaiting approval",
        recipe["title"], recipe["cook"],
    )
    return True


@bp.activity_trigger(input_name="payload")
def publish_recipe(payload: dict) -> dict:
    recipe, decision = payload["recipe"], payload["decision"]
    logger.info("Publishing recipe '%s' (approved by %s)", recipe["title"], decision.get("reviewer"))
    return {
        "status": "published",
        "title": recipe["title"],
        "cook": recipe["cook"],
        "approved_by": decision.get("reviewer"),
        "comments": decision.get("comments", ""),
    }


@bp.activity_trigger(input_name="payload")
def reject_recipe(payload: dict) -> dict:
    recipe, decision, reason = payload["recipe"], payload["decision"], payload["reason"]
    logger.info("Rejecting recipe '%s' (reason: %s)", recipe["title"], reason)
    return {
        "status": "rejected",
        "title": recipe["title"],
        "cook": recipe["cook"],
        "reason": reason,
        "reviewed_by": decision.get("reviewer") if decision else None,
        "comments": decision.get("comments", "") if decision else "No response from the head chef in time.",
    }
