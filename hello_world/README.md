

## 1. Prerequisites (one-off, macOS)

```bash
brew tap azure/functions
brew install azure-functions-core-tools@4   # provides `func`
brew install azure-cli                      # only needed for deployment
brew install uv
brew install azurite                        # or npm install -g azurite
```

## 2. Scaffolding from scratch

Only needed if you're re-creating this project from scratch

```bash
mkdir hello_world && cd hello_world

# Python project managed by uv
uv init --bare --python 3.14       # creates pyproject.toml
uv python pin 3.14                 # creates .python-version
uv add azure-functions azure-storage-blob   # creates .venv and uv.lock

# Functions project files (host.json, local.settings.json, function_app.py, requirements.txt)
func init . --worker-runtime python --model V2
```

create `local.settings.json`:
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

```bash
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

---

## 3. Run locally in development

Open **three terminals** in the app folder.

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

## 4. Deploy to Azure

Deploying to Azure to test. Deployment will use cheapest resources as possible while still providing all the functionality to test this application.

``` shell
RG=rg-functions-test-2
LOC=australiaeast
STORAGE=helloworld20260920jimcr
APP=hello-world-20260920-jimcr
```

Log in to Azure. If you've been using Azurite, `unset AZURE_STORAGE_CONNECTION_STRING`
``` shell
az login
```

Create a Resource group:
``` shell
az group create --name $RG --location australiaeast
```

Create the storage account. Every function app needs one for its own internal state, even when your code doesn't store anything:
``` shell
az storage account create --name $STORAGE --resource-group $RG --location $LOC --sku Standard_LRS \
  --min-tls-version TLS1_2
```

Create the function app:
``` shell
az functionapp create --name $APP --resource-group $RG \
  --storage-account $STORAGE \
  --flexconsumption-location $LOC \
  --runtime python --runtime-version 3.14
```

This also creates an Application Insights resource for logs, and sets the app settings
Azure needs (including the storage connection). Your `local.settings.json` is **not**
used in Azure.

### Publish the code

Make sure `requirements.txt` is up to date, then publish from the app folder:
``` shell
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt

func azure functionapp publish $APP
```

`func` zips the folder and uploads it, and Azure installs the packages from `requirements.txt`.

You re-run the same `func azure functionapp publish $APP` command every time you change the code.

## 5. Test the deployed app

`function_app.py` uses the default auth level, `FUNCTION`, so deployed HTTP endpoints need a **function key** (locally no key is needed).

``` shell
curl -i "https://$APP.azurewebsites.net/api/hello?name=Jim"
# -> HTTP/1.1 401 Unauthorized
```

Fetch the default key and call it again with `code=`:

``` shell
KEY=$(az functionapp keys list --name $APP --resource-group $RG --query functionKeys.default -o tsv)

curl "https://$APP.azurewebsites.net/api/hello?name=Jim&code=$KEY"
# -> Hello friend, Jim!
```

### Check it's working

- **Function list:** `az functionapp function list --name $APP --resource-group $RG -o table`
- **Live logs:** `func azure functionapp logstream $APP` (leave it running, then call the endpoint in another terminal)

## 6. Clean up

Deleting the resource group deletes everything in it (function app, storage account,
Application Insights), so nothing keeps costing money:
``` shell
az group delete --name $RG --yes --no-wait
```
