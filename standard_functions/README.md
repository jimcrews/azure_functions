# standard_functions

A small Azure Functions app (Python v2 programming model) for learning the local
development flow with **Azurite**, **Azure Functions Core Tools (`func`)** and **uv**.

## What the app does

| Function          | Trigger | Description                                                            |
| ----------------- | ------- | ---------------------------------------------------------------------- |
| `hello`           | HTTP    | `GET /api/hello?name=Jim` – no storage needed                          |
| `save`            | HTTP    | `POST /api/save` – watermark load: writes only records with a `modified_date` after the watermark to `data/<new watermark>.json`, then updates `watermark/latest.txt` |

The `save` function needs a storage account. Locally, Azurite emulates it
(`AzureWebJobsStorage` = `UseDevelopmentStorage=true` in `local.settings.json`).

---

## 1. Prerequisites (one-off, macOS)

```bash
brew tap azure/functions
brew install azure-functions-core-tools@4   # provides `func`
brew install azure-cli                      # only needed for deployment
brew install uv
brew install azurite                        # or npm install -g azurite
```

Check: `func --version` (4.x), `uv --version`, `azurite --version`.

Azurite via Docker instead of npm:

```bash
docker run -p 10000:10000 -p 10001:10001 -p 10002:10002 mcr.microsoft.com/azure-storage/azurite
```

The Azure Functions Python worker supports specific Python versions (3.10–3.13 at
time of writing). Pin one with uv (below) rather than relying on your system Python.

---

## 2. Scaffolding from scratch

Only needed if you're re-creating this project; the files already exist here.

```bash
mkdir standard_functions && cd standard_functions

# Python project managed by uv
uv init --bare --python 3.12       # creates pyproject.toml
uv python pin 3.12                 # creates .python-version
uv add azure-functions azure-storage-blob   # creates .venv and uv.lock

# Functions project files (host.json, local.settings.json, function_app.py, requirements.txt)
func init . --worker-runtime python --model V2
```

`func init` may create its own `requirements.txt` and `.gitignore`; that's fine, we
overwrite `requirements.txt` in the next step. Then replace `function_app.py` with the
code in this repo.

### Why `requirements.txt`?

Azure Functions (`func` and the deployment service) install dependencies from
`requirements.txt`; they don't read `pyproject.toml` or `uv.lock`. So **uv is the
source of truth** and `requirements.txt` is a generated file you export and commit:

```bash
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

Re-run this whenever you `uv add` / `uv remove` a dependency. (`azure-functions`
must stay in `requirements.txt`; the export includes it.)

---

## 3. Run locally in development

Open **three terminals** in `standard_functions/`.

**Terminal 1 – Azurite (storage emulator)**

```bash
mkdir -p .azurite
azurite --location .azurite --silent
```

It listens on 127.0.0.1: blob `10000`, queue `10001`, table `10002`.
Leave it running before starting `func`.

**Terminal 2 – the Functions host**

```bash
uv sync                      # create/update .venv from uv.lock
source .venv/bin/activate    # func uses the python on PATH, so activate the venv
func start
```

`func` prints the function URLs, e.g. `http://localhost:7071/api/hello`.
Code changes are picked up automatically for Python in most cases; otherwise
Ctrl+C and `func start` again.

**Terminal 3 – try it**

Locally, HTTP function keys aren't enforced, so no `?code=` is needed.

```bash
curl "http://localhost:7071/api/hello?name=Jim"
```

### Demo: incremental load with a watermark

`save` compares each record's `modified_date` with the **watermark** (the latest
`modified_date` loaded so far, stored in blob `watermark/latest.txt`). It writes only
the newer records to `data/<new watermark>.json`, then updates the watermark. If the
write fails, the watermark is not updated, so the next run retries the same records.

1. Run 1 – post the whole file (all records are new, since there is no watermark yet):

   ```bash
   curl -X POST http://localhost:7071/api/save -H "Content-Type: application/json" -d @dummy_data.json
   # -> {"loaded": 10, "watermark": "2026-09-19T11:00:00Z"}
   ```

   This creates `data/xxxx-xx-xxTxx:xx:xxZ.json`

2. Run 2 – same file again, nothing is newer than the watermark:

   ```bash
   # -> {"loaded": 0, "watermark": "2026-09-19T11:00:00Z"}
   ```

