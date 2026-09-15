#!/usr/bin/env bash
# CKG prod deploy preflight — READ-ONLY. Run from the dev machine with:
#   ssh simpus-app-prd 'bash -s' < .claude/skills/ckg-deploy/preflight.sh
# Prints incoming changes, the image rebuild set, build/deps/compose warnings,
# .env gaps, disk, nginx status, and the in-flight work inventory (+resume params).
# Changes nothing on the server or in Postgres.
set -uo pipefail
cd ~/ckg-ai 2>/dev/null || { echo "FATAL: ~/ckg-ai not found"; exit 1; }

echo "===HEAD (current)==="
git rev-parse --short HEAD
git fetch -q origin 2>/dev/null || echo "WARN: git fetch failed"

echo "===INCOMING (HEAD..origin/master)==="
git --no-pager log --oneline HEAD..origin/master 2>/dev/null | head -20
[ -z "$(git --no-pager log --oneline HEAD..origin/master 2>/dev/null)" ] && echo "(already up to date)"

CH="$(git --no-pager diff --name-only HEAD..origin/master 2>/dev/null)"

echo "===IMAGES TO REBUILD==="
# frontend-shared/ is synced into BOTH frontends at build → a shared change
# rebuilds both, even if neither app dir changed.
SHARED=""; echo "$CH" | grep -q '^frontend-shared/' && SHARED=1
echo "$CH" | grep -q '^backend/'            && echo "backend (+ recreate celery_worker, celery_beat)"
{ echo "$CH" | grep -q '^frontend-internal/'  || [ -n "$SHARED" ]; } && echo "frontend-internal"
{ echo "$CH" | grep -q '^frontend-dashboard/' || [ -n "$SHARED" ]; } && echo "frontend-dashboard"
[ -n "$SHARED" ] && echo "NOTE: frontend-shared/ changed — rebuild BOTH frontends"
echo "$CH" | grep -qE '^backend/alembic/versions/' && echo "NOTE: new migration(s) — auto-applied on backend start"
if ! echo "$CH" | grep -qE '^(backend|frontend-internal|frontend-dashboard|frontend-shared)/'; then
  echo "(no app code changed — likely no rebuild needed)"
fi

echo "===CONFIRM-FIRST CHANGES (not a plain rebuild)==="
echo "$CH" | grep -qE 'docker-compose|/Dockerfile' && echo "WARN: compose/Dockerfile changed"
echo "$CH" | grep -qE 'requirements.*\.txt|pyproject\.toml' && echo "WARN: python deps changed"
echo "$CH" | grep -qE 'package\.json|package-lock|pnpm-lock|yarn\.lock' && echo "WARN: node deps changed"
echo "$CH" | grep -qE '\.env\.example' && echo "WARN: env template changed — check .env gaps below"
echo "(none of the above = plain rebuild, no extra confirmation needed)"

echo "===ENV GAPS (template keys missing from live; compose-injected ignored)==="
IGN='DATABASE_URL|REDIS_URL|SCRAPER_SESSIONS_ROOT'
if [ -f backend/.env.example ] && [ -f backend/.env ]; then
  comm -23 <(grep -oE '^[A-Z_][A-Z0-9_]*=' backend/.env.example | tr -d '=' | sort -u) \
           <(grep -oE '^[A-Z_][A-Z0-9_]*=' backend/.env | tr -d '=' | sort -u) \
    | grep -vE "^($IGN)$" | sed 's,^,backend/.env MISSING: ,'
fi
if [ -f .env.example ] && [ -f .env ]; then
  comm -23 <(grep -oE '^[A-Z_][A-Z0-9_]*=' .env.example | tr -d '=' | sort -u) \
           <(grep -oE '^[A-Z_][A-Z0-9_]*=' .env | tr -d '=' | sort -u) \
    | sed 's,^,.env MISSING: ,'
fi
echo "(env gaps end — empty = nothing to add)"

echo "===DISK / DOCKER==="
df -h / | tail -1
docker system df 2>/dev/null | sed -n '1,3p'

echo "===NGINX==="
systemctl is-active nginx 2>/dev/null
sudo -n nginx -t 2>&1 | tail -1 || echo "(nginx -t needs sudo)"

echo "===IN-FLIGHT WORK (pending/running) — save before any kill==="
echo "type|id|puskesmas|mode/step/kind|range-or-date|progress/status   (resume backfill from cursor..date_to, carrying merge_mode + source_scope + sync_mode + mandiri_only)"
docker exec ckg-ai-postgres-1 psql -U ckg_ai -d ckg_ai -At -F'|' -c "
SELECT 'backfill', b.id, p.name, b.merge_mode::text||'/'||b.source_scope::text,
       coalesce(b.cursor_date::text, b.date_from::text)||'..'||b.date_to::text,
       b.completed_dates||'/'||b.total_dates||' (resume_from='||coalesce(b.cursor_date::text,b.date_from::text)||' pk='||b.puskesmas_id::text||' scope='||b.source_scope::text||' sync='||b.sync_mode::text||' mandiri='||b.mandiri_only::text||')'
FROM cron_backfills b JOIN puskesmas p ON p.id=b.puskesmas_id
WHERE b.status IN ('pending','running') AND b.deleted_at IS NULL
UNION ALL
SELECT 'cron_run', r.id, p.name, coalesce(r.current_step::text,'-'), r.target_date::text,
       CASE WHEN r.cron_backfill_id IS NULL THEN 'STANDALONE' ELSE 'child-of-backfill '||r.cron_backfill_id::text END
FROM cron_runs r JOIN puskesmas p ON p.id=r.puskesmas_id
WHERE r.status IN ('pending','running') AND r.deleted_at IS NULL
UNION ALL
SELECT 'scrape', s.id, p.name, s.kind::text, coalesce(s.date_filter,'-'),
       s.status::text||CASE WHEN s.cron_run_id IS NULL THEN ' STANDALONE' ELSE ' child-of-cron' END
FROM scrape_jobs s JOIN puskesmas p ON p.id=s.puskesmas_id
WHERE s.status IN ('pending','running') AND s.deleted_at IS NULL
UNION ALL
SELECT 'merge', m.id, p.name,
       CASE WHEN m.patient_id IS NULL THEN 'date:'||coalesce(m.date_filter,'?') ELSE 'single-patient:'||m.patient_id::text END,
       '-', m.status::text||CASE WHEN m.cron_run_id IS NULL THEN ' STANDALONE' ELSE ' child-of-cron' END
FROM merge_jobs m JOIN puskesmas p ON p.id=m.puskesmas_id
WHERE m.status IN ('pending','running') AND m.deleted_at IS NULL
UNION ALL
-- ASIK sync. A cron SYNC step has NO per-step job row (it fans out one SyncJob
-- per patient), so a cron run sitting at current_step=sync shows here as its
-- in-flight patient. 'STANDALONE' = a manual sync from the patient detail page:
-- it has no parent to resume from, so killing it means re-triggering by hand.
SELECT 'sync', sj.id, p.name,
       CASE WHEN sj.triggered_by_type::text = 'cron' THEN 'cron-batch' ELSE 'STANDALONE' END,
       coalesce(pt.filter_date::text,'-'),
       sj.status::text||' patient='||pt.nama||' ('||pt.id::text||')'
FROM sync_jobs sj JOIN puskesmas p ON p.id=sj.puskesmas_id
                  JOIN patients pt ON pt.id=sj.patient_id
WHERE sj.status IN ('pending','running') AND sj.deleted_at IS NULL
ORDER BY 1,3;" 2>/dev/null
echo "(in-flight end — empty = nothing running, safe to rebuild without kill/resume)"
