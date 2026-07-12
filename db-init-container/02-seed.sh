#!/bin/bash
# ============================================================================
# db-init-container/02-seed.sh   (Option B only)
# ----------------------------------------------------------------------------
# Runs ONCE on first container init, AFTER 01-user-extensions.sh. Loads the
# demo workload so the dashboard has real slow queries to show — you don't have
# to run any seed command by hand.
#
# It reuses the canonical seed-ai-optimizer-db.sql (mounted read-only at /seed)
# so there's a single source of truth. We SET ROLE to the app user first, so the
# demo tables are OWNED by ai_optimizer_user and the backend's EXPLAIN (ANALYZE)
# can execute against them without any extra data-read grant.
# ============================================================================
set -euo pipefail

: "${POSTGRES_USER:?}"
: "${POSTGRES_DB:?}"
: "${AI_OPTIMIZER_USER:?}"

# SET ROLE persists for the whole psql session, so everything in the seed file
# runs as ai_optimizer_user (postgres superuser is allowed to SET ROLE).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -c "SET ROLE ${AI_OPTIMIZER_USER};" \
     -f /seed/seed-ai-optimizer-db.sql

echo "[init] demo workload seeded into ${POSTGRES_DB} as ${AI_OPTIMIZER_USER}"
