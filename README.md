# SwarmBench Harness

Evaluation harness for SwarmBench — runs single-agent and multi-agent benchmarks using [Harbor](https://github.com/harbor-framework/harbor).

> **Active agent:** `swarm-opencode-single` / `swarm-opencode-multi` (OpenCode, Fireworks Kimi K2.7)  
> **Kimi-CLI agent:** stalled — `swarm-kimi-single` / `swarm-kimi-multi` are available in `swarmbench-kimi/` but not actively used.

---

## Prerequisites

- Docker Desktop running
- [uv](https://docs.astral.sh/uv/) installed

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Setup

### 1. Clone this repo

```bash
git clone https://github.com/MathavanSG14/swarmbench-harness.git
cd swarmbench-harness
```

This gives you the diff files (`swarmbench-kimi/` and `swarmbench-opencode/`) needed in the next step.

### 2. Clone Harbor inside it and apply the patch

Clone Harbor and pin to the exact commit the diff targets:

```bash
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

### 2. Set API Key

```bash
export FIREWORKS_API_KEY=your_fireworks_api_key_here
```

---

## Running Tasks

All commands run from inside the `harbor/` directory.

### Set your task path

```bash
TASK=../example_tasks/template-llm-judge/4c3c848bb2f9459cb908d78f02897c6f-SWARMBENCH-FANOUT-RESEARCH-MEDICALRESEARCH
```

### Model

| Pool | Model ID |
|---|---|
| **Fireworks Kimi K2.7** | `fireworks_ai/accounts/fireworks/models/kimi-k2p7-code` |

### Oracle Validation (expected reward = 1.0)

```bash
uv run harbor run -t $TASK -a oracle \
  --ve FIREWORKS_API_KEY=$FIREWORKS_API_KEY
```

### Single Agent — OpenCode

```bash
uv run harbor run \
  -t $TASK \
  -a swarm-opencode-single \
  -m fireworks_ai/accounts/fireworks/models/kimi-k2p7-code \
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
  -t $TASK \
  -a swarm-opencode-multi \
  -m fireworks_ai/accounts/fireworks/models/kimi-k2p7-code \
  -k 1 -n 1 \
  --job-name "multi-opencode-agent" \
  --jobs-dir "$TASK/execution_logs" \
  --ve FIREWORKS_API_KEY=$FIREWORKS_API_KEY \
  --ae FIREWORKS_API_KEY=$FIREWORKS_API_KEY \
  --quiet
```

---

## Agent Differences

| | `swarm-opencode-single` | `swarm-opencode-multi` |
|---|---|---|
| `task` permission | `deny` — no subagents | `allow` — spawns subagents |
| Agent tiers | Single session only | `general` (coordinator) + `explore` (leaf worker) |
| `explore` can spawn | — | No (`task` hard-blocked at config level) |
| Coordination pattern | — | Hierarchical: orchestrator → managers → workers |
| Typical agent count | 1 | 13–20 |

Both agents set `external_directory: allow`, `doom_loop: allow`, `read: allow`, `question: deny` to prevent any subagent from blocking on interactive permission prompts in headless mode.

---

## Example Run

See [`example_run_tasks/STACKEXCHANGE_DUPLICATE_CLUSTER.md`](example_run_tasks/STACKEXCHANGE_DUPLICATE_CLUSTER.md) for a fully documented run with agent spawn diagram, reward (0.8423), and the permission fix that resolved 2-hour hangs.

---

## Results Structure

```
{task}/execution_logs/
├── multi-opencode-agent/
│   ├── result.json
│   └── {trial}/
│       ├── agent/
│       │   ├── opencode.txt          # raw JSON event stream
│       │   ├── trajectory.json       # ATIF-format trajectory
│       │   └── raw_trajectory/
│       │       ├── orchestrator_*.json
│       │       └── subagent_*.json   # one file per spawned subagent
│       └── verifier/reward.json
└── single-opencode-agent/
    └── (same structure, only orchestrator_*.json)
```

Browse results interactively:
```bash
cd harbor && uv run harbor view ../example_tasks/
```

---

## Flag Reference

| Flag | Purpose |
|---|---|
| `-t` | Path to task directory |
| `-a` | Agent: `oracle`, `swarm-opencode-single`, `swarm-opencode-multi` |
| `-m` | Model ID |
| `-k` | Number of runs per task |
| `-n` | Concurrent trials within the run |
| `--job-name` | Output folder name under `--jobs-dir` |
| `--jobs-dir` | Where Harbor saves results |
| `--ve` | Env var passed to the verifier |
| `--ae` | Env var passed to the agent |
| `--quiet` | Show summary table only |

---

## Troubleshooting

**Patch fails to apply**  
Make sure you ran `git checkout e70d5f060ffeb4525f320669d50b290925b55425` before running `git apply`. The diff must be applied against that exact commit.

**`NonZeroAgentExitCodeError` / `curl: (6) Could not resolve host`**  
The Docker container needs outbound internet access to install opencode via `nvm`/`npm`. Check Docker network settings — containers must reach `raw.githubusercontent.com`, `nodejs.org`, and `registry.npmjs.org`.

**Subagents hang for the full agent timeout (e.g. 2 hours) then score 0.0**  
This was caused by `external_directory` permission being set to `ask` — opencode's `read` tool blocks indefinitely waiting for user approval when reading paths outside `/workspace/`. The permission fix is already applied in `swarmbench-opencode/swarmbench_harbor_changes.diff`. See the example run doc for the full root-cause analysis.

**`trajectory.json` not created**  
Written only after opencode runs successfully. If the agent crashed during install, fix the network issue and re-run.
