-- ============================================================================
-- setup-ai-optimizer-db.sql
-- ----------------------------------------------------------------------------
-- Creates an ISOLATED database + a dedicated, minimally-privileged login role
-- for the AI Database Optimizer prototype.
--
-- WHO RUNS THIS: a PostgreSQL SUPERUSER (e.g. the `postgres` role).
--   Creating databases, roles, the pg_read_all_stats grant, and the `vector`
--   extension all require superuser — the app's own role deliberately cannot
--   do these things.
--
-- HOW TO RUN (see SETUP-CHECKLIST.md for the full flow):
--   psql -U postgres -h 127.0.0.1 -f setup-ai-optimizer-db.sql
--
-- IMPORTANT: do NOT run this with --single-transaction / -1.
--   CREATE DATABASE cannot execute inside a transaction block.
--
-- BEFORE RUNNING: replace CHANGE_ME_STRONG_PASSWORD below with a real password.
--   Use the SAME value in your .env file's DATABASE_URL.
--
-- ISOLATION CAVEAT (read this): pg_stat_statements is CLUSTER-WIDE. A role with
--   pg_read_all_stats connected to ai_optimizer_db will still see normalized
--   query text from EVERY database in this Postgres instance, including your
--   production database if it lives in the same cluster. If you need the app to
--   see ONLY its own workload, use the fully separate container instead
--   (docker-compose.new-container.yml, its own cluster on port 5433).
-- ============================================================================


-- 1. Dedicated login role for the app. Explicitly a NON-superuser that also
--    cannot create databases or other roles. This is the account the backend
--    and ai-service connect as.
CREATE ROLE ai_optimizer_user WITH
    LOGIN
    PASSWORD 'CHANGE_ME_STRONG_PASSWORD'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOINHERIT;

-- 2. Allow the role to read statistics views (pg_stat_statements,
--    pg_stat_user_indexes, pg_statio_user_tables, etc.). This is a predefined
--    role membership, granted at the cluster level. It grants stats visibility
--    ONLY — not the ability to read your table DATA.
GRANT pg_read_all_stats TO ai_optimizer_user;

-- 3. The isolated database itself. Owned by the current (superuser) role, NOT
--    by ai_optimizer_user, so the app role only gets the explicit grants below.
CREATE DATABASE ai_optimizer_db;

-- 4. Lock down who may connect: revoke the default PUBLIC connect grant, then
--    hand CONNECT to our app role only.
REVOKE CONNECT ON DATABASE ai_optimizer_db FROM PUBLIC;
GRANT  CONNECT ON DATABASE ai_optimizer_db TO ai_optimizer_user;

-- 5. Switch into the new database. Everything after this runs INSIDE
--    ai_optimizer_db (extensions and schema-level grants are per-database).
--    NOTE: \connect is a psql meta-command; this file must be run with psql.
\connect ai_optimizer_db

-- 6. Enable required extensions. These are superuser-only here:
--    * pg_stat_statements also needs shared_preload_libraries set at server
--      start (see the checklist for how to verify) — this CREATE EXTENSION only
--      registers the view, the library itself must already be preloaded.
--    * `vector` is the pgvector extension. Its extension NAME is `vector`
--      (NOT `pgvector`), and it is not a "trusted" extension, so it must be
--      created by a superuser — which is why the app role does not create it.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS vector;

-- 7. Let the app role create its own objects in schema public. The backend
--    creates its tables (query_snapshots, index_recommendations, ai_insights,
--    knowledge_embeddings) at startup, so it needs CREATE; USAGE lets it
--    reference the schema. On PostgreSQL 15+ the PUBLIC role no longer gets
--    CREATE on public by default, so this grant is required.
GRANT USAGE, CREATE ON SCHEMA public TO ai_optimizer_user;

-- 8. Sanity echo (harmless): confirm the role and extensions landed.
--    These SELECTs just print rows so you can eyeball the result.
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
  FROM pg_roles WHERE rolname = 'ai_optimizer_user';
SELECT extname FROM pg_extension WHERE extname IN ('pg_stat_statements', 'vector');
