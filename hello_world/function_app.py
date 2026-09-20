import azure.functions as func
import datetime
import json
import logging

app = func.FunctionApp()


@app.route(route="hello", methods=["GET"])
def hello(req: func.HttpRequest) -> func.HttpResponse:
    """Public endpoint: greets the caller.

    Trigger:  HTTP GET /api/hello?name=Jim
    Reads:    optional `name` query parameter (defaults to "world")
    Returns:  200 with the text "Hello, <name>!"

    The simplest kind of function: no bindings and no storage, so it works
    even when Azurite isn't running.
    """
    name = req.params.get("name", "world")
    return func.HttpResponse(f"Hello friend, {name}!")