FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/doc-sentinel
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[runtime]"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# GitHub Actions mounts the workspace and runs the container as root by
# default; the entrypoint drops nothing but marks the workspace safe for git.
ENTRYPOINT ["/entrypoint.sh"]
