FROM python:3.12-slim
# Network happens ONLY at build time. Test runs use --network none.
RUN apt-get update -qq && apt-get install -y -qq git ca-certificates curl xz-utils gnupg >/dev/null && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /etc/apt/keyrings && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update -qq && apt-get install -y -qq nodejs >/dev/null && rm -rf /var/lib/apt/lists/*
# harness CLIs (real binaries)
RUN npm install -g --no-fund --no-audit @anthropic-ai/claude-code \
 && npm install -g --no-fund --no-audit @openai/codex \
 && npm install -g --no-fund --no-audit opencode-ai
# goose: GitHub release binary
RUN curl -sL https://github.com/aaif-goose/goose/releases/download/v1.56.0/goose-x86_64-unknown-linux-musl.tar.gz | tar xz -C /tmp \
 && mv /tmp/goose /usr/local/bin/goose && chmod +x /usr/local/bin/goose && goose --version
# python deps for aim itself
COPY aim-wheels/ /tmp/wheels/  # build: pip download cryptography pydantic click pyyaml pytest -d aim-wheels
RUN pip install --no-index --find-links /tmp/wheels cryptography pydantic click pyyaml pytest
ENV PYTHONPATH=/aim/src
WORKDIR /work
