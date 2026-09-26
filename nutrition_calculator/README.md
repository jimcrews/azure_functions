# Durable Function using Fan Out / Fan In

## 1. Prerequisites

Using Powershell

```shell
winget install Microsoft.Azure.FunctionsCoreTools   # provides `func`
winget install Microsoft.AzureCLI                    # only needed for deployment
winget install astral-sh.uv
npm install -g azurite
```

## 2. Scaffolding from scratch

Only needed if you're re-creating this project from scratch

```shell
mkdir nutrition_calculator; cd nutrition_calculator

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

```shell
uv sync                        # create/update .venv from uv.lock

# powershell:
.venv\Scripts\Activate.ps1     # func uses the python on PATH, so activate the venv
# bash:
source .venv/bin/activate

func start
```

`func` prints the function URLs

**Terminal 3 – try it**

Locally, HTTP function keys aren't enforced, so no `?code=` is needed.

```shell
# Start the workflow (meal is optional: spaghetti | salad | omelette | anything else)
$start = Invoke-RestMethod -Method Post -Uri "http://localhost:7071/api/orchestrators/nutrition?meal=salad"

# Poll its status (takes ~2-3 seconds)
$r = Invoke-RestMethod $start.statusQueryGetUri
$r.runtimeStatus

# PowerShell abbreviates nested objects (e.g. "System.Object[]"), so print the output as JSON
$r.output | ConvertTo-Json -Depth 5

# Bash
start=$(curl -s -X POST "http://localhost:7071/api/orchestrators/nutrition?meal=salad")
echo "$start"

# Poll its status (takes ~2-3 seconds)
status_url=$(echo "$start" | python3 -c "import json, sys; print(json.load(sys.stdin)['statusQueryGetUri'])")
curl -s "$status_url"
```

---

## 4. What this demonstrates: fan out / fan in

Files:

- `function_app.py` – the **client** (starter). Defines the HTTP function `start_nutrition`, which calls `client.start_new(...)` and returns status-check URLs.
- `workflows/nutrition_workflow.py` – the **orchestrator** (`nutrition_orchestrator`) and the **activities** (`get_meal_ingredients`, `lookup_ingredient_nutrition`, `total_nutrition`).

```
get_meal_ingredients
        |
  +-----+------+------+       fan out: one lookup per ingredient, all at once
  v     v      v      v
lookup lookup lookup lookup    lookup_ingredient_nutrition (simulated 2s API call each)
  +-----+------+------+
        |                      fan in: context.task_all waits for every lookup
        v
total_nutrition
```

The key lines in the orchestrator:

```python
lookups = [context.call_activity("lookup_ingredient_nutrition", i) for i in ingredients]  # fan out
per_ingredient = yield context.task_all(lookups)                                          # fan in
```

Creating the tasks does not `yield` them, so they all start immediately. `yield context.task_all(...)` then waits for all of them.

## 5. Verify it works

1. **Result.** Polling `statusQueryGetUri` should end with `runtimeStatus: Completed`. For `salad`, `output.totals` is `calories 240, protein_g 7, carbs_g 12, fat_g 20`, with one entry per ingredient under `output.ingredients`.
2. **It really ran in parallel.** In the `func start` terminal, all the `Calling nutrition API for ...` lines appear within a fraction of a second of each other, and all the `Nutrition API returned for ...` lines appear ~2 seconds later. Run sequentially, 5 ingredients would take ~10 seconds; the whole workflow takes ~3.
3. **Results keep their order.** `task_all` returns results in the order the tasks were created, not the order they finished.
4. **Try other meals.** `?meal=spaghetti` (4 ingredients), `?meal=omelette`, and an unknown meal (falls back to a default list with zero-nutrition unknown ingredients).
5. **Look at the history.** Append `&showHistory=true` to `statusQueryGetUri` to see all the lookups scheduled together, then completed.

Learning notes:

- In the real world, a failing lookup makes `task_all` fail. Use retry options (`call_activity_with_retry`) for flaky APIs.