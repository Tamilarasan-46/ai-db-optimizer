-- ============================================================================
-- seed-ai-optimizer-db.sql
-- ----------------------------------------------------------------------------
-- Optional demo workload for the AI Database Optimizer, scoped to ONLY the
-- isolated ai_optimizer_db. Creates a few tables WITHOUT helpful indexes so the
-- optimizer has real sequential scans / slow queries to find.
--
-- WHO RUNS THIS: the app role `ai_optimizer_user` (NOT a superuser).
--   Running it as ai_optimizer_user means that role OWNS these tables, so the
--   backend's EXPLAIN (ANALYZE) can actually execute against them without any
--   extra data-read grant. That is why we do not need pg_read_all_data.
--
-- HOW TO RUN (always target ai_optimizer_db explicitly — never a default DB):
--   Option A (native Postgres on 5432):
--     psql -U ai_optimizer_user -h 127.0.0.1 -p 5432 -d ai_optimizer_db -f seed-ai-optimizer-db.sql
--   Option B (separate container on 5433):
--     psql -U ai_optimizer_user -h 127.0.0.1 -p 5433 -d ai_optimizer_db -f seed-ai-optimizer-db.sql
--
-- SAFE-BY-DESIGN: every statement is scoped to this database's own tables.
--   It NEVER touches any other database or your production schema.
--
-- Row counts are deliberately modest (fast to load, still large enough to force
-- seq scans). To mirror the spec's heavier volume, bump the generate_series
-- upper bounds (e.g. orders -> 2400000, events -> 5000000) — expect minutes and
-- several GB of disk if you do.
-- ============================================================================

-- Guard: make sure we are in the right database before writing anything.
DO $$
BEGIN
    IF current_database() <> 'ai_optimizer_db' THEN
        RAISE EXCEPTION
            'Refusing to seed: connected to "%" but expected "ai_optimizer_db". Reconnect with -d ai_optimizer_db.',
            current_database();
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS customers (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(255),
    email      VARCHAR(255),
    country    VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- No index on customer_id / status on purpose: these are the "missing index"
-- cases the optimizer is meant to flag.
CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    total       DECIMAL(10,2),
    status      VARCHAR(50),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id         SERIAL PRIMARY KEY,
    type       VARCHAR(100),
    payload    JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ── Seed data (modest volumes) ──────────────────────────────────────────────
INSERT INTO customers (name, email, country)
SELECT
    'Customer ' || i,
    'customer' || i || '@example.com',
    CASE (i % 5) WHEN 0 THEN 'US' WHEN 1 THEN 'UK' WHEN 2 THEN 'DE' WHEN 3 THEN 'FR' ELSE 'JP' END
FROM generate_series(1, 50000) AS i
ON CONFLICT DO NOTHING;

INSERT INTO orders (customer_id, total, status, created_at)
SELECT
    -- floor()+1 keeps this in 1..50000 (customers' id range). Plain
    -- (random()*50000)::int rounds up to 50001 sometimes -> FK violation.
    (floor(random() * 50000) + 1)::int,
    (random() * 500)::numeric(10,2),
    CASE (random() * 3)::int WHEN 0 THEN 'pending' WHEN 1 THEN 'shipped' ELSE 'delivered' END,
    NOW() - (random() * interval '365 days')
FROM generate_series(1, 500000) AS i
ON CONFLICT DO NOTHING;

INSERT INTO events (type, payload, created_at)
SELECT
    CASE (random() * 5)::int WHEN 0 THEN 'login' WHEN 1 THEN 'purchase' WHEN 2 THEN 'logout' WHEN 3 THEN 'view' ELSE 'click' END,
    jsonb_build_object('user_id', (random() * 50000)::int, 'session', md5(random()::text)),
    NOW() - (random() * interval '90 days')
FROM generate_series(1, 1000000) AS i
ON CONFLICT DO NOTHING;

-- Refresh planner statistics so EXPLAIN estimates are realistic.
ANALYZE customers;
ANALYZE orders;
ANALYZE events;

-- Generate some workload so pg_stat_statements has slow queries to show.
-- These intentionally filter on UN-indexed columns -> sequential scans.
SELECT count(*) FROM orders  WHERE status = 'pending';
SELECT count(*) FROM orders  WHERE customer_id = 12345;
SELECT count(*) FROM events  WHERE type = 'purchase';
SELECT c.country, count(*) FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.country;

-- Heavier statements so at least one crosses the 100ms "slow" threshold the
-- dashboard filters on (unindexed self-join + big grouped aggregate/sort).
SELECT o.status, c.country, count(*), round(avg(o.total), 2) AS avg_total
FROM orders o JOIN customers c ON c.id = o.customer_id
GROUP BY o.status, c.country
ORDER BY count(*) DESC;
SELECT payload->>'user_id' AS uid, count(*)
FROM events
GROUP BY uid
ORDER BY count(*) DESC
LIMIT 20;
SELECT status, count(*), sum(total)
FROM orders
WHERE created_at::date >= '2025-01-01'   -- non-sargable cast on purpose (audit flags this)
GROUP BY status;

-- NOTE: pg_stat_statements_reset() is intentionally NOT called here — it
-- requires pg_monitor / superuser, which ai_optimizer_user does not have.
-- If you want a clean baseline, run it separately as a superuser:
--   psql -U postgres -d ai_optimizer_db -c "SELECT pg_stat_statements_reset();"
