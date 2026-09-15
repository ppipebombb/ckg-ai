from typing import Literal

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "production"]

# Placeholder secrets shipped in the .env.example files. Booting production with
# any of these (or a too-short JWT secret) means tokens are trivially forgeable,
# so we fail closed at startup rather than silently run insecure.
_PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "replace-with-32-byte-random-secret-string-here",
        "replace-with-fernet-key-from-Fernet.generate_key",
        "change-me",
        "changeme",
        "secret",
        "test-secret-key",
    }
)
_MIN_JWT_SECRET_LEN = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: AppEnv = "local"
    DATABASE_URL: str
    REDIS_URL: str
    ADMIN_EMAIL: str
    ADMIN_PASSWORD: str
    ADMIN_FULL_NAME: str = "Root Admin"
    # Separate "prod" admin for the external frontend-dashboard app (scope="prod").
    # Optional: if unset, the seed migration adds the scope column but skips
    # creating the prod admin (no insecure default account).
    PROD_ADMIN_EMAIL: str | None = None
    PROD_ADMIN_PASSWORD: str | None = None
    PROD_ADMIN_FULL_NAME: str = "Prod Admin"
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 1440
    CRED_ENCRYPTION_KEY: str
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    # Number of trusted reverse proxies in front of the app. The client IP for
    # rate-limiting is read as the Nth-from-last X-Forwarded-For entry (each
    # trusted proxy appends exactly one). 0 = ignore XFF and use the socket peer
    # (set this when uvicorn is directly exposed). Default 1 = one nginx hop.
    # Reading from the right makes the value un-spoofable: a client can prepend
    # arbitrary XFF entries but cannot push past the entries the proxies append.
    TRUSTED_PROXY_COUNT: int = 1
    LOGIN_RATE_LIMIT_MAX: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    SCRAPERS_ROOT: str | None = None
    SCRAPER_SESSIONS_ROOT: str | None = None

    # ---- Loop agent (self-maintaining EPUS scraper/converter agent, PLAN §8.1) ----
    # The throwaway container image the loop task launches per run, built from
    # loop-agent/Dockerfile (backend image + node + pinned OpenCode + gh + git).
    LOOP_AGENT_IMAGE: str = "ckg-loop-agent:latest"
    # docker CLI name — the loop worker shells out to `docker run`. The loop
    # worker needs the host docker socket (mounted in compose, native on the Mac).
    LOOP_DOCKER_BIN: str = "docker"
    # Per-container hard caps. The prod box has been taken down by unbounded
    # Chrome before, so these are non-negotiable. --init reaps zombie renderers.
    LOOP_AGENT_MEMORY: str = "1.5g"
    LOOP_AGENT_PIDS_LIMIT: int = 512
    LOOP_AGENT_CPUS: str = "1.5"
    LOOP_AGENT_SHM_SIZE: str = "1g"
    # Wall-clock ceiling on ONE loop run — over budget = killed. A covered check
    # is minutes; a maxed-out fix+review loop (5 cycles + 3 review rounds) is
    # ~1-2 h, so 4 h is ~2x honest headroom. Sized together with the fix-cycle
    # cap: raising one should raise the other.
    LOOP_RUN_TIMEOUT_SECONDS: int = 14400  # 4 h
    # How many patients one run deep-checks on BOTH sides (live capture AND
    # scraper --detail-limit): every tab of each, full list compared at count +
    # row level. Deep per patient, small sample per run.
    LOOP_DETAIL_LIMIT: int = 5
    # Per-run persisted-event cap so one runaway session can't bloat the table.
    LOOP_EVENT_CAP: int = 20000
    # Host path to the repo checkout, bind-mounted read-only into the container
    # as the seed tree. MUST be set when the worker runs in a container (the HOST
    # path is what `docker run -v` needs); auto-detected when the worker is native.
    LOOP_HOST_REPO_PATH: str | None = None
    # GitHub token scoped to push-branch + open-PR. None = local-branch-only mode
    # (the run still gates + fixes; it just can't push or open a PR).
    LOOP_GITHUB_TOKEN: str | None = None
    # HTTPS remote the container pushes branches to (owner/repo or full URL).
    LOOP_GITHUB_REPO: str | None = None
    # Comma-separated GitHub handles to request review from / assign on a new PR.
    # Reviewers get a notification; a PR's own author cannot be its reviewer, so
    # put the author in ASSIGNEES only. Empty = the PR opens with neither.
    LOOP_PR_REVIEWERS: str | None = None
    LOOP_PR_ASSIGNEES: str | None = None
    # OpenRouter provider-order lock (e.g. "z-ai") forwarded to the container so
    # BOTH the agent and reviewer models pin their upstream and forbid fallbacks.
    # Confirm the slug via the dashboard's Test-connection.
    LOOP_LLM_ROUTE_ORDER: str | None = None
    # The in-container gate + regression check READ the DB, so the container gets
    # a READ-ONLY DATABASE_URL (the gate never writes). None → fall back to the
    # worker's own DATABASE_URL (NOT read-only; fine for local, set a read-only
    # role in prod). The container also receives CRED_ENCRYPTION_KEY + the other
    # app-config secrets so `import app.config` succeeds — a documented exposure:
    # the agent can read them via `env` (PLAN §8.2).
    LOOP_AGENT_DB_URL: str | None = None
    # Docker network the loop container joins so it can resolve `postgres`
    # (e.g. "ckg-ai_default"). None → the in-container gate can't reach the DB.
    LOOP_AGENT_NETWORK: str | None = None
    OPENAI_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_PROVIDER: str = "openai"
    # Directory holding the explainer-chatbot knowledge packs (system.md,
    # manifest.json, knowledge/*.md). Default is the container path baked by the
    # Dockerfile (COPY chatbot /app/chatbot); set CHATBOT_DIR=../chatbot for dev.
    CHATBOT_DIR: str = "/app/chatbot"
    # Cross-date match window (days). ASIK upsert at date D looks for an
    # EPUS sibling within ±MATCH_WINDOW_DAYS for the same (puskesmas, nik).
    # Set to 0 to disable cross-date matching.
    MATCH_WINDOW_DAYS: int = 7
    # How many ASIK sync browsers a cron sync batch runs at once, all sharing
    # ONE ASIK login (ASIK invalidates on a second login, not on concurrent
    # requests — verified live). Almost all of a sync is idle waiting, so this
    # scales close to linearly.
    #
    # Ramp it deliberately: prod is 4 vCPU / 7.9 GB with the celery worker
    # already at ~2.6 GB and >100% CPU during a backfill, and each extra
    # Chromium costs roughly 400-600 MB. 2 is the conservative default; go to
    # 3-4 only while watching `free -m`, CPU, and the sync_jobs failure rate
    # (rising `validation_error` means the box is too loaded, not that ASIK
    # is rate-limiting). 1 restores the old strictly-sequential behaviour.
    ASIK_SYNC_CONCURRENCY: int = 2

    # Wall-clock ceiling on ONE scraper/sync subprocess.
    #
    # Both task loops wait on `while proc.poll() is None` and only break on the
    # Redis cancel flag, so a Playwright subprocess that hangs (a tab that never
    # opens, a page that never settles) holds its Celery slot FOREVER. Observed
    # 2026-07-29: an ASIK scrape stuck 14.5 h and sync subprocesses stuck 25 h,
    # with concurrency=4 that was 3 of 4 slots dead and no error anywhere.
    #
    # These are backstops, not budgets — set them far above the real p99 so they
    # only ever fire on a genuine hang. One sync patient is ~94 s typical; a
    # whole-puskesmas ASIK_SEKOLAH scrape legitimately runs for hours.
    SYNC_SUBPROCESS_TIMEOUT_SECONDS: int = 1800  # 30 min per patient
    SCRAPE_SUBPROCESS_TIMEOUT_SECONDS: int = 21600  # 6 h per scrape job

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Fail closed if production is configured with placeholder/weak secrets.

        Only enforced when APP_ENV=production so local dev and tests are
        unaffected. A forgeable JWT secret is a full auth bypass; an invalid
        Fernet key means stored credentials can't be decrypted at all.
        """
        if not self.is_production:
            return self
        if (
            self.JWT_SECRET in _PLACEHOLDER_SECRETS
            or len(self.JWT_SECRET) < _MIN_JWT_SECRET_LEN
        ):
            raise ValueError(
                "JWT_SECRET must be a strong random value of at least "
                f"{_MIN_JWT_SECRET_LEN} characters in production "
                "(generate: python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
            )
        if self.CRED_ENCRYPTION_KEY in _PLACEHOLDER_SECRETS:
            raise ValueError("CRED_ENCRYPTION_KEY must be set to a real Fernet key in production")
        try:
            Fernet(self.CRED_ENCRYPTION_KEY.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - surface any malformed-key error
            raise ValueError(
                "CRED_ENCRYPTION_KEY must be a valid Fernet key in production "
                "(generate: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\")"
            ) from exc
        return self


settings = Settings()
