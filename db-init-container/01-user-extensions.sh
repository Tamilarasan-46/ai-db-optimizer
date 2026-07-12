#!/bin/bash
# ============================================================================
# db-init-container/01-user-extensions.sh   (Option B only)
# ----------------------------------------------------------------------------
# Runs ONCE, automatically, the first time the isolated Postgres container in
# docker-compose.new-container.yml initializes an empty data volume. The stock
# Postgres entrypoint executes every *.sh / *.sql in /docker-entrypoint-initdb.d
# as the superuser ($POSTGRES_USER) against the freshly created $POSTGRES_DB.
#
# Because this container is its OWN cluster, there is no production data here to
# protect — but we still create a dedicated NON-superuser for the app to keep
# the setup identical to the native-DB path.
#
# The app-role password comes from the AI_OPTIMIZER_PASSWORD env var (set in
# .env, passed to the postgres service in the compose file) — nothing secret is
# hardcoded in this script.
# ============================================================================
set -euo pipefail

: "${POSTGRES_USER:?}"
: "${POSTGRES_DB:?}"
: "${AI_OPTIMIZER_USER:?set AI_OPTIMIZER_USER in .env}"
: "${AI_OPTIMIZER_PASSWORD:?set AI_OPTIMIZER_PASSWORD in .env}"

# --dbname "$POSTGRES_DB" so extensions + schema grants land in ai_optimizer_db.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Dedicated, minimally-privileged app login role.
    CREATE ROLE ${AI_OPTIMIZER_USER} WITH
        LOGIN
        PASSWORD '${AI_OPTIMIZER_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

    -- Read statistics views (pg_stat_statements etc.) — stats only, not data.
    GRANT pg_read_all_stats TO ${AI_OPTIMIZER_USER};

    -- Restrict connections on this database to the app role.
    REVOKE CONNECT ON DATABASE ${POSTGRES_DB} FROM PUBLIC;
    GRANT  CONNECT ON DATABASE ${POSTGRES_DB} TO ${AI_OPTIMIZER_USER};

    -- Superuser-only extensions (see note about the 'vector' name in the .sql).
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Let the app create its own tables in schema public.
    GRANT USAGE, CREATE ON SCHEMA public TO ${AI_OPTIMIZER_USER};
EOSQL

echo "[init] ai_optimizer_user + extensions ready in ${POSTGRES_DB}"
