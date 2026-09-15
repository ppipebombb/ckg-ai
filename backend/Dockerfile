# Base pinned by digest (2026-07-15) so the tag can't silently drift. The
# unpinned python:3.12-slim was re-pulled after the local base image had been
# pruned, which invalidated the cached ~1.2GB Chromium layer (Dockerfile line
# ~29) and forced a re-download of Chromium from storage.googleapis.com — which
# the box currently can't resolve. This digest is the exact base the running
# image was built on, so the browser layer stays cached and reproducible.
# To bump: pull the new python:3.12-slim, update this digest deliberately.
FROM python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev gcc xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./

# Python dependencies — cached until pyproject.toml changes (NOT on every code
# edit). pip must build the package from pyproject to resolve its deps, but the
# real source isn't copied yet, so a throwaway empty `app` package lets pip
# install just the dependencies into this cacheable layer. The real source is
# copied below and the package re-registered with --no-deps (a tiny, fast layer).
RUN mkdir -p app && touch app/__init__.py \
    && pip install ".[dev]" \
    && rm -rf app

# Chromium browser (~1.2GB) + its OS deps, installed to match the playwright
# version resolved just above (avoids any browser/package version mismatch).
# Independent of app source, so this layer stays cached until pyproject.toml
# changes — which is exactly when the playwright version (and thus the required
# browser build) can change, so re-syncing the browser then is correct.
RUN playwright install --with-deps chromium

# Application source — the ONLY layers that rebuild on a code change.
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/scripts ./scripts
# Chatbot knowledge packs — plain markdown read at runtime (CHATBOT_DIR defaults
# to /app/chatbot). Ships with the code so a rebuild after git pull updates the
# bot automatically; ops can bind-mount ./chatbot:/app/chatbot to hot-patch.
COPY chatbot /app/chatbot

RUN pip install -e . --no-deps

COPY scrapers /app/scrapers

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
