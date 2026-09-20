import json
import os
from datetime import datetime, timezone

import azure.functions as func
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

DATA_CONTAINER = "data"
WATERMARK_CONTAINER = "watermark"
WATERMARK_BLOB = "latest.txt"


def _parse_date(value):
    """Parse an ISO 8601 string like 2026-09-19T11:00:00Z (naive = UTC), or None if invalid."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
    return func.HttpResponse(f"Hello, {name}!")


@app.route(route="save", methods=["POST"])
def save(req: func.HttpRequest) -> func.HttpResponse:
    """Public endpoint: incremental (watermark) load of a JSON array into blob storage.

    Trigger:  HTTP POST /api/save with a JSON array body of objects that have
              an ISO 8601 `modified_date`, e.g. `curl -d @dummy_data.json`.
              The body may contain records that were already loaded; they
              are skipped, unless their modified_date has moved forward.
    Reads:    blob `watermark/latest.txt`, the latest modified_date loaded so
              far (everything is loaded if it doesn't exist yet).
    Writes:   1. blob `data/<new watermark>.json` with only the records whose
                 modified_date is later than the old watermark
              2. blob `watermark/latest.txt` with the new watermark (latest
                 modified_date in this load). Written last, so if step 1
                 fails the watermark is unchanged and the next run retries
                 the same records.
    Returns:  201 with {"loaded": n, "watermark": "<modified_date>"} when new
              records were loaded, 200 with {"loaded": 0, ...} when there was
              nothing new, or 400 if the body isn't a JSON array of objects
              with a valid `modified_date`.
    """
    try:
        items = req.get_json()
    except ValueError:
        items = None
    if not isinstance(items, list) or not all(
        isinstance(i, dict) and _parse_date(i.get("modified_date")) for i in items
    ):
        return func.HttpResponse(
            "Body must be a JSON array of objects with an ISO 8601 modified_date",
            status_code=400,
        )

    # AzureWebJobsStorage is "UseDevelopmentStorage=true" locally (Azurite)
    blobs = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])
    for container in (DATA_CONTAINER, WATERMARK_CONTAINER):
        try:
            blobs.create_container(container)
        except ResourceExistsError:
            pass

    watermark_blob = blobs.get_blob_client(WATERMARK_CONTAINER, WATERMARK_BLOB)
    try:
        old_watermark = watermark_blob.download_blob().readall().decode()
    except ResourceNotFoundError:
        old_watermark = None

    old_date = _parse_date(old_watermark) if old_watermark else None
    new_items = [
        i for i in items if old_date is None or _parse_date(i["modified_date"]) > old_date
    ]
    if not new_items:
        return func.HttpResponse(
            json.dumps({"loaded": 0, "watermark": old_watermark}),
            mimetype="application/json",
        )

    # keep the original string (not the parsed datetime) so the blob name is exactly what was in the data
    new_watermark = max(new_items, key=lambda i: _parse_date(i["modified_date"]))["modified_date"]
    json_type = ContentSettings(content_type="application/json")
    blobs.get_blob_client(DATA_CONTAINER, f"{new_watermark}.json").upload_blob(
        json.dumps(new_items, indent=2), overwrite=True, content_settings=json_type
    )
    watermark_blob.upload_blob(new_watermark, overwrite=True)

    return func.HttpResponse(
        json.dumps({"loaded": len(new_items), "watermark": new_watermark}),
        status_code=201,
        mimetype="application/json",
    )
