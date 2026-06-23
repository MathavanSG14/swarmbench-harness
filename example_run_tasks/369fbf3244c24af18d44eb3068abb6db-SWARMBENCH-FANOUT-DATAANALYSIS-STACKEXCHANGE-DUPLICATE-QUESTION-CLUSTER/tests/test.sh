#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier /logs/agent
python3 /tests/verify.py --agent-output /logs/agent/output.json --oracle /tests/oracle.json --reward-out /logs/verifier/reward.txt 2>&1 | tee /logs/verifier/test-output.log
[ -f /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
