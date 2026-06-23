#!/usr/bin/env python3
"""Oracle solver: load the frozen CQADupStack duplicate-cluster gold and emit it as
the agent-output schema. No reasoning; the gold partition is the answer."""
import json
from pathlib import Path

# Harbor mounts both /tests and /solution. Prefer /solution copy (placed by the
# build_corpus.py builder), fall back to /tests/oracle.json.
src_candidates = [Path("/solution/oracle.json"), Path("/tests/oracle.json")]
gold_path = next(p for p in src_candidates if p.exists())
gold = json.loads(gold_path.read_text())

out = {
    "analyst_line": "Oracle: applied the published CQADupStack duplicate-question partition as the cluster grouping.",
    "assignments": [{"id": g["id"], "group": g["cluster_id"]} for g in gold["gold"]],
}
Path("/logs/agent").mkdir(parents=True, exist_ok=True)
Path("/logs/agent/output.json").write_text(json.dumps(out, indent=2))
