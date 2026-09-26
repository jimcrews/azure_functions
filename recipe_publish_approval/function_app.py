import json

import azure.durable_functions as df
import azure.functions as func

from workflows.recipe_approval_workflow import APPROVAL_EVENT_NAME, bp as recipe_approval_bp

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

# Register the orchestrator + activities defined in workflows/
app.register_functions(recipe_approval_bp)


@app.route(route="recipes/submit", methods=["POST"])
@app.durable_client_input(client_name="client")
async def submit_recipe(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    """HTTP starter: a cook submits a recipe for the head chef to approve."""
    title = req.params.get("title", "Grandma's Lasagna")
    cook = req.params.get("cook", "Jamie")

    recipe = {"title": title, "cook": cook}
    instance_id = await client.start_new("recipe_approval_orchestrator", None, recipe)
    return client.create_check_status_response(req, instance_id)


@app.route(route="recipes/{instanceId}/decision", methods=["POST"])
@app.durable_client_input(client_name="client")
async def submit_decision(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    """HTTP: the head chef approves or rejects a pending recipe.

    Body: {"approved": true|false, "reviewer": "...", "comments": "..."}
    """
    instance_id = req.route_params["instanceId"]

    status = await client.get_status(instance_id)
    if status is None:
        return func.HttpResponse(f"No instance found with ID '{instance_id}'", status_code=404)
    if status.runtime_status != df.OrchestrationRuntimeStatus.Running:
        return func.HttpResponse(
            f"Instance '{instance_id}' is no longer waiting for a decision "
            f"(status: {status.runtime_status.value}).",
            status_code=409,
        )

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    decision = {
        "approved": bool(body.get("approved", False)),
        "reviewer": body.get("reviewer", "Head Chef"),
        "comments": body.get("comments", ""),
    }

    await client.raise_event(instance_id, APPROVAL_EVENT_NAME, decision)
    return func.HttpResponse(
        json.dumps({"instanceId": instance_id, "eventSent": APPROVAL_EVENT_NAME, "decision": decision}),
        mimetype="application/json",
        status_code=202,
    )
