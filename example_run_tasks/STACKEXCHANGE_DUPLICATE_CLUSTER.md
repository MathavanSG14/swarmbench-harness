# Example Run: StackExchange Duplicate Question Clustering

**Task:** `SWARMBENCH-FANOUT-DATAANALYSIS-STACKEXCHANGE-DUPLICATE-QUESTION-CLUSTER`  
**Agent:** `swarm-opencode-multi` (multi-agent hierarchical)  
**Model:** `fireworks_ai/accounts/fireworks/models/kimi-k2p7-code`  
**Reward:** 0.8423 (pairwise-F1 vs CQADupStack gold labels)  
**Runtime:** ~7m 36s | **Agents spawned:** 20 (1 orchestrator + 19 subagents)  
**Tokens:** 183,599 input / 6,699 output

---

## Run Commands

### Multi-agent (hierarchical orchestration)

```bash
cd /path/to/multi-agent-swarm-bench && harbor run \
  -p issue_tasks/<batch>/<task-dir> \
  --agent swarm-opencode-multi \
  --model fireworks_ai/accounts/fireworks/models/kimi-k2p7-code \
  --ae FIREWORKS_API_KEY=$FIREWORKS_API_KEY
```

### Single-agent (no subagent spawning)

```bash
cd /path/to/multi-agent-swarm-bench && harbor run \
  -p issue_tasks/<batch>/<task-dir> \
  --agent swarm-opencode-single \
  --model fireworks_ai/accounts/fireworks/models/kimi-k2p7-code \
  --ae FIREWORKS_API_KEY=$FIREWORKS_API_KEY
```

> **Difference:** `swarm-opencode-multi` sets `permission.task = allow` so the orchestrator can spawn subagents via the `task` tool. `swarm-opencode-single` sets `permission.task = deny`, blocking all subagent spawning — the model must solve the task in a single session.

---

## OpenCode Specialities

- **Native multi-agent via `task` tool** — spawns child opencode processes as subagents within the same session DB; no external orchestration framework needed.
- **Two-tier agent contract** — `general` agents coordinate and delegate; `explore` agents are leaf workers with `task` hard-blocked at config level, preventing unbounded recursion.
- **SQLite session store** — all orchestrator and subagent trajectories are stored in a single `opencode.db`; exportable post-run for full replay and debugging.
- **Streaming JSON output** — emits newline-delimited JSON events to stdout, making trajectory capture reliable even under timeout.
- **Permission system** — every tool call (read, bash, edit, external_directory, doom_loop, etc.) goes through a configurable ruleset; headless harness sets all interactive permissions to `allow`/`deny` so subagents never block waiting for user input.
- **Thinking mode** — supports extended reasoning (`--thinking`) for complex multi-step planning before tool use.
- **Provider-agnostic** — works with any OpenAI-compatible endpoint (Fireworks, Anthropic, local) via `opencode.json` provider config.

---

## Agent Spawn Diagram — This Run (20 sessions)

```
Orchestrator (1)
├── reads index.json + part files for planning
├── writes instruction.md to /workspace/
│
├── [task] Group A Manager — parts 01–04 (general subagent)
│   ├── [task] Worker 1  → reads part_01.json → writes bundle_01.json
│   ├── [task] Worker 2  → reads part_02.json → writes bundle_02.json
│   ├── [task] Worker 3  → reads part_03.json → writes bundle_03.json
│   ├── [task] Worker 4  → reads part_04.json → writes bundle_04.json
│   └── [task] Worker 4 retry → re-processes part_04.json (self-correction)
│
├── [task] Group B Manager — parts 05–08 (general subagent)
│   ├── [task] Bundle worker part_05.json → writes bundle_05.json
│   ├── [task] Bundle worker part_06.json → writes bundle_06.json
│   ├── [task] Bundle worker part_07.json → writes bundle_07.json
│   ├── [task] Bundle worker part_08.json → writes bundle_08.json
│   ├── [task] Retry worker part_05.json  → re-processes part_05.json
│   ├── [task] Retry worker part_06.json  → re-processes part_06.json
│   └── [task] Retry worker part_07.json  → re-processes part_07.json
│
└── [task] Group C Manager — parts 09–12 (general subagent)
    ├── [task] Bundle worker part_09 → writes bundle_09.json
    ├── [task] Bundle worker part_10 → writes bundle_10.json
    ├── [task] Bundle worker part_11 → writes bundle_11.json
    └── [task] Bundle worker part_12 → writes bundle_12.json

(Aligner: assembled all bundles → /logs/agent/output.json)
```

**Total: 1 orchestrator + 3 group managers + 12 bundle workers + 4 retry workers = 20 sessions**

Managers are `general` agents; bundle/retry workers are `explore` agents (task tool blocked).  
Retries were self-initiated by managers when a worker's output was incomplete.

---

## Key Fix Applied

Prior to this run, all 12 leaf workers hung for the full 2-hour timeout on `read /input_artifacts/part_XX.json`.

**Root cause:** opencode's `read` tool calls `assertExternalDirectoryEffect` for any path outside `/workspace/` (the worktree). This triggers a `permission.asked` event. The `--dangerously-skip-permissions` handler in `run.ts` filters by root `sessionID` — subagent permission events are silently ignored and the `Deferred.await()` blocks forever.

**Fix** (`multi_opencode.py` / `single_opencode.py`):

```python
_MULTI_AGENT_PERMISSION = {
    "task": "allow",
    "external_directory": "allow",  # was "ask" → subagents hung reading /input_artifacts/
    "doom_loop": "allow",           # was "ask" → would hang headlessly on repeated failures
    "read": "allow",                # was "ask" for *.env* → prevent .env read blocks
    "question": "deny",             # explicit; already opencode default, guards regressions
}
```