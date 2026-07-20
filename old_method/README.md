# Old method — local Harbor + your own Fireworks key (deprecated)

**This workflow is deprecated.** Trainers now use the `mascloud` client (see the
[top-level README](../README.md)) instead — it runs tasks in a managed cloud
sandbox without ever requiring a local Harbor install or your own Fireworks key.

This document is kept for reference / as a fallback only (e.g. debugging a task
locally, or if the managed service is ever unavailable).

---

## Prerequisites

- Docker Desktop running
- [uv](https://docs.astral.sh/uv/) installed

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Setup

### 1. You already have the diff file here

This folder (`old_method/`) contains `swarmbench_harbor_changes.diff`, the patch
needed in the next step.

### 2. Clone Harbor inside this folder and apply the patch

Clone Harbor and pin to the exact commit the diff targets:

```bash
cd swarmbench-harness/old_method
git clone https://github.com/harbor-framework/harbor.git
cd harbor
git checkout e70d5f060ffeb4525f320669d50b290925b55425
```

> The commit SHA is pinned to ensure the diff applies cleanly. Do not skip `git checkout`.

Apply the single combined patch from inside `harbor/`:

#### macOS / Linux

```bash
git apply ../swarmbench_harbor_changes.diff
uv sync --all-extras
```

#### Windows (PowerShell, from inside `harbor\`)

`git apply` requires LF line endings. If your browser or editor converted the diff to CRLF, normalize it first:

```powershell
$diff = "..\swarmbench_harbor_changes.diff"
$lf = $diff -replace "\.diff$", ".lf.diff"
$text = [System.IO.File]::ReadAllText((Resolve-Path $diff)) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($lf, $text, (New-Object System.Text.UTF8Encoding $false))
git apply $lf
uv sync --all-extras
```

Verify:

```bash
uv run harbor --version
```

### 3. Set API Key

```bash
export FIREWORKS_API_KEY=your_fireworks_api_key_here
```

---

## Running Tasks

All commands run from inside the `harbor/` directory (i.e. `old_method/harbor/`).

### Set your task path

```bash
TASK=../../example_tasks/template-llm-judge/4c3c848bb2f9459cb908d78f02897c6f-SWARMBENCH-FANOUT-RESEARCH-MEDICALRESEARCH
```

### Model

| Pool                    | Model ID                                           |
| ----------------------- | -------------------------------------------------- |
| **Fireworks Kimi K2.6** | `fireworks_ai/accounts/fireworks/models/kimi-k2p6` |

### Oracle Validation (expected reward = 1.0)

```bash
uv run harbor run -p $TASK -a oracle \
  --ve FIREWORKS_API_KEY=$FIREWORKS_API_KEY
```

### Single Agent — OpenCode

```bash
uv run harbor run \
  -p $TASK \
  -a swarm-opencode-single \
  -m fireworks_ai/accounts/fireworks/models/kimi-k2p6 \
  -k 1 -n 1 \
  --job-name "single-opencode-agent" \
  --jobs-dir "$TASK/execution_logs" \
  --ve FIREWORKS_API_KEY=$FIREWORKS_API_KEY \
  --ae FIREWORKS_API_KEY=$FIREWORKS_API_KEY \
  --quiet
```

### Multi Agent — OpenCode (hierarchical)

```bash
uv run harbor run \
  -p $TASK \
  -a swarm-opencode-multi \
  -m fireworks_ai/accounts/fireworks/models/kimi-k2p6 \
  -k 1 -n 1 \
  --job-name "multi-opencode-agent" \
  --jobs-dir "$TASK/execution_logs" \
  --ve FIREWORKS_API_KEY=$FIREWORKS_API_KEY \
  --ae FIREWORKS_API_KEY=$FIREWORKS_API_KEY \
  --quiet
```

---

## Flag Reference

| Flag         | Purpose                                                          |
| ------------ | ---------------------------------------------------------------- |
| `-t`         | Path to task directory                                           |
| `-a`         | Agent: `oracle`, `swarm-opencode-single`, `swarm-opencode-multi` |
| `-m`         | Model ID                                                         |
| `-k`         | Number of runs per task                                          |
| `-n`         | Concurrent trials within the run                                 |
| `--job-name` | Output folder name under `--jobs-dir`                            |
| `--ve`       | Env var passed to the verifier                                   |
| `--ae`       | Env var passed to the agent                                      |
| `--quiet`    | Show summary table only                                          |

---

## Troubleshooting

**Patch fails to apply**
Make sure you ran `git checkout e70d5f060ffeb4525f320669d50b290925b55425` before running `git apply`. The diff must be applied against that exact commit.

**`NonZeroAgentExitCodeError` / `curl: (6) Could not resolve host`**
The Docker container needs outbound internet access to install opencode via `nvm`/`npm`. Check Docker network settings — containers must reach `raw.githubusercontent.com`, `nodejs.org`, and `registry.npmjs.org`.

**Subagents hang for the full agent timeout (e.g. 2 hours) then score 0.0**
This was caused by `external_directory` permission being set to `ask` — opencode's `read` tool blocks indefinitely waiting for user approval when reading paths outside `/workspace/`. The permission fix is already applied in this patch. See `../example_run_tasks/STACKEXCHANGE_DUPLICATE_CLUSTER.md` for the full root-cause analysis.

**`trajectory.json` not created**
Written only after opencode runs successfully. If the agent crashed during install, fix the network issue and re-run.
