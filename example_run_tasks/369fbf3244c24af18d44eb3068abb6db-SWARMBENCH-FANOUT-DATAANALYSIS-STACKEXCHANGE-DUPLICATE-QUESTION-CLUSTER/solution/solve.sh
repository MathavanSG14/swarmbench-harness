#!/bin/bash
set -euo pipefail
# Oracle is cp-only: recovering the duplicate-question partition is non-scriptable
# moderator judgment, so the reference answer is the frozen CQADupStack qrels gold
# (copied, not re-derived). verify.py scores deterministically (pairwise-F1) against
# it, which is why verifier_type = executable.
mkdir -p /logs/agent
python3 /solution/build_output.py
echo "Oracle (CQADupStack qrels reference grouping) written to /logs/agent/output.json"
