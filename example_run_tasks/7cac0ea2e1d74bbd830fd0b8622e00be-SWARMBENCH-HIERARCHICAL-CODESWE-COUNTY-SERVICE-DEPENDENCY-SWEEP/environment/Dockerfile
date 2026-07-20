FROM python:3.12-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir openai pandas matplotlib

RUN mkdir -p /logs/agent

WORKDIR /workspace