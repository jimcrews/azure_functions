# Durable Function using Human Approval

## 1. Prerequisites

 - Microsoft.Azure.FunctionsCoreTools (provides `func`)
 - Microsoft.AzureCLI (`az`)
 - astral-sh.uv
- azurite

## 2. Scaffolding from scratch

Only needed if you're re-creating this project from scratch

```shell
mkdir recipe_publish_approval; cd recipe_publish_approval

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

```shell
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

---

## 3. Run locally in development

Open **three terminals** in the app folder.

**Terminal 1 – Azurite (storage emulator)**

```shell
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

func start                     # prints the function URLs
```

**Terminal 3 – try it**

Locally, HTTP function keys aren't enforced, so no `?code=` is needed.
`title` and `cook` are optional query params on submit. The approval window is fixed at
`DEFAULT_TIMEOUT_SECONDS` (30s) in the orchestrator.

**Scenario A — the chef approves in time**

```shell
# Bash
start=$(curl -s -X POST "http://localhost:7071/api/recipes/submit?title=Miso%20Ramen&cook=Sam")
echo "$start"
instance_id=$(echo "$start" | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
status_url=$(echo "$start" | python3 -c "import json, sys; print(json.load(sys.stdin)['statusQueryGetUri'])")

# While it's waiting, the head chef approves it
curl -s -X POST "http://localhost:7071/api/recipes/$instance_id/decision" \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "reviewer": "Chef Marco", "comments": "Looks great, publish it."}'

# Poll the status
curl -s "$status_url"
```

**Scenario B — the chef rejects it**

Same as above, but post:
``` shell
curl -s -X POST "http://localhost:7071/api/recipes/$instance_id/decision" \
  -H "Content-Type: application/json" \
  -d '{"approved": false, "reviewer": "Chef Marco", "comments": "Too much salt, try again."}'
```

**Scenario C — the chef never responds (auto-rejected on timeout)**

```shell
# Bash — takes ~30s since that's the fixed approval window
start=$(curl -s -X POST "http://localhost:7071/api/recipes/submit?title=Mystery%20Stew&cook=Sam")
status_url=$(echo "$start" | python3 -c "import json, sys; print(json.load(sys.stdin)['statusQueryGetUri'])")

sleep 31   # let the 30s timeout elapse without sending a decision
curl -s "$status_url"
```

---

## 4. What this demonstrates: human interaction (notify, wait, act)

Files:

- `function_app.py` – the **client**. `submit_recipe` starts the orchestration when a cook submits a recipe;
  `submit_decision` is how the head chef's answer gets in — it raises an *external event* on the running
  instance.
- `workflows/recipe_approval_workflow.py` – the **orchestrator** (`recipe_approval_orchestrator`) and the
  **activities** (`notify_head_chef`, `publish_recipe`, `reject_recipe`).

```
notify_head_chef
      |                          Notify: tell the head chef a recipe is waiting
      v
wait_for_external_event   <-- race -->   create_timer
("ApprovalDecision")                     (DEFAULT_TIMEOUT_SECONDS)
      |                                        |
      +------------------ Wait ---------------+
                          |
          approved? -----+----- rejected? -----+----- timed out?
             |                     |                       |
      publish_recipe         reject_recipe            reject_recipe
                                                     (reason="timed_out")
                          Act
```

The key lines in the orchestrator:

```python
timeout_task = context.create_timer(deadline)                 # ticking clock
approval_task = context.wait_for_external_event("ApprovalDecision")  # waits for a human

winner = yield context.task_any([approval_task, timeout_task])  # race: whichever finishes first

if winner == approval_task:
    timeout_task.cancel()          # the chef answered; stop the clock
    decision = approval_task.result
    ...
else:
    ...                            # the timer won: no answer in time
```

The external event is how a human gets a message into an already-running orchestration. `submit_decision`
doesn't call the orchestrator directly — it calls `client.raise_event(instance_id, "ApprovalDecision", ...)`,
which the durable extension delivers to whichever orchestration instance is currently waiting on
`context.wait_for_external_event("ApprovalDecision")`. If nothing is waiting (wrong instance ID, or the
instance already finished), the event is simply dropped.

## 5. Verify it works

1. **Approved.** Scenario A's `statusQueryGetUri` ends with `runtimeStatus: Completed` and
   `output.status: "published"`, with `output.approved_by` and `output.comments` matching what you sent
   in the decision call.
2. **Rejected by the chef.** Scenario B ends `Completed` with `output.status: "rejected"` and
   `output.reason: "rejected_by_chef"`.
3. **Timed out.** Scenario C ends `Completed` with `output.status: "rejected"` and
   `output.reason: "timed_out"`, and `output.reviewed_by` is `null` since no one responded. In the
   `func start` terminal you'll see the `notify_head_chef` log line, then nothing else until the timer
   fires ~30 seconds later.
4. **The race resolves once.** In Scenario A, try sending another decision to the same `instance_id`
   after it's already `Completed` — you should get back `409` (the starter checks `runtime_status` before
   raising the event), and the orchestration's output doesn't change.
5. **Look at the history.** Append `&showHistory=true` to `statusQueryGetUri` to see the timer get
   created, then either the `ApprovalDecision` event arrive or the timer fire — never both.

Learning notes:

- **Where this could go next:** an escalation chain (no answer from the head chef → ping the sous chef →
  ping the owner), multiple required approvals (fan-out `wait_for_external_event` calls, fan-in like the
  nutrition demo), and reminders (a shorter timer that loops back to `notify_head_chef` a couple of times
  before the real deadline) are natural extensions of this same Notify/Wait/Act shape.