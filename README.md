# SwarmBench Harness

Evaluation harness for SwarmBench — runs single-agent and multi-agent benchmarks using [Harbor](https://github.com/harbor-framework/harbor).

> **Active agent:** `swarm-opencode-single` / `swarm-opencode-multi` (OpenCode, Fireworks Kimi K2.6)

---

## How tasks actually run now — no local Docker, no API key

Trainers no longer clone Harbor or hold a Fireworks API key. Instead, the
**`mascloud` client** uploads your task folder to our managed control plane,
which runs it in the cloud (Harbor + Daytona on the server side) and streams
progress back live. The key lives only on the server — this machine never
touches it.

```
you (mascloud CLI) ──upload/run──▶ MAS Cloud Run server ──▶ cloud sandbox ──▶ Fireworks
                    ◀──live logs──                          (Harbor + Daytona)
                    ◀──result.zip──
```

> The old local-Harbor-plus-your-own-key workflow is deprecated but kept for
> reference/fallback in [`old_method/`](old_method/README.md).

---

## Setup (one time)

You need Python 3.9+ and [`pipx`](https://pipx.pypa.io).

```bash
git clone https://github.com/MathavanSG14/swarmbench-harness.git
cd swarmbench-harness/mascloud_client
pipx install .
```

Verify:

```bash
mascloud --help
```

Log in (your password is in the credentials sheet you were given):

```bash
mascloud login --email you@turing.com
```

Your session token is stored locally in `~/.mascloud/config.json` — this is the
**only** thing kept on your machine. No Fireworks/Daytona key ever appears here.

---

## Running a task

```bash
mascloud run <task_folder> --mode single
mascloud run <task_folder> --mode multi
```

Delivery requires **both** the single-agent and multi-agent execution logs, so
run each task in both modes. Each `run`:

1. packages your task folder locally (excluding any old `execution_logs/`),
2. uploads it and runs it on a managed cloud sandbox,
3. streams progress to your terminal live,
4. saves a result zip **beside your task folder** — e.g. `my-task-single.zip`,
   `my-task-multi.zip` — containing the full task **plus** the fresh
   `execution_logs/`.

Press **`Ctrl-C`** while a run is streaming to cancel it (stops the run and
tears down its cloud sandbox).

### Other commands

```bash
mascloud runs                    # your run history — status, reward, tokens, cost
mascloud download <run_id> [dir] # re-fetch a past result (kept 24h after the run finishes)
mascloud logout                  # clear your local session
```

### Model

| Pool                    | Model ID                                           |
| ----------------------- | -------------------------------------------------- |
| **Fireworks Kimi K2.6** | `fireworks_ai/accounts/fireworks/models/kimi-k2p6` |

This is fixed server-side — there's no flag to change it.

---

## Agent Differences

|                      | `swarm-opencode-single` | `swarm-opencode-multi`                            |
| -------------------- | ----------------------- | ------------------------------------------------- |
| `task` permission    | `deny` — no subagents   | `allow` — spawns subagents                        |
| Agent tiers          | Single session only     | `general` (coordinator) + `explore` (leaf worker) |
| `explore` can spawn  | —                       | No (`task` hard-blocked at config level)          |
| Coordination pattern | —                       | Hierarchical: orchestrator → managers → workers   |
| Typical agent count  | 1                       | 13–20                                             |

Both agents set `external_directory: allow`, `doom_loop: allow`, `read: allow`, `question: deny` to prevent any subagent from blocking on interactive permission prompts in headless mode.

---

## Example Run

[`example_run_tasks/7cac0ea2e1d74bbd830fd0b8622e00be-SWARMBENCH-HIERARCHICAL-CODESWE-COUNTY-SERVICE-DEPENDENCY-SWEEP`](example_run_tasks/7cac0ea2e1d74bbd830fd0b8622e00be-SWARMBENCH-HIERARCHICAL-CODESWE-COUNTY-SERVICE-DEPENDENCY-SWEEP)
is a real task package with a genuine cloud run already recorded under
`execution_logs/` — a `swarm-opencode-multi` run executed through the managed
`mascloud` pipeline (Harbor + Daytona), including the full `raw_trajectory/`
session files and `result.json`. Browse it directly to see the expected task
layout (`task.toml`, `instruction.md`, `decomposition.yaml`, `environment/`,
`tests/`) and the exact shape of a completed run's output.

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

---

## Troubleshooting

| Symptom                                              | Meaning                                    | Fix                                         |
| ----------------------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| `Not logged in — run mascloud login first.`          | No local token                              | `mascloud login --email you@turing.com`     |
| `API 401: Session expired or invalid`                | Your session token expired                  | Log in again                                 |
| `Run is still in progress — no result package yet.`  | Download attempted before the run finished  | Wait for it to finish                        |
| `Result package has expired…`                        | More than 24h since the run finished        | Re-run the task                              |
| `Task folder must contain task.toml`                 | You pointed `run` at the wrong folder       | Point it at the folder that has `task.toml`  |
| A run seems stuck with no output                     | The cloud sandbox is still building         | Give it a few minutes; it streams once ready |

For deeper agent-behavior issues (subagents hanging, `trajectory.json` missing,
etc.) — those are now handled server-side, since trainers no longer run Harbor
directly. Report them to the platform team with your `run_id` from `mascloud runs`.
For the legacy local-Harbor troubleshooting (patch application, Docker network
access), see [`old_method/README.md`](old_method/README.md).
