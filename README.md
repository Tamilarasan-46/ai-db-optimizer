# AI Database Optimizer

Connect a PostgreSQL database, click **Run Full Audit**, get a prioritized list
of performance problems — each with a copy-paste fix. Self-hosted, open source,
always **read-only** against your data.

![stack](https://img.shields.io/badge/PostgreSQL-12→17-336791) ![stack](https://img.shields.io/badge/FastAPI-Vue3-42b883) ![license](https://img.shields.io/badge/license-MIT-green)

![AI Database Optimizer dashboard](docs/screenshot-dashboard.png)

---

## 1. Run it (2 commands, zero config)

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:8080** → a bundled **demo database** (deliberately
un-indexed) is analysed out of the box. Click **▶ Run Full Audit** to see the
whole pipeline work before touching your own data.

> First boot takes a few minutes: it seeds the demo dataset and downloads the
> embedding model (~80 MB), one time.

> **Want a public instance?** See **[DEPLOY.md](DEPLOY.md)** — a step-by-step guide
> to host a locked-down public demo for free (Oracle Cloud Always-Free VM + automatic
> HTTPS), plus every deploy command and a troubleshooting playbook.

## 2. Connect YOUR database

### Option A — from the UI (fastest)
Header → **`＋ Connect database…`** → enter host, database, user, password →
Connect. Done. (Runtime-only: a backend restart returns to `.env`.)

### Option B — durable, via .env
```
TARGET_DATABASE_URL=postgresql://ai_opt_readonly:PASSWORD@host.docker.internal:5432/your_db
```
then `docker compose restart backend`.

> `host.docker.internal` = the machine running Docker. For a remote DB use its
> host/IP (through a VPN/SSH tunnel — never expose 5432 to the internet).

### Prepare your database (once)

1. **Create a read-only user** — run as a superuser, once per database you
   want to analyse (grants stats access + SELECT; the optimizer physically
   cannot write to your DB — connections are forced read-only):
   ```bash
   psql -U postgres -h YOUR_HOST -d your_db \
        -v ro_password="choose_a_password" -f setup-target-readonly-user.sql
   ```

2. **Enable pg_stat_statements** (the slow-query radar) — check first:
   ```sql
   SHOW shared_preload_libraries;   -- want: pg_stat_statements
   ```
   If missing, add to `postgresql.conf` and restart PostgreSQL once:
   ```
   shared_preload_libraries = 'pg_stat_statements'
   pg_stat_statements.track = all
   ```
   then in your database: `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;`

   *Without this, schema health / function analysis still work — only the
   slow-query features stay empty. The UI tells you if it's missing.*

Works on **PostgreSQL 12 through 17** (column renames handled automatically).

## 3. What you get

| Feature | What it does |
|---|---|
| **⚡ One-click Full Audit** | Scans slow queries, **every plpgsql function body**, query plans, schema and config → prioritized findings, each with a copy-paste fix |
| **Sargability linter** | Catches predicates that defeat indexes: `col::date` casts, functions wrapped on columns, per-row plpgsql calls in WHERE, `CASE WHEN` filters, leading-wildcard LIKE |
| **Function analyzer** | Reads function bodies from `pg_proc`: string-spliced dynamic SQL, temp-table chains, the same table scanned 20-30× |
| **Plan analyzer** | Sequential scans in your real slow queries (EXPLAIN — never executes) + index recommendations |
| **Divergence detector** | Planner estimates ≥10× off vs actuals → `ANALYZE`/statistics fixes (`POST /api/queries/deep-analyze/{id}`) |
| **🔄 Rewrite Parity Check** | Paste original + optimized query → proves they return **identical** results, with timings & speedup — before you ship |
| **AI Insights (RAG)** | Findings explained against a knowledge base of PostgreSQL tuning patterns (sentence-transformers + pgvector, fully local, no API keys) |
| **Target switcher** | Analyse any database on the cluster from a dropdown; connect new clusters from the UI |

## 4. Configuration

Everything lives in `.env` (see `.env.example` — every key has a working
default). Highlights:

| Key | Default | Meaning |
|---|---|---|
| `TARGET_DATABASE_URL` | *(empty = demo mode)* | The database to analyse, read-only |
| `EXPLAIN_ANALYZE` | `false` | `true` = real timings but executes queries (non-prod only) |
| `FRONTEND_PORT` / `BACKEND_PORT` / `AI_SERVICE_PORT` / `STORAGE_DB_PORT` | 8080 / 8000 / 5000 / 5433 | Host ports |
| `BIND_ADDR` | `127.0.0.1` | `0.0.0.0` exposes on LAN — set real passwords first; there is no built-in auth |
| `PG_IMAGE_TAG` | `pg16` | Bundled storage container's Postgres version |

## 5. Architecture

```
YOUR PostgreSQL  ←──(read-only: pg_stat_statements, pg_proc, EXPLAIN, catalogs)──┐
                                                                                 │
   ┌──────────────┐     ┌──────────────────┐     ┌───────────────────────────┐   │
   │ Vue 3        │ ──► │ FastAPI backend  │ ──► │ AI service (RAG)          │   │
   │ dashboard    │     │ audit engine ────┼─────┘ sentence-transformers     │   │
   │ :8080        │     │ :8000            │       :5000                     │   │
   └──────────────┘     └───────┬──────────┘                                 │
                                ▼                                            │
                        Bundled PostgreSQL+pgvector (:5433) ◄────────────────┘
                        findings · insights · embeddings · demo data
```

## 6. API reference

```
GET  /api/health                          health check
GET  /api/stats/summary | /stats/trends   dashboard metrics
GET  /api/queries/slow                    slow queries (pg_stat_statements)
POST /api/queries/analyze/{queryid}       EXPLAIN + index recommendations
POST /api/queries/deep-analyze/{queryid}  EXPLAIN ANALYZE + estimate divergence (SELECT-only)
POST /api/audit/full                      ⚡ one-click full audit
GET  /api/audit/findings                  stored report for current target
POST /api/parity/check                    {query_a, query_b} -> identical? + speedup
GET  /api/recommendations | /insights | /schema/health | /rag/status
GET  /api/target/info | /target/databases
POST /api/target/connect                  {database} or {host,port,database,username,password}
```

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Slow-query panel empty | No workload since `pg_stat_statements` was enabled/reset — run your app, then Refresh. Or the extension isn't installed (UI warns on connect). |
| "Cannot EXPLAIN a CREATE statement" | Normal — utility statements can't be EXPLAINed. Click a SELECT row. |
| Audit finds nothing in functions | Your functions may not be plpgsql, or >50 functions (largest 50 are scanned per run — shown in the audit chips). |
| Connect fails with "password authentication failed" | Re-run `setup-target-readonly-user.sql` with the password you're entering. |
| Port already in use | Change `FRONTEND_PORT` etc. in `.env`. |
| Everything slow on first boot | Demo seeding + model download; subsequent boots are fast. |

## 8. Security notes (read before hosting)

- Target connections are forced read-only (`default_transaction_read_only=on`);
  the read-only role additionally has no write grants.
- **No authentication is built in.** Keep `BIND_ADDR=127.0.0.1`, or put the
  stack behind a reverse proxy with auth before exposing it.
- Query texts from `pg_stat_statements` are normalized (literals stripped),
  but treat the dashboard as sensitive — it reveals your schema and workload.
- `pg_stat_statements` is cluster-wide: connected to one database, the slow
  list shows normalized query *text* from all databases in that cluster.

## License

MIT — every dependency is free/open-source. No API keys, no cloud, no telemetry.
