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

## The 5 commands

| Command                                             | What it does                                                                       | Required?                             |
| --------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------- |
| `mascloud login --email <you@turing.com>`           | Authenticate (prompts for password), store a session token                        | **Must** — first, once per session    |
| `mascloud run <task_folder> [--mode single\|multi]` | Zip the folder → upload → run in the cloud → stream progress → save the result zip | **Must** — this is the job            |
| `mascloud runs`                                     | List **your** runs with status, reward, tokens, and cost                           | Optional (monitoring)                 |
| `mascloud download <run_id> [folder]`               | Re-fetch a run's result zip (task + `execution_logs/`)                             | Optional (auto-downloads after `run`) |
| `mascloud logout`                                   | Clear your local token                                                             | Optional                              |

**Plus one action during a run:** press **`Ctrl-C`** while a run is streaming to
**cancel it** — this stops the run on the server and tears down its sandbox.

---

## What you MUST do (the flow)

```bash
# 1. Log in once (your password is in the credentials sheet)
mascloud login --email you@turing.com

# 2. Run BOTH modes for each task — SwarmBench delivery needs single AND multi logs
mascloud run ./my-task --mode single
mascloud run ./my-task --mode multi     # (or run this in a second terminal, in parallel)
```

Each `run`:

1. packages your task folder locally (excluding any old `execution_logs/`),
2. uploads and runs it on a managed cloud sandbox,
3. streams progress to your terminal,
4. saves a result zip **beside your task folder** — e.g. `my-task-single.zip`,
   `my-task-multi.zip` — containing the full task **plus** the fresh `execution_logs/`.

Because delivery requires **both** the single-agent and multi-agent execution
logs, running both modes for every task is the real deliverable.

---

## What you CAN do (optional)

- **Pick the mode**: `--mode single` or `--mode multi` (you're prompted if you omit it).
  To run both, just run the command twice — separate terminals run them in parallel.
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
- **No model/topology choice beyond single vs multi** — the model is fixed and there are
  no arbitrary execution flags.
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
