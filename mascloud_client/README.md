# `mascloud` — Trainer CLI

Run SwarmBench tasks in the cloud **without ever handling a Fireworks or Daytona
key.** You log in with your Turing email, point `mascloud` at a task folder, and it
uploads the task, runs it on a managed sandbox, streams progress live, and hands
back a result package (your task folder + the generated `execution_logs/`).

The keys live only on the server. This client only ever holds your login token.

---

## Install (one time)

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

---

## Upgrading

When there's a new `mascloud` update, **pulling the latest code is not enough** —
`pipx`/`pip` see the package version (`0.1.0`) hasn't changed and skip reinstalling,
so you keep running the old CLI even after `git pull`. Force it:

```bash
cd swarmbench-harness
git pull
cd mascloud_client
pipx install --force .
```

If you installed with plain `pip` instead of `pipx` (e.g. into your own venv), the
equivalent is:

```bash
pip install --force-reinstall --no-deps .
```

Verify the update actually took by running `mascloud runs` — updated versions show
a `model` column and a `Today: X/Y runs used` line above the table. If you don't see
those, the reinstall didn't take effect — double check you forced it, and that
`which mascloud` points at the environment you just reinstalled into (not a leftover
install elsewhere on your `PATH`).

---

## The 7 commands

| Command                                             | What it does                                                                       | Required?                             |
| --------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------- |
| `mascloud login --email <you@turing.com>`           | Authenticate (prompts for password), store a session token                        | **Must** — first, once per session    |
| `mascloud run <task_folder> [--mode single\|multi\|multi_noplan]` | Zip the folder → upload → run in the cloud → stream progress → save the result zip | **Must** — this is the job            |
| `mascloud verify-only <task_folder> --target-mode single\|multi\|multi_noplan` | Re-run **only the verifier** against an execution log you already have — no agent, no inference cost | Optional (see below) |
| `mascloud runs`                                     | List **your** runs with status, reward, tokens, and cost                           | Optional (monitoring)                 |
| `mascloud download <run_id> [folder]`               | Re-fetch a run's result zip (task + `execution_logs/`)                             | Optional (auto-downloads after `run`) |
| `mascloud pull-trajectory <run_id> [folder]`        | Pull a fresh trajectory export from a run's **live** sandbox, mid-run — no need to wait for it to finish | Optional (peek at a run in progress) |
| `mascloud logout`                                   | Clear your local token                                                             | Optional                              |

**Plus one action during a run:** press **`Ctrl-C`** while a run is streaming to
**cancel it** — this stops the run on the server and tears down its sandbox.

---

## What you MUST do (the flow)

```bash
# 1. Log in once (your password is in the credentials sheet)
mascloud login --email you@turing.com

# 2. Run ALL THREE modes for each task — SwarmBench delivery needs single, multi,
#    AND multi_noplan logs. Only one of your runs can be QUEUED/RUNNING at a time --
#    wait for one to finish (or let --download auto-wait) before submitting the next.
mascloud run ./my-task --mode single
mascloud run ./my-task --mode multi
mascloud run ./my-task --mode multi_noplan
```

Each `run`:

1. packages your task folder locally (excluding any old `execution_logs/`),
2. uploads and runs it on a managed cloud sandbox,
3. streams progress to your terminal,
4. saves a result zip **beside your task folder** — e.g. `my-task-single.zip`,
   `my-task-multi.zip`, `my-task-multi_noplan.zip` — containing the full task
   **plus** the fresh `execution_logs/`.

Because delivery requires the single-agent, multi-agent, AND multi-agent-no-plan
execution logs, running all three modes for every task is the real deliverable.

---

## `verify-only`: fixing a stale reward without re-running the agent

If your task's `tests/verify.py` gets fixed *after* you already ran `single`/`multi`/
`multi_noplan` (e.g. a reward-format fix), you do **not** need to re-run the agent to
get an updated `reward.json` — that would re-spend the same inference cost for no
reason, since the agent's own output hasn't changed.

```bash
# your task_folder already has execution_logs/multi-opencode-agent/ from a prior run
mascloud verify-only ./my-task --target-mode multi
```

This uploads your task folder **including** its existing `execution_logs/` (unlike
`run`, which strips it), and the server:

1. copies the existing `multi-opencode-agent` trial's agent output into `solution/`,
2. replays verification via Harbor's built-in oracle agent against the **current**
   `tests/verify.py` — no opencode agent runs, no inference cost,
3. patches the new `reward.json`/`test-stdout.txt` and `result.json` back into the
   **same** `execution_logs/multi-opencode-agent/` folder, and
4. hands back the whole task folder zipped, same as `run` does.

The original agent trajectory (`trajectory.json`, `raw_trajectory/`, `opencode.txt`)
is never touched — only the verifier's output and the recorded reward change. If the
task folder you upload doesn't actually have a populated `execution_logs/<target_mode>/`
run in it, the server rejects the request immediately (400) rather than queuing a job.

---

## What you CAN do (optional)

- **Pick the mode**: `--mode single`, `--mode multi`, or `--mode multi_noplan` (you're
  prompted if you omit it). `multi_noplan` runs the same multi-agent swarm without
  `decomposition.yaml` injected — required for delivery alongside single and multi.
  To run more than one mode, run the command again after the first finishes — only
  one of your runs can be active at a time, even across two terminals.
- **Skip the auto-download**: `--no-download` (the result stays on the server; fetch it
  later with `mascloud download <run_id>`).
- **Check history & cost anytime**: `mascloud runs` shows your runs with token counts
  and `$` cost.
- **Re-download a result**: `mascloud download <run_id>` — **within 24 hours** (see below).
- **Cancel a run**: `Ctrl-C` while it's streaming.

---

## What you CANNOT do (by design)

- **Never see or handle the Fireworks/Daytona keys** — they exist only on the server.
- **Only your own runs** — you can view, cancel, and download only runs you started;
  another trainer's run is not visible to you.
- **No model/topology choice beyond single vs multi vs multi_noplan** — the model is
  fixed and there are no arbitrary execution flags.
- **No admin access** — you cannot manage users or see other people's runs or costs.

---

## ⏳ Results are kept for 24 hours

A finished run's result package is available for **24 hours**, then it is
automatically cleaned up. So:

- **Download promptly** (the auto-download after `run` handles this for you).
- If you come back later and `mascloud download` says the result **expired**, just
  **re-run the task** to regenerate it.

Your run's summary (status, reward, tokens, cost) stays in `mascloud runs`
regardless — only the downloadable zip expires.

---

## Troubleshooting

| Message                                             | Meaning                                    | Fix                                         |
| --------------------------------------------------- | ------------------------------------------ | -------------------------------------------- |
| `Not logged in — run mascloud login first.`         | No local token                             | `mascloud login --email you@turing.com`     |
| `API 401: Session expired or invalid`               | Your session token expired                 | Log in again                                 |
| `Run is still in progress — no result package yet.` | Download attempted before the run finished | Wait for it to finish                        |
| `Result package has expired…`                       | More than 24h since the run finished       | Re-run the task                              |
| `Task folder must contain task.toml`                | You pointed `run` at the wrong folder      | Point it at the folder that has `task.toml`  |

If a run seems stuck with no output, it's usually the sandbox building in the
background — give it a few minutes.
