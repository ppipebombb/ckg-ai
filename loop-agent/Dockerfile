# Loop-agent container image (PLAN §11, §14).
#
# Base on ckg-backend:latest — it ALREADY carries the exact Python deps the
# scraper and the verify_converter regression need, plus Chromium (installed via
# `playwright install --with-deps chromium`). We only add what the agent itself
# needs on top: Node + OpenCode (the coding agent), git + gh (branch + PR), and
# the entrypoint. This keeps the image small and its deps in lock-step with prod.
#
# Build (from repo root, after `docker build` of ckg-backend:latest):
#   docker build -f loop-agent/Dockerfile -t ckg-loop-agent:latest .
FROM ckg-backend:latest

USER root
ENV DEBIAN_FRONTEND=noninteractive

# git + gh (PR), curl/gnupg for the Node + gh apt repos.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# OpenCode (the headless coding agent). PINNED — bump deliberately and re-run
# the auth/routing probe (PLAN §15 step 3) before shipping a new version.
RUN npm install -g opencode-ai@1.18.25

# The AI-SDK provider package the generated opencode.json references for the
# OpenAI-compatible / OpenRouter provider (§10.1).
RUN npm install -g @ai-sdk/openai-compatible

# Entrypoint + the agent's home. The repo itself is bind-mounted at /seed at
# runtime (never baked in) and cloned to /work per run.
COPY loop-agent/run.sh /usr/local/bin/loop-run
RUN chmod +x /usr/local/bin/loop-run

WORKDIR /work
ENTRYPOINT ["/usr/local/bin/loop-run"]