3. Change [dummy_data.json](dummy_data.json): update an existing record (change its
   `data` **and set its `modified_date` later than the watermark**, e.g.
   `2026-09-20T09:00:00Z`) and/or append new records with a later `modified_date`.
   Run the same curl again:

   ```bash
   # -> {"loaded": 2, "watermark": "2026-09-20T10:30:00Z"}   (only the changed/new records)
   ```

   This creates a second blob named after the new watermark. Each load is a separate
   batch file, so an updated record appears again in a later file rather than
   replacing the earlier copy.

Notes: a record is only picked up if its `modified_date` is *strictly after* the
watermark, so changing a record without bumping `modified_date` is not loaded.
Dates without a timezone are treated as UTC.

Look at what was written:

```bash
export AZURE_STORAGE_CONNECTION_STRING="UseDevelopmentStorage=true"   # point az at Azurite
az storage blob list -c data -o table
az storage blob list -c watermark -o table
az storage blob download -c watermark -n latest.txt --file /tmp/latest.txt --no-progress -o none && cat /tmp/latest.txt
az storage blob download -c data -n "2020-09-19T11:00:00Z.json" --file /tmp/batch.json --no-progress -o none && cat /tmp/batch.json
```

To start the demo again, delete the state: `az storage container delete -n data` and
`az storage container delete -n watermark` (or `rm -rf .azurite` with Azurite stopped).

### Inspecting Azurite's data

- **Azure Storage Explorer** (GUI): connect to *Local storage emulator* (defaults).
- Or the CLI, using the well-known dev connection string:

  ```bash
  export AZURE_STORAGE_CONNECTION_STRING="UseDevelopmentStorage=true"
  az storage blob list -c data -o table
  ```

To reset all local state, stop Azurite and `rm -rf .azurite`.

---

## 4. Deploy to Azure

Uses the Flex Consumption plan with Python 3.12. Replace the names; the function app
and storage account names must be globally unique (storage: lowercase, 3–24 chars).

```bash
az login

RG=rg-standard-functions
LOC=uksouth
STORAGE=stdfuncstorage$RANDOM
APP=standard-functions-$RANDOM

az group create -n $RG -l $LOC

az storage account create -n $STORAGE -g $RG -l $LOC --sku Standard_LRS

az functionapp create -n $APP -g $RG \
  --storage-account $STORAGE \
  --flexconsumption-location $LOC \
  --runtime python --runtime-version 3.12
```

Make sure `requirements.txt` is up to date, then publish:

```bash
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
func azure functionapp publish $APP
```

`func` zips the folder and Azure builds the dependencies remotely from
`requirements.txt`. It does **not** upload `local.settings.json` (that's local only,
and is git-ignored for good reason). In Azure, `AzureWebJobsStorage` and
`FUNCTIONS_WORKER_RUNTIME` are configured by `az functionapp create`; add any
extra app settings with:

```bash
az functionapp config appsettings set -n $APP -g $RG --settings KEY=value
```

> On Flex Consumption the runtime is set at creation, so `FUNCTIONS_WORKER_RUNTIME`
> is not an app setting there. If `func azure functionapp publish` complains about
> settings on a non-Flex plan, add `--build remote` (or use a Consumption/Premium plan).

### Calling the deployed app

`function_app.py` uses `AuthLevel.FUNCTION`, so deployed HTTP endpoints need a key:

```bash
KEY=$(az functionapp keys list -n $APP -g $RG --query functionKeys.default -o tsv)
curl "https://$APP.azurewebsites.net/api/hello?name=Jim&code=$KEY"
```

Tail logs: `func azure functionapp logstream $APP`

### Clean up

```bash
az group delete -n $RG --yes --no-wait
```

---

## Troubleshooting

- **`Connection refused 127.0.0.1:10000`** – Azurite isn't running; start it first.
- **`func start` can't find `azure.functions`** – the venv isn't active; run
  `source .venv/bin/activate` (or `uv sync` first).
- **Python version not supported** – check `func`'s message and align
  `.python-version` with a supported version.
- **Functions not listed after deploy** – check `func azure functionapp logstream $APP`
  and confirm `requirements.txt` contains `azure-functions`.
- **`func` complains about `--worker-runtime`** – make sure `local.settings.json`
  has `"FUNCTIONS_WORKER_RUNTIME": "python"`.
