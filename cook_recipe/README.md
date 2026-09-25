

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

Start Azurite before `func start`

```powershell
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
Invoke-RestMethod -Method Post -Uri "http://localhost:7071/api/orchestrators/cook_recipe"
```

(Adjust the route once `function_app.py` defines the actual HTTP-triggered starter function.)

