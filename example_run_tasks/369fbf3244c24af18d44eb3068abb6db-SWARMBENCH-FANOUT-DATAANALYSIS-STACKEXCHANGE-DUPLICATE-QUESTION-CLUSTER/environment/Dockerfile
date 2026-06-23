FROM python:3.11.9-slim

# This task runs OFFLINE on purpose. The gold CQADupStack duplicate-cluster partition
# is public (mteb/cqadupstack-* on HuggingFace), so giving the agent network access
# would let it look up the answer key. No network is needed: the Stack Exchange
# questions are staged locally and the verifier is stdlib-only. Run without egress.

# Stage the real Stack Exchange questions (label-stripped: no cluster_id).
# /input_artifacts/part_*.json + index.json is the sole input.
COPY input_artifacts/ /input_artifacts/

WORKDIR /workspace

RUN mkdir -p /logs/agent /logs/verifier /workspace /tests /solution
