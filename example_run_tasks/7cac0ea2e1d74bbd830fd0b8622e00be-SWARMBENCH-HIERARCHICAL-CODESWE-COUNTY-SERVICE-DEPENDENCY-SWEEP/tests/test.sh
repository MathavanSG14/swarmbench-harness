#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
python3 /tests/verify.py 2>&1 | tee /logs/verifier/test-output.log
[ -f /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
