# The loop CELERY WORKER image (distinct from the loop-agent CONTAINER image).
#
# This runs the backend code that consumes the `loop` queue and `docker run`s the
# throwaway ckg-loop-agent container per run (§11.2). It is just ckg-backend plus
# the docker CLI so it can talk to the host docker socket mounted into it.
#
# Build (from repo root):
#   docker build -f loop-agent/worker.Dockerfile -t ckg-loop-worker:latest .
FROM ckg-backend:latest

USER root
ENV DEBIAN_FRONTEND=noninteractive

# docker CLI only (the client) — the daemon is the host's, reached via the
# mounted /var/run/docker.sock. Uses Docker's apt repo for docker-ce-cli.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Same working dir/entry as the backend image; command is set in compose.
