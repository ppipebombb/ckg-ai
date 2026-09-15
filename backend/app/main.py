from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.routes import (
    admin_auth,
    asik_locations,
    auth,
    bayi_report,
    chatbot,
    cron_backfill,
    cron_config,
    cron_run,
    dm_report,
    gdp_report,
    hipertensi_report,
    lipid_report,
    llm,
    loop_runs,
    mapping,
    merge,
    merge_conflicts,
    obesitas_report,
    patients,
    prod_auth,
    puskesmas,
    report,
    report_dashboards,
    school_cron_config,
    school_patients,
    scrape,
    stats,
    sync,
    users,
)
from app.config import settings
from app.core import soft_delete  # noqa: F401  registers global query filter

_docs_disabled = settings.is_production

app = FastAPI(
    title="CKG Backend",
    version="0.1.0",
    docs_url=None if _docs_disabled else "/docs",
    redoc_url=None if _docs_disabled else "/redoc",
    openapi_url=None if _docs_disabled else "/openapi.json",
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        msg = err.get("msg", "Invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Swagger UI / ReDoc load assets + run inline scripts, so the strict API CSP
# would break them. They're dev-only (disabled in production) — exempt them.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def _security_headers(request: Request, call_next) -> Response:
    """Defense-in-depth response headers. This is a JSON API (no first-party
    HTML beyond dev docs), so a deny-by-default CSP plus anti-framing /
    anti-sniffing headers are safe and satisfy baseline scanner checks."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

app.include_router(admin_auth.router)
app.include_router(prod_auth.router)
app.include_router(auth.router)
app.include_router(puskesmas.router)
app.include_router(asik_locations.router)
app.include_router(users.router)
app.include_router(patients.router)
app.include_router(school_patients.router)
app.include_router(school_cron_config.router)
app.include_router(scrape.router)
app.include_router(loop_runs.router)
app.include_router(merge.router)
app.include_router(merge_conflicts.router)
app.include_router(sync.router)
app.include_router(llm.router)
app.include_router(stats.router)
app.include_router(cron_config.router)
app.include_router(cron_run.router)
app.include_router(cron_backfill.router)
app.include_router(mapping.router)
app.include_router(gdp_report.router)
app.include_router(hipertensi_report.router)
app.include_router(dm_report.router)
app.include_router(lipid_report.router)
app.include_router(obesitas_report.router)
app.include_router(bayi_report.router)
app.include_router(report.router)
app.include_router(report_dashboards.router)
app.include_router(chatbot.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
