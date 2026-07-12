-- ============================================================================
-- setup-target-readonly-user.sql
-- ----------------------------------------------------------------------------
-- Creates/refreshes a READ-ONLY role on your EXISTING working cluster so the
-- optimizer can analyse it safely. The optimizer never writes here — this role
-- cannot either. Reusable: run it ONCE PER DATABASE you want to analyse (SELECT
-- and CONNECT grants are per-database; the role itself is created only once).
--
-- WHO RUNS THIS: a SUPERUSER on your working cluster (e.g. postgres).
--
-- HOW TO RUN (password is passed in as a psql variable — no file edits needed;
-- use the SAME password as TARGET_DATABASE_URL in .env):
--   psql -U postgres -h 127.0.0.1 -p 5432 -d tectalik_trade_api_dev ^
--        -v ro_password="aiopt_ro_R6nT2wQ9xK4bL8vZ7pH3" -f setup-target-readonly-user.sql
--
-- To also test another DB later, just run it again against that DB, e.g.:
--   psql -U postgres -h 127.0.0.1 -p 5432 -d jwl_erp_dev ^
--        -v ro_password="aiopt_ro_R6nT2wQ9xK4bL8vZ7pH3" -f setup-target-readonly-user.sql
--
-- NOTE: This does NOT enable pg_stat_statements collection. That needs
--   shared_preload_libraries='pg_stat_statements' in postgresql.conf + a cluster
--   restart (SETUP-CHECKLIST.md Part 3.1). Your cluster currently has it OFF.
-- ============================================================================

-- 1. Create the login role once (idempotent); (re)set its password every run.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_opt_readonly') THEN
        CREATE ROLE ai_opt_readonly WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END $$;
ALTER ROLE ai_opt_readonly WITH LOGIN PASSWORD :'ro_password';

-- 2. Read all statistics views, including pg_stat_statements (cluster-wide).
GRANT pg_read_all_stats TO ai_opt_readonly;

-- 3. Allow it to connect to whichever database this script is run against.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO ai_opt_readonly', current_database());
END $$;

-- 4. Read access so EXPLAIN can plan queries that reference your tables.
--    (PostgreSQL 12 has no pg_read_all_data role, so grant SELECT explicitly.)
--    Grants USAGE + SELECT on EVERY non-system schema in THIS database, and sets
--    it as the default for future tables. Read-only; no data can change.
DO $$
DECLARE
    s text;
BEGIN
    FOR s IN
        SELECT nspname FROM pg_namespace
        WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO ai_opt_readonly', s);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO ai_opt_readonly', s);
        EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO ai_opt_readonly', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO ai_opt_readonly', s);
    END LOOP;
END $$;

-- 5. pg_stat_statements view must exist in THIS database for the optimizer to
--    read it. Superuser-only to create; safe no-op if already present.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 6. Sanity echo.
SELECT current_database() AS analysed_db, rolname, rolsuper, rolcreatedb
  FROM pg_roles WHERE rolname = 'ai_opt_readonly';
