# Durable Function using Function chaining

## 1. Prerequisites (one-off, Windows)

```powershell
winget install Microsoft.Azure.FunctionsCoreTools   # provides `func`
winget install Microsoft.AzureCLI                    # only needed for deployment
winget install astral-sh.uv
npm install -g azurite
```

## 2. Scaffolding from scratch

Only needed if you're re-creating this project from scratch

```powershell
mkdir cook_recipe; cd cook_recipe

# Python project managed by uv
uv init --bare --python 3.14                              # creates pyproject.toml
uv python pin 3.14                                        # creates .python-version
uv add azure-functions azure-functions-durable            # creates .venv and uv.lock

# Functions project files (host.json, local.settings.json, function_app.py, requirements.txt)
func init . --worker-runtime python --model V2
```

create `local.settings.json` if it doesnt exist (func init creates it):
```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "UseDevelopmentStorage=true"
  }
}
```

### `requirements.txt`?

Azure Functions install dependencies from `requirements.txt`; they don't read `pyproject.toml`.
Re-run this whenever you `uv add` / `uv remove` a dependency.

```powershell
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

---

## 3. Run locally in development

Open **three terminals** in the app folder.

**Terminal 1 – Azurite (storage emulator)**

```powershell
# Start Azurite before `func start`
# depends on local.settings.json: "AzureWebJobsStorage": "UseDevelopmentStorage=true"
# .azurite folder will be created if not exists
# .azurite holds local blobs, queues, and tables, and it shouldn't be committed to git.
# If you want a clean task hub, stop Azurite, delete .azurite, and restart it

azurite --location .azurite --silent
```

It listens on 127.0.0.1: blob `10000`, queue `10001`, table `10002`.

**Terminal 2 – the Functions host**

```powershell
uv sync                        # create/update .venv from uv.lock
.venv\Scripts\Activate.ps1     # func uses the python on PATH, so activate the venv
func start
```

`func` prints the function URLs, e.g. `http://localhost:7071/api/orchestrators/cook_recipe`.
Code changes are picked up automatically for Python in most cases; otherwise
Ctrl+C and `func start` again.

**Terminal 3 – try it**

Locally, HTTP function keys aren't enforced, so no `?code=` is needed.

```powershell
# Start the workflow (recipe is optional: pancakes | omelette | anything else)
$start = Invoke-RestMethod -Method Post -Uri "http://localhost:7071/api/orchestrators/cook_recipe?recipe=omelette"

# Poll its status (the workflow takes ~8 seconds: 4 steps x 2s)
Invoke-RestMethod $start.statusQueryGetUri
```

---

## 4. What this demonstrates: function chaining

Files:

- `function_app.py` – entry point. Creates the app, registers the workflow, and defines the HTTP starter (`start_cook_recipe`) that calls `client.start_new(...)`.
- `workflows/cook_recipe_workflow.py` – the orchestrator and four activities.

The orchestrator runs the activities in order, passing each output to the next:

```
gather_ingredients -> prep_ingredients -> cook -> plate
```

## 5. Verify it works

1. **Status progresses.** Polling `statusQueryGetUri` should show `runtimeStatus` go `Running` -> `Completed`. When completed, `output` is:
   `Your omelette is ready: golden brown, made from 4 ingredients. Enjoy!`
2. **Steps ran in order.** In the `func start` terminal you should see the activity logs appear about 2 seconds apart: Gathering -> Prepping -> Cooking -> Plating.
3. **Chaining is real.** The final message contains data created by earlier steps (ingredient count, `golden brown`). Try `?recipe=pancakes` and an unknown recipe and compare.
4. **Durability (the interesting part).** Start a run, and while it is `Running` press Ctrl+C in the `func start` terminal, then run `func start` again. The orchestration resumes where it left off and completes; finished steps are not re-run (check the logs). This works because progress is checkpointed in Azurite storage.
5. **Look at the history.** Poll with `&showHistory=true` appended to `statusQueryGetUri` to see each activity scheduled/completed event.

Learning notes:

- Orchestrator code is **replayed** after every step, so it must be deterministic (no `datetime.now()`, random, or I/O). Do that work in activities.
- Use `yield` for every `call_activity`; the orchestrator is a generator.
- Activity inputs/outputs must be JSON-serializable.
