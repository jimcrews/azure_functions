import azure.durable_functions as df
import azure.functions as func

from workflows.nutrition_workflow import bp as nutrition_bp

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

# Register the orchestrator + activities defined in workflows/
app.register_functions(nutrition_bp)


@app.route(route="orchestrators/nutrition")
@app.durable_client_input(client_name="client")
async def start_nutrition(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    """HTTP starter: kicks off the orchestration and returns status-check URLs."""
    meal = req.params.get("meal", "spaghetti")
    instance_id = await client.start_new("nutrition_orchestrator", None, meal)
    return client.create_check_status_response(req, instance_id)
