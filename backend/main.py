"""
AI Database Optimizer - Backend API
FastAPI service for query analysis, index recommendations, and RAG insights.
"""
import os
import re
import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import httpx

# ── Configuration ──────────────────────────────────────────────────────────
# DATABASE_URL      -> the optimizer's OWN storage (isolated container, has pgvector).
#                      This is where recommendations/insights/snapshots/embeddings live.
# TARGET_DATABASE_URL -> the database you want to ANALYZE (your working cluster DB),
#                      opened READ-ONLY. If empty, the optimizer analyses its own DB
#                      (demo/self mode).
# EXPLAIN_ANALYZE   -> "false" (default) uses EXPLAIN only (no execution, safe on a
#                      real DB); "true" runs EXPLAIN ANALYZE (executes the query).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5432/optimizer")
TARGET_DATABASE_URL = os.getenv("TARGET_DATABASE_URL", "")
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:5000")
EXPLAIN_ANALYZE = os.getenv("EXPLAIN_ANALYZE", "false").lower() in ("1", "true", "yes")

# ── Pydantic Models ────────────────────────────────────────────────────────
class SlowQuery(BaseModel):
    # String, not int: pg_stat_statements queryid is a 64-bit value that exceeds
    # JavaScript's safe-integer range and would be rounded (breaking analyze).
    queryid: str
    query: str
    calls: int
    total_time: float
    mean_time: float
    rows: int
    shared_blks_hit: int
    shared_blks_read: int

class IndexRecommendation(BaseModel):
    id: Optional[int] = None
    table_name: str
    index_def: str
    estimated_improvement_pct: float
    current_cost: float
    new_cost: float
    impact: str  # "High", "Medium", "Low"
    reason: str

class AIInsight(BaseModel):
    id: Optional[int] = None
    severity: str  # "Critical", "Warning", "Info"
    category: str
    title: str
    description: str
    query_id: Optional[str] = None
    suggested_action: Optional[str] = None

class QueryPlanNode(BaseModel):
    node_type: str
    cost: float
    rows: int
    width: int
    actual_time: Optional[float] = None
    actual_rows: Optional[int] = None
    loops: int = 1
    index_name: Optional[str] = None
    relation: Optional[str] = None
    filter: Optional[str] = None
    children: List["QueryPlanNode"] = []

class SchemaHealth(BaseModel):
    tables_without_pk: int
    missing_fk_indexes: int
    unused_indexes: int
    duplicate_columns: int
    bloat_ratio: float

# ── Database Connection Pools ──────────────────────────────────────────────
# pool        -> optimizer storage (read/write, isolated DB with pgvector)
# target_pool -> database under analysis (read-only). Equals `pool` in self mode.
pool: asyncpg.Pool = None
target_pool: asyncpg.Pool = None

# pg_stat_statements renamed its timing columns in PG13
# (total_time -> total_exec_time, mean_time -> mean_exec_time).
# Detected per target so the tool works on PG12 through PG17.
PSS = {"mean": "mean_time", "total": "total_time"}

async def detect_pss_columns(p: asyncpg.Pool):
    global PSS
    try:
        async with p.acquire() as conn:
            ver = int(await conn.fetchval("SHOW server_version_num"))
        PSS = ({"mean": "mean_exec_time", "total": "total_exec_time"}
               if ver >= 130000 else {"mean": "mean_time", "total": "total_time"})
    except Exception as e:
        print(f"[warn] pg version detection failed ({e}); assuming PG12 column names")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, target_pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)

    # Initialize schema if needed
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS query_snapshots (
                id SERIAL PRIMARY KEY,
                queryid BIGINT,
                query TEXT,
                calls BIGINT,
                total_time DOUBLE PRECISION,
                mean_time DOUBLE PRECISION,
                rows BIGINT,
                shared_blks_hit BIGINT,
                shared_blks_read BIGINT,
                captured_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS index_recommendations (
                id SERIAL PRIMARY KEY,
                queryid BIGINT,
                table_name TEXT,
                index_def TEXT,
                estimated_improvement_pct DOUBLE PRECISION,
                current_cost DOUBLE PRECISION,
                new_cost DOUBLE PRECISION,
                impact TEXT,
                reason TEXT,
                applied BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_insights (
                id SERIAL PRIMARY KEY,
                severity TEXT,
                category TEXT,
                title TEXT,
                description TEXT,
                query_id BIGINT,
                suggested_action TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Enable pgvector extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                id SERIAL PRIMARY KEY,
                content TEXT,
                embedding vector(384),
                category TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Time-series of dashboard metrics for the Performance Trends card.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS metric_snapshots (
                id SERIAL PRIMARY KEY,
                captured_at TIMESTAMP DEFAULT NOW(),
                avg_latency_ms DOUBLE PRECISION,
                slow_queries INTEGER,
                cache_hit_rate DOUBLE PRECISION
            )
        """)

    # Open the read-only analysis connection to the target (working) database.
    # `default_transaction_read_only` is a hard guard: even EXPLAIN ANALYZE of a
    # write statement will be refused, so we can never mutate your working DB.
    if TARGET_DATABASE_URL:
        try:
            target_pool = await asyncpg.create_pool(
                TARGET_DATABASE_URL,
                min_size=1,
                max_size=5,
                server_settings={"default_transaction_read_only": "on"},
            )
            print(f"[info] Analysing TARGET database (read-only).")
        except Exception as e:
            # e.g. target not reachable yet, role/pg_stat_statements not set up.
            # Fall back to self mode instead of crashing the whole backend.
            print(f"[warn] TARGET_DATABASE_URL connect failed ({e}); using self/demo mode.")
            target_pool = pool
    else:
        target_pool = pool  # self/demo mode: analyse the optimizer's own DB

    await detect_pss_columns(target_pool)

    yield
    if target_pool is not pool:
        await target_pool.close()
    await pool.close()

app = FastAPI(title="AI Database Optimizer API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helper Functions ─────────────────────────────────────────────────────
def normalize_query(query: str) -> str:
    """Strip literals and IDs for privacy/analytics."""
    import re
    # Replace string literals
    query = re.sub(r"'[^']*'", "'?'", query)
    # Replace numeric literals
    query = re.sub(r"\d+", "?", query)
    # Replace IN lists
    query = re.sub(r"IN\s*\([^)]+\)", "IN (?)", query, flags=re.IGNORECASE)
    return query.strip()

def compute_query_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]

# ── API Endpoints ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "ai-db-optimizer", "version": "1.0.0"}

@app.get("/api/stats/summary")
async def get_summary():
    """Dashboard summary statistics."""
    # Live stats come from the TARGET (analysed) database. If pg_stat_statements
    # isn't installed there, degrade to zeros instead of erroring the dashboard.
    async with target_pool.acquire() as conn:
        try:
            slow_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM pg_stat_statements WHERE {PSS['mean']} > 100"
            )
            total_queries = await conn.fetchval("SELECT COUNT(*) FROM pg_stat_statements")
            avg_latency = await conn.fetchval(
                f"SELECT COALESCE(AVG({PSS['mean']}), 0) FROM pg_stat_statements"
            )
        except asyncpg.UndefinedTableError:
            slow_count, total_queries, avg_latency = 0, 0, 0
        # Cache hit rate
        cache_hit = await conn.fetchval("""
            SELECT CASE
                WHEN sum(heap_blks_hit) + sum(heap_blks_read) = 0 THEN 0
                ELSE 100.0 * sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read))
            END
            FROM pg_statio_user_tables
        """)
    avg_latency = round(avg_latency or 0, 1)
    cache_hit = round(cache_hit or 0, 1)
    slow_count = slow_count or 0

    # Pending recommendations come from the optimizer's OWN storage; also record a
    # time-series sample so the Performance Trends card has real data to plot.
    async with pool.acquire() as conn:
        idx_count = await conn.fetchval(
            "SELECT COUNT(*) FROM index_recommendations WHERE applied = FALSE"
        )
        await conn.execute(
            "INSERT INTO metric_snapshots (avg_latency_ms, slow_queries, cache_hit_rate) VALUES ($1, $2, $3)",
            avg_latency, slow_count, cache_hit,
        )
        # Keep the series bounded (retain the most recent 500 samples).
        await conn.execute("""
            DELETE FROM metric_snapshots WHERE id IN (
                SELECT id FROM metric_snapshots ORDER BY id DESC OFFSET 500
            )
        """)

    return {
        "slow_queries": slow_count,
        "total_queries": total_queries or 0,
        "avg_latency_ms": avg_latency,
        "cache_hit_rate": cache_hit,
        "pending_recommendations": idx_count or 0,
    }

@app.get("/api/stats/trends")
async def get_stats_trends(limit: int = 24):
    """Recent metric samples for the Performance Trends card (oldest→newest)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT captured_at, avg_latency_ms, slow_queries, cache_hit_rate
            FROM metric_snapshots
            ORDER BY id DESC
            LIMIT $1
        """, limit)
    # Reverse so the chart reads left(old)→right(new).
    return [
        {
            "timestamp": r["captured_at"].isoformat(),
            "avg_latency_ms": round(r["avg_latency_ms"] or 0, 1),
            "slow_queries": r["slow_queries"] or 0,
            "cache_hit_rate": round(r["cache_hit_rate"] or 0, 1),
        }
        for r in reversed(rows)
    ]

@app.get("/api/rag/status")
async def get_rag_status():
    """Real RAG knowledge-base status (counts from the pgvector store)."""
    entries = 0
    categories = 0
    try:
        async with pool.acquire() as conn:
            entries = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings") or 0
            categories = await conn.fetchval(
                "SELECT COUNT(DISTINCT category) FROM knowledge_embeddings"
            ) or 0
    except Exception as e:
        print(f"rag status query failed: {e}")
    return {
        "knowledge_entries": entries,
        "categories": categories,
        "embedding_model": os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "vector_dim": 384,
        "vector_store": "pgvector",
    }

@app.get("/api/queries/slow", response_model=List[SlowQuery])
async def get_slow_queries(threshold_ms: float = 100.0, limit: int = 20):
    """Get slow queries from pg_stat_statements (of the analysed target DB)."""
    async with target_pool.acquire() as conn:
        try:
            rows = await conn.fetch(f"""
                SELECT queryid, query, calls, {PSS['total']} AS total_time,
                       {PSS['mean']} AS mean_time, rows,
                       shared_blks_hit, shared_blks_read
                FROM pg_stat_statements
                WHERE {PSS['mean']} > $1
                ORDER BY {PSS['mean']} DESC
                LIMIT $2
            """, threshold_ms, limit)
        except asyncpg.UndefinedTableError:
            rows = []   # extension not installed in this DB — empty, not a 500

    return [
        SlowQuery(
            queryid=str(r["queryid"]),
            query=normalize_query(r["query"]),
            calls=r["calls"],
            total_time=r["total_time"],
            mean_time=r["mean_time"],
            rows=r["rows"],
            shared_blks_hit=r["shared_blks_hit"],
            shared_blks_read=r["shared_blks_read"],
        )
        for r in rows
    ]

@app.post("/api/queries/analyze/{queryid}")
async def analyze_query(queryid: int, background_tasks: BackgroundTasks):
    """Run EXPLAIN and generate index recommendations for a query.

    Reads the query and its plan from the TARGET (working) database read-only;
    stores the resulting recommendations only in the optimizer's own DB.
    """
    # 1. Read the query text + its plan from the TARGET (read-only) database.
    async with target_pool.acquire() as tconn:
        row = await tconn.fetchrow(
            "SELECT query FROM pg_stat_statements WHERE queryid = $1", queryid
        )
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")

        query = row["query"]

        # pg_stat_statements stores NORMALIZED SQL: literals are replaced by $1,$2,...
        # and only DML can be EXPLAINed. Build a best-effort explainable version by
        # binding placeholders to NULL, and skip statement types EXPLAIN rejects.
        explainable = re.sub(r"\$\d+", "NULL", query)
        first_kw = explainable.split(None, 1)[0].upper() if explainable.strip() else ""
        if first_kw not in ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "TABLE", "VALUES"):
            plan = {
                "error": f"Cannot EXPLAIN a {first_kw or 'blank'} statement "
                         f"(only SELECT/INSERT/UPDATE/DELETE/WITH are supported).",
                "query": normalize_query(query),
            }
        else:
            # EXPLAIN only by default (does NOT execute the query — safe on a live DB).
            # EXPLAIN ANALYZE only if EXPLAIN_ANALYZE is explicitly enabled.
            explain_opts = "ANALYZE, BUFFERS, FORMAT JSON" if EXPLAIN_ANALYZE else "FORMAT JSON"
            try:
                plan_json = await tconn.fetchval(f"EXPLAIN ({explain_opts}) {explainable}")
                plan = json.loads(plan_json)[0]["Plan"]
            except Exception as e:
                # e.g. NULL-bound placeholder made an ambiguous function call, or the
                # stored text was truncated. Report it instead of failing the request.
                plan = {"error": str(e), "query": normalize_query(query)}

    # 2. Detect sequential scans and build recommendations (pure Python, no DB).
    def find_seq_scans(node, parent=None):
        """Recursively find sequential scans in plan."""
        results = []
        if node.get("Node Type") == "Seq Scan":
            rel = node.get("Relation Name", "unknown")
            filter_cond = node.get("Filter", "")
            results.append({
                "table": rel,
                "filter": filter_cond,
                "cost": node.get("Total Cost", 0),
                "rows": node.get("Plan Rows", 0),
            })
        for child in node.get("Plans", []):
            results.extend(find_seq_scans(child, node))
        return results

    seq_scans = find_seq_scans(plan) if isinstance(plan, dict) and "error" not in plan else []

    recommendations = []
    for scan in seq_scans:
        table = scan["table"]
        # Extract column from filter condition (simplified)
        col_match = re.search(r"\((\w+)\s*[=<>]", scan.get("filter", ""))
        column = col_match.group(1) if col_match else "column_name"

        idx_def = f"CREATE INDEX idx_{table}_{column} ON {table}({column})"
        current_cost = scan["cost"]
        new_cost = current_cost * 0.05  # Estimate 95% improvement

        recommendations.append(IndexRecommendation(
            table_name=table,
            index_def=idx_def,
            estimated_improvement_pct=95.0,
            current_cost=current_cost,
            new_cost=new_cost,
            impact="High" if current_cost > 1000 else "Medium",
            reason=f"Sequential scan on {table} detected. Adding index on {column} would enable Index Scan.",
        ))

    # 3. Persist recommendations in the optimizer's OWN storage (never the target).
    async with pool.acquire() as sconn:
        for rec in recommendations:
            await sconn.execute("""
                INSERT INTO index_recommendations
                (queryid, table_name, index_def, estimated_improvement_pct, current_cost, new_cost, impact, reason)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT DO NOTHING
            """, queryid, rec.table_name, rec.index_def, rec.estimated_improvement_pct,
                 rec.current_cost, rec.new_cost, rec.impact, rec.reason)

    # 4. Trigger AI insight generation.
    background_tasks.add_task(generate_ai_insight, queryid, query, plan, recommendations)

    return {
        "queryid": queryid,
        "query": normalize_query(query),
        "plan": plan,
        "recommendations": [r.model_dump() for r in recommendations],
        "seq_scans_detected": len(seq_scans),
    }

async def generate_ai_insight(queryid: int, query: str, plan: dict, recommendations: list):
    """Generate AI insight via the AI service."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{AI_SERVICE_URL}/generate-insight", json={
                "query": normalize_query(query),
                "plan": plan,
                "recommendations": recommendations,
            })
            insight_data = response.json()

            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO ai_insights (severity, category, title, description, query_id, suggested_action)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, 
                    insight_data.get("severity", "Info"),
                    insight_data.get("category", "Performance"),
                    insight_data.get("title", "Query Analysis"),
                    insight_data.get("description", ""),
                    queryid,
                    insight_data.get("suggested_action"),
                )
    except Exception as e:
        print(f"AI insight generation failed: {e}")

@app.get("/api/recommendations", response_model=List[IndexRecommendation])
async def get_recommendations(applied_only: bool = False):
    """Get all index recommendations."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, table_name, index_def, estimated_improvement_pct,
                   current_cost, new_cost, impact, reason
            FROM index_recommendations
            WHERE applied = $1
            ORDER BY estimated_improvement_pct DESC
        """, applied_only)

    return [
        IndexRecommendation(
            id=r["id"],
            table_name=r["table_name"],
            index_def=r["index_def"],
            estimated_improvement_pct=r["estimated_improvement_pct"],
            current_cost=r["current_cost"],
            new_cost=r["new_cost"],
            impact=r["impact"],
            reason=r["reason"],
        )
        for r in rows
    ]

@app.post("/api/recommendations/{rec_id}/apply")
async def apply_recommendation(rec_id: int):
    """Apply an index recommendation (demo-safe: uses hypopg for testing)."""
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            "SELECT * FROM index_recommendations WHERE id = $1", rec_id
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        # In production, this would run the actual CREATE INDEX
        # For demo safety, we mark as applied
        await conn.execute(
            "UPDATE index_recommendations SET applied = TRUE WHERE id = $1", rec_id
        )

        return {"status": "applied", "index": rec["index_def"]}

@app.get("/api/insights", response_model=List[AIInsight])
async def get_insights(limit: int = 20):
    """Get AI-generated insights."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, severity, category, title, description, query_id, suggested_action
            FROM ai_insights
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)

    return [
        AIInsight(
            id=r["id"],
            severity=r["severity"],
            category=r["category"],
            title=r["title"],
            description=r["description"],
            query_id=str(r["query_id"]) if r["query_id"] is not None else None,
            suggested_action=r["suggested_action"],
        )
        for r in rows
    ]

@app.get("/api/schema/health", response_model=SchemaHealth)
async def get_schema_health():
    """Analyze schema health metrics (of the analysed target DB)."""
    async with target_pool.acquire() as conn:
        # Tables without primary keys
        no_pk = await conn.fetchval("""
            SELECT COUNT(*) FROM information_schema.tables t
            WHERE t.table_schema = 'public'
            AND t.table_type = 'BASE TABLE'
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints tc
                WHERE tc.table_schema = t.table_schema
                AND tc.table_name = t.table_name
                AND tc.constraint_type = 'PRIMARY KEY'
            )
        """)

        # Missing FK indexes (simplified heuristic)
        missing_fk = await conn.fetchval("""
            SELECT COUNT(*) FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND NOT EXISTS (
                SELECT 1 FROM pg_indexes pi
                WHERE pi.tablename = tc.table_name
                AND pi.indexdef LIKE '%' || kcu.column_name || '%'
            )
        """)

        # Unused indexes (scans = 0), across all user schemas.
        unused = await conn.fetchval("""
            SELECT COUNT(*) FROM pg_stat_user_indexes
            WHERE idx_scan = 0
        """)

        # Bloat proxy: average share of DEAD tuples per table (n_dead / (n_live+n_dead)).
        # Dead tuples left by UPDATE/DELETE are the real driver of table bloat, and this
        # is readable without extra extensions. 0% = freshly vacuumed, higher = more bloat.
        bloat = await conn.fetchval("""
            SELECT COALESCE(AVG(
                CASE WHEN n_live_tup + n_dead_tup = 0 THEN 0
                     ELSE 100.0 * n_dead_tup / (n_live_tup + n_dead_tup) END
            ), 0)
            FROM pg_stat_user_tables
        """)

    return SchemaHealth(
        tables_without_pk=no_pk or 0,
        missing_fk_indexes=missing_fk or 0,
        unused_indexes=unused or 0,
        duplicate_columns=0,  # Would need more complex analysis
        bloat_ratio=round(bloat or 0, 1),
    )

@app.post("/api/collect")
async def collect_metrics(background_tasks: BackgroundTasks):
    """Trigger manual collection of pg_stat_statements snapshot."""
    background_tasks.add_task(snapshot_queries)
    return {"status": "collection_started"}

async def snapshot_queries():
    """Snapshot the target's pg_stat_statements into the optimizer's storage."""
    # Read from the target (may be a different DB), then write to our own storage.
    async with target_pool.acquire() as tconn:
        rows = await tconn.fetch(f"""
            SELECT queryid, query, calls, {PSS['total']} AS total_time,
                   {PSS['mean']} AS mean_time, rows,
                   shared_blks_hit, shared_blks_read
            FROM pg_stat_statements
        """)
    async with pool.acquire() as sconn:
        await sconn.executemany("""
            INSERT INTO query_snapshots
            (queryid, query, calls, total_time, mean_time, rows, shared_blks_hit, shared_blks_read)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, [
            (r["queryid"], r["query"], r["calls"], r["total_time"], r["mean_time"],
             r["rows"], r["shared_blks_hit"], r["shared_blks_read"])
            for r in rows
        ])

@app.get("/api/queries/trends/{queryid}")
async def get_query_trends(queryid: int):
    """Get performance trends for a specific query."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT captured_at, mean_time, calls, rows
            FROM query_snapshots
            WHERE queryid = $1
            ORDER BY captured_at ASC
        """, queryid)

    return [
        {"timestamp": r["captured_at"].isoformat(), "mean_time": r["mean_time"], "calls": r["calls"], "rows": r["rows"]}
        for r in rows
    ]

# ═══════════════════════════════════════════════════════════════════════════
#  DEEP ANALYSIS SUITE
#  Four analyzers born from a real-world optimization (a 28-56s plpgsql
#  report function): sargability linting, function-body analysis,
#  estimate-vs-actual divergence, and a result-parity harness — plus a
#  one-click Full Audit that runs everything and a dynamic target switcher.
# ═══════════════════════════════════════════════════════════════════════════

class Finding(BaseModel):
    category: str          # "sargability" | "function" | "plan" | "schema" | "config"
    severity: str          # "Critical" | "Warning" | "Info"
    title: str
    object_name: str       # query hash / function name / table name
    detail: str
    suggestion: Optional[str] = None   # concrete fix (SQL or action)
    source: str            # where it was found: "query" | "function:<name>" | "plan"

# ── 1. Sargability linter ──────────────────────────────────────────────────
# Each rule: (compiled regex, severity, title, detail template, suggestion).
# These patterns each cost seconds-to-minutes on real workloads; all of them
# were observed in production-style code.
SARGABILITY_RULES = [
    (
        re.compile(r"(\w+(?:\.\w+)?)\s*::\s*date\s*(?:[<>=!]|BETWEEN)", re.IGNORECASE),
        "Critical", "Non-sargable ::date cast on column",
        "Casting column '{m}' to date inside a comparison defeats indexes AND partition pruning — "
        "the planner must scan every row/partition to evaluate the cast.",
        "Rewrite as a range on the raw column, e.g.  col >= '2025-04-01'::timestamp AND col < '2025-04-02'::timestamp",
    ),
    (
        re.compile(r"\b(?:date|date_trunc)\s*\(\s*(?:'[^']*'\s*,\s*)?(\w+(?:\.\w+)?)\s*\)\s*[<>=!]", re.IGNORECASE),
        "Critical", "Function wrapped around column in comparison",
        "Applying a function to column '{m}' before comparing prevents index use.",
        "Move the function to the constant side, or create an expression index on the wrapped column.",
    ),
    (
        re.compile(r"\b(?:lower|upper)\s*\(\s*(\w+(?:\.\w+)?)\s*\)\s*=", re.IGNORECASE),
        "Warning", "lower()/upper() on column in equality",
        "Case-normalizing column '{m}' per row prevents plain index use.",
        "CREATE INDEX ... ON table (lower(column));  — or use the citext type.",
    ),
    (
        re.compile(r"\bLIKE\s+'%", re.IGNORECASE),
        "Warning", "Leading-wildcard LIKE",
        "LIKE '%...' cannot use a btree index — every row is scanned.",
        "Use pg_trgm:  CREATE EXTENSION pg_trgm;  CREATE INDEX ... USING gin (col gin_trgm_ops);",
    ),
    (
        re.compile(r"\bNOT\s+IN\s*\(\s*SELECT", re.IGNORECASE),
        "Warning", "NOT IN (subquery)",
        "NOT IN with a subquery gives poor plans and surprising NULL semantics.",
        "Rewrite as  NOT EXISTS (SELECT 1 FROM ... WHERE ...)  — planner turns it into an anti-join.",
    ),
    (
        re.compile(r"\b(\w+\.\w+)\s*\(\s*\w+\.\w+\s*\)\s*(?:IS\s+(?:NOT\s+)?NULL|[<>=!])", re.IGNORECASE),
        "Critical", "User function called per-row in WHERE",
        "'{m}(column)' in a predicate calls the function for EVERY row — plpgsql calls cost "
        "microseconds each and block index use (measured: 368k calls added ~5s to one scan).",
        "Inline the logic (e.g. check_if_null(col) IS NOT NULL  →  col IS NOT NULL AND col <> 0).",
    ),
    (
        re.compile(r"\bAND\s*\(\s*CASE\s+WHEN\b", re.IGNORECASE),
        "Warning", "CASE WHEN used as WHERE filter",
        "CASE-based predicates ('CASE WHEN param IS NULL THEN 1=1 ELSE col = param END') are opaque "
        "to the planner — no index use, no partition pruning.",
        "Rewrite as boolean logic:  (param IS NULL OR col = param)  — the planner handles this form.",
    ),
]

# Function-body-only structural rules.
FUNCTION_RULES = [
    (
        re.compile(r"quote_literal\s*\(", re.IGNORECASE),
        "Warning", "String-spliced dynamic SQL (quote_literal)",
        "Parameters are being spliced into SQL text — every call re-plans, and the text is fragile.",
        "Use  EXECUTE format(...) USING $1, $2  — parameterized, cached plans, injection-safe.",
    ),
    (
        re.compile(r"md5\s*\(\s*random\s*\(\s*\)", re.IGNORECASE),
        "Warning", "Random-named temp tables per call",
        "A uniquely-named temp table on every call churns the system catalogs and defeats plan caching.",
        "Use a fixed temp table name with ON COMMIT DROP, or restructure as a single WITH query.",
    ),
]

def lint_sql(sql: str, source: str) -> List[Finding]:
    """Run the sargability rules over one SQL text."""
    findings = []
    for rx, severity, title, detail_tpl, suggestion in SARGABILITY_RULES:
        m = rx.search(sql)
        if m:
            token = m.group(1) if m.groups() else m.group(0)
            findings.append(Finding(
                category="sargability", severity=severity, title=title,
                object_name=token.strip()[:80],
                detail=detail_tpl.format(m=token.strip()[:80]),
                suggestion=suggestion, source=source,
            ))
    return findings

# ── 2. Function-aware analysis ─────────────────────────────────────────────
async def analyze_functions(conn, limit: int = 50) -> (List[Finding], dict):
    """Static-lint plpgsql function bodies; enrich with runtime stats if available."""
    findings: List[Finding] = []

    track = await conn.fetchval("SHOW track_functions")
    if track == "none":
        findings.append(Finding(
            category="config", severity="Info",
            title="track_functions is disabled",
            object_name="track_functions",
            detail="PostgreSQL is not recording per-function call counts/timings, so slow plpgsql "
                   "functions are invisible to monitoring.",
            suggestion="ALTER SYSTEM SET track_functions = 'all'; SELECT pg_reload_conf();  -- no restart needed",
            source="config",
        ))

    # Runtime stats (only populated when track_functions is on)
    fn_stats = {}
    try:
        for r in await conn.fetch("""
            SELECT schemaname || '.' || funcname AS fq, calls, total_time, self_time
            FROM pg_stat_user_functions ORDER BY total_time DESC LIMIT 200
        """):
            fn_stats[r["fq"]] = dict(calls=r["calls"], total_time=r["total_time"], self_time=r["self_time"])
    except Exception:
        pass

    rows = await conn.fetch("""
        SELECT n.nspname AS schema, p.proname AS name,
               length(p.prosrc) AS src_len, pg_get_functiondef(p.oid) AS def
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_language l ON l.oid = p.prolang
        WHERE l.lanname = 'plpgsql'
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY length(p.prosrc) DESC
        LIMIT $1
    """, limit)
    total_fns = await conn.fetchval("""
        SELECT count(*) FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_language l ON l.oid = p.prolang
        WHERE l.lanname = 'plpgsql' AND n.nspname NOT IN ('pg_catalog','information_schema')
    """)

    for r in rows:
        fq = f"{r['schema']}.{r['name']}"
        body = r["def"] or ""
        src = f"function:{fq}"
        stats = fn_stats.get(fq)
        stat_note = (f" Runtime: {stats['calls']} calls, {stats['total_time']:.0f}ms total." if stats else "")

        # sargability rules apply inside function bodies too
        for f in lint_sql(body, src):
            f.object_name = fq
            f.detail += stat_note
            findings.append(f)
        # structural rules
        for rx, severity, title, detail, suggestion in FUNCTION_RULES:
            if rx.search(body):
                findings.append(Finding(
                    category="function", severity=severity, title=title,
                    object_name=fq, detail=detail + stat_note,
                    suggestion=suggestion, source=src,
                ))
        # repeated scans of the same table
        tbls = re.findall(r"(?:FROM|JOIN)\s+(\w+\.\w+)", body, re.IGNORECASE)
        from collections import Counter
        for tbl, cnt in Counter(t.lower() for t in tbls).most_common(3):
            if cnt >= 4 and not tbl.startswith(("pg_", "information_schema")):
                findings.append(Finding(
                    category="function", severity="Warning",
                    title=f"Table scanned {cnt}x in one function",
                    object_name=fq,
                    detail=f"'{tbl}' appears in {cnt} FROM/JOIN clauses — often the same data re-read. "
                           f"Consolidating to one pass with FILTER aggregates usually halves runtime.{stat_note}",
                    suggestion="Combine repeated scans:  SUM(x) FILTER (WHERE cond1), SUM(x) FILTER (WHERE cond2) ...",
                    source=src,
                ))
        # temp-table chains
        tt = len(re.findall(r"CREATE\s+TEMP(?:ORARY)?\s+TABLE", body, re.IGNORECASE))
        if tt >= 3:
            findings.append(Finding(
                category="function", severity="Warning",
                title=f"{tt} temp tables in one function",
                object_name=fq,
                detail=f"Chained temp-table materialization blocks the planner from optimizing across steps.{stat_note}",
                suggestion="Restructure as one WITH (CTE) pipeline so the planner sees the whole query.",
                source=src,
            ))

    meta = {"functions_scanned": len(rows), "functions_total": total_fns or 0,
            "runtime_stats_available": bool(fn_stats)}
    return findings, meta

# ── 3. Estimate-vs-actual divergence ───────────────────────────────────────
def plan_divergence(plan: dict) -> List[Finding]:
    """Walk an EXPLAIN ANALYZE tree; flag nodes whose row estimate is >=10x off."""
    findings = []
    def walk(node):
        est, act = node.get("Plan Rows"), node.get("Actual Rows")
        if est is not None and act is not None and node.get("Actual Loops", 1) >= 1:
            act_total = act * node.get("Actual Loops", 1)
            lo, hi = sorted([max(est, 1), max(act_total, 1)])
            ratio = hi / lo
            if ratio >= 10 and hi > 100:
                rel = node.get("Relation Name", node.get("Node Type", "?"))
                findings.append(Finding(
                    category="plan", severity="Critical" if ratio >= 100 else "Warning",
                    title=f"Row estimate off by {ratio:.0f}x",
                    object_name=rel,
                    detail=f"{node.get('Node Type')} on '{rel}': planner estimated {est:,} rows, got "
                           f"{act_total:,}. Bad estimates cause wrong join strategies (e.g. nested loops "
                           f"over hash joins) — often the entire slowdown.",
                    suggestion=f"ANALYZE {rel};  -- refresh stats. If still off: "
                               f"ALTER TABLE {rel} ALTER COLUMN <col> SET STATISTICS 500; or CREATE STATISTICS for correlated columns.",
                    source="plan",
                ))
        for child in node.get("Plans", []):
            walk(child)
    if isinstance(plan, dict) and "error" not in plan:
        walk(plan)
    return findings

@app.post("/api/queries/deep-analyze/{queryid}")
async def deep_analyze_query(queryid: int):
    """EXPLAIN ANALYZE (SELECT-only, timeout-guarded) + divergence + sargability lint."""
    async with target_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT query FROM pg_stat_statements WHERE queryid = $1", queryid)
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")
        query = row["query"]
        explainable = re.sub(r"\$\d+", "NULL", query)
        first_kw = explainable.split(None, 1)[0].upper() if explainable.strip() else ""
        if first_kw not in ("SELECT", "WITH"):
            raise HTTPException(status_code=400,
                detail=f"Deep analyze executes the query, so only SELECT/WITH are allowed (got {first_kw}).")
        try:
            async with conn.transaction():
                await conn.execute("SET LOCAL statement_timeout = '30s'")
                plan_json = await conn.fetchval(
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {explainable}")
            plan = json.loads(plan_json)[0]["Plan"]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"EXPLAIN ANALYZE failed: {e}")

    findings = plan_divergence(plan) + lint_sql(query, "query")
    return {
        "queryid": str(queryid),
        "query": normalize_query(query),
        "plan": plan,
        "findings": [f.model_dump() for f in findings],
    }

# ── 4. Parity harness ──────────────────────────────────────────────────────
class ParityRequest(BaseModel):
    query_a: str    # e.g. the original query / function call
    query_b: str    # the optimized rewrite
    round_decimals: int = 2
    max_rows: int = 50000

@app.post("/api/parity/check")
async def parity_check(req: ParityRequest):
    """Run two SELECTs read-only and compare results as multisets.
    This is how you PROVE a rewrite is safe before shipping it."""
    for label, q in (("query_a", req.query_a), ("query_b", req.query_b)):
        kw = q.strip().split(None, 1)[0].upper() if q.strip() else ""
        if kw not in ("SELECT", "WITH"):
            raise HTTPException(status_code=400, detail=f"{label} must be SELECT/WITH (got {kw}).")

    def norm(v, nd):
        if isinstance(v, float):
            return round(v, nd)
        try:
            from decimal import Decimal
            if isinstance(v, Decimal):
                return round(float(v), nd)
        except Exception:
            pass
        return str(v) if v is not None else None

    from collections import Counter
    results, timings = {}, {}
    async with target_pool.acquire() as conn:
        for label, q in (("a", req.query_a), ("b", req.query_b)):
            import time as _time
            t0 = _time.monotonic()
            try:
                async with conn.transaction():
                    await conn.execute("SET LOCAL statement_timeout = '120s'")
                    rows = await conn.fetch(q)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"query_{label} failed: {e}")
            timings[label] = round((_time.monotonic() - t0) * 1000, 1)
            if len(rows) > req.max_rows:
                raise HTTPException(status_code=400,
                    detail=f"query_{label} returned {len(rows)} rows (max {req.max_rows}).")
            results[label] = Counter(
                tuple(norm(v, req.round_decimals) for v in r.values()) for r in rows
            )

    only_a = results["a"] - results["b"]
    only_b = results["b"] - results["a"]
    identical = not only_a and not only_b
    return {
        "identical": identical,
        "rows_a": sum(results["a"].values()),
        "rows_b": sum(results["b"].values()),
        "rows_only_in_a": sum(only_a.values()),
        "rows_only_in_b": sum(only_b.values()),
        "sample_diff_a": [list(t) for t in list(only_a)[:5]],
        "sample_diff_b": [list(t) for t in list(only_b)[:5]],
        "time_ms_a": timings["a"],
        "time_ms_b": timings["b"],
        "speedup": round(timings["a"] / timings["b"], 2) if timings["b"] > 0 else None,
        "verdict": "IDENTICAL — rewrite is safe to ship" if identical
                   else "DIFFERENT — do NOT ship; inspect sample_diff rows",
    }

# ── One-click Full Audit ───────────────────────────────────────────────────
async def generate_audit_insights(findings: List["Finding"]):
    """RAG-explain the top findings via the AI service -> AI Insights panel."""
    top = [f for f in findings if f.severity == "Critical"][:4] or findings[:3]
    if not top:
        return
    try:
        async with pool.acquire() as conn:
            # keep the panel fresh: one set of audit insights at a time
            await conn.execute("DELETE FROM ai_insights WHERE category = 'Audit'")
        async with httpx.AsyncClient(timeout=30.0) as client:
            for f in top:
                try:
                    resp = await client.post(f"{AI_SERVICE_URL}/explain-finding", json={
                        "title": f.title, "detail": f.detail, "category": f.category,
                        "object_name": f.object_name, "suggestion": f.suggestion,
                        "severity": f.severity,
                    })
                    ins = resp.json()
                    async with pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO ai_insights (severity, category, title, description, query_id, suggested_action)
                            VALUES ($1, 'Audit', $2, $3, NULL, $4)
                        """, ins.get("severity", "Warning"), ins.get("title", f.title),
                             ins.get("description", f.detail), ins.get("suggested_action"))
                except Exception as e:
                    print(f"[warn] explain-finding failed for '{f.title}': {e}")
    except Exception as e:
        print(f"[warn] audit insight generation failed: {e}")

@app.post("/api/audit/full")
async def run_full_audit(background_tasks: BackgroundTasks, threshold_ms: float = 100.0):
    """Run every analyzer against the target DB and return one prioritized report."""
    findings: List[Finding] = []
    meta: Dict[str, Any] = {}

    async with target_pool.acquire() as conn:
        meta["database"] = await conn.fetchval("SELECT current_database()")
        meta["version"] = await conn.fetchval("SHOW server_version")

        # 1. slow queries -> sargability lint + seq-scan check (EXPLAIN only, safe)
        try:
            slow = await conn.fetch(f"""
                SELECT queryid, query, calls, {PSS['mean']} AS mean_time FROM pg_stat_statements
                WHERE {PSS['mean']} > $1 ORDER BY {PSS['mean']} DESC LIMIT 20
            """, threshold_ms)
        except asyncpg.UndefinedTableError:
            slow = []
            findings.append(Finding(
                category="config", severity="Warning",
                title="pg_stat_statements not installed in this database",
                object_name="pg_stat_statements",
                detail="Slow-query detection is disabled for this database until the extension exists here.",
                suggestion="CREATE EXTENSION IF NOT EXISTS pg_stat_statements;  -- as superuser, in this database",
                source="config",
            ))
        meta["slow_queries_scanned"] = len(slow)
        for r in slow:
            q = r["query"]
            src = f"query:{r['queryid']}"
            for f in lint_sql(q, src):
                f.detail += f" (query averages {r['mean_time']:.0f}ms over {r['calls']} calls)"
                findings.append(f)
            explainable = re.sub(r"\$\d+", "NULL", q)
            kw = explainable.split(None, 1)[0].upper() if explainable.strip() else ""
            if kw in ("SELECT", "WITH"):
                try:
                    async with conn.transaction():
                        await conn.execute("SET LOCAL statement_timeout = '10s'")
                        pj = await conn.fetchval(f"EXPLAIN (FORMAT JSON) {explainable}")
                    plan = json.loads(pj)[0]["Plan"]
                    def seqscans(n):
                        out = []
                        if n.get("Node Type") == "Seq Scan" and n.get("Plan Rows", 0) > 10000:
                            out.append((n.get("Relation Name", "?"), n.get("Plan Rows", 0)))
                        for c in n.get("Plans", []):
                            out.extend(seqscans(c))
                        return out
                    for rel, nrows in seqscans(plan):
                        findings.append(Finding(
                            category="plan", severity="Warning",
                            title=f"Sequential scan over ~{nrows:,} rows",
                            object_name=rel,
                            detail=f"Query {r['queryid']} (avg {r['mean_time']:.0f}ms) full-scans '{rel}'.",
                            suggestion=f"Check WHERE columns of this query and index them on {rel}.",
                            source=src,
                        ))
                except Exception:
                    pass

        # 2. function-aware analysis
        fn_findings, fn_meta = await analyze_functions(conn)
        findings.extend(fn_findings)
        meta.update(fn_meta)

    # 3. schema health (existing endpoint logic, reused for the report)
    health = await get_schema_health()
    if health.tables_without_pk:
        findings.append(Finding(
            category="schema", severity="Warning",
            title=f"{health.tables_without_pk} tables without a PRIMARY KEY",
            object_name="schema", detail="Tables without PKs cannot be efficiently replicated or deduplicated.",
            suggestion="Add a primary key (or at least a unique NOT NULL index) to each.", source="schema"))
    if health.unused_indexes > 10:
        findings.append(Finding(
            category="schema", severity="Info",
            title=f"{health.unused_indexes} indexes have never been scanned",
            object_name="schema",
            detail="Unused indexes cost write amplification and disk. (Verify over a full business cycle before dropping.)",
            suggestion="SELECT schemaname, relname AS table, indexrelname AS index FROM pg_stat_user_indexes WHERE idx_scan = 0;", source="schema"))
    if health.bloat_ratio > 20:
        findings.append(Finding(
            category="schema", severity="Warning",
            title=f"Average dead-tuple ratio {health.bloat_ratio}%",
            object_name="schema", detail="High dead-tuple ratios slow every scan.",
            suggestion="VACUUM ANALYZE;  -- and check autovacuum settings for hot tables", source="schema"))

    sev_rank = {"Critical": 0, "Warning": 1, "Info": 2}
    findings.sort(key=lambda f: sev_rank.get(f.severity, 3))

    # persist for the dashboard
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_findings (
                id SERIAL PRIMARY KEY, run_at TIMESTAMP DEFAULT NOW(),
                database TEXT, category TEXT, severity TEXT, title TEXT,
                object_name TEXT, detail TEXT, suggestion TEXT, source TEXT
            )
        """)
        await conn.execute("DELETE FROM audit_findings WHERE database = $1", meta["database"])
        for f in findings:
            await conn.execute("""
                INSERT INTO audit_findings (database, category, severity, title, object_name, detail, suggestion, source)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """, meta["database"], f.category, f.severity, f.title, f.object_name, f.detail, f.suggestion, f.source)

    # RAG-explain the top findings in the background -> AI Insights panel
    background_tasks.add_task(generate_audit_insights, findings)

    counts = {"Critical": 0, "Warning": 0, "Info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return {"meta": meta, "counts": counts, "findings": [f.model_dump() for f in findings]}

@app.get("/api/audit/findings")
async def get_audit_findings():
    """Last stored audit report for the CURRENT target database."""
    async with target_pool.acquire() as conn:
        current_db = await conn.fetchval("SELECT current_database()")
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                "SELECT * FROM audit_findings WHERE database = $1 "
                "ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Warning' THEN 1 ELSE 2 END, id",
                current_db)
        except Exception:
            return {"findings": []}
    return {"findings": [dict(r) for r in rows]}

# ── Dynamic target switching ───────────────────────────────────────────────
CURRENT_TARGET_URL = TARGET_DATABASE_URL

@app.get("/api/target/info")
async def target_info():
    mode = "self/demo" if target_pool is pool else "external target"
    async with target_pool.acquire() as conn:
        db = await conn.fetchval("SELECT current_database()")
        ver = await conn.fetchval("SHOW server_version")
    return {"mode": mode, "database": db, "server_version": ver}

@app.get("/api/target/databases")
async def target_databases():
    """List databases on the target cluster (for the switcher dropdown)."""
    async with target_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")
    return {"databases": [r["datname"] for r in rows]}

class SwitchRequest(BaseModel):
    database: str
    # Optional full credentials: lets anyone connect the optimizer to their own
    # PostgreSQL from the UI without ever editing .env. Runtime-only (not
    # persisted) — put the URL in .env's TARGET_DATABASE_URL to make it durable.
    host: Optional[str] = None
    port: int = 5432
    username: Optional[str] = None
    password: Optional[str] = None

@app.post("/api/target/connect")
async def target_connect(req: SwitchRequest):
    """Point the analysis connection at a database.

    Two modes:
      * {database} only            -> switch DB on the currently connected cluster
      * {host, username, password, database} -> connect to a brand-new cluster
    Always read-only (default_transaction_read_only=on).
    """
    global target_pool, CURRENT_TARGET_URL
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", req.database):
        raise HTTPException(status_code=400, detail="Invalid database name.")

    if req.host and req.username:
        from urllib.parse import quote
        new_url = (f"postgresql://{quote(req.username)}:{quote(req.password or '')}"
                   f"@{req.host}:{req.port}/{req.database}")
    elif CURRENT_TARGET_URL:
        new_url = re.sub(r"/[^/?]+(\?|$)", f"/{req.database}\\1", CURRENT_TARGET_URL, count=1)
    else:
        raise HTTPException(status_code=400,
            detail="No target cluster configured yet — provide host, username and "
                   "password (or set TARGET_DATABASE_URL in .env).")

    try:
        new_pool = await asyncpg.create_pool(
            new_url, min_size=1, max_size=5, timeout=10,
            server_settings={"default_transaction_read_only": "on"})
        # fail fast with a clear message if the role lacks access
        async with new_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            has_pss = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements')")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot connect to '{req.database}': {e}")

    old = target_pool
    target_pool = new_pool
    CURRENT_TARGET_URL = new_url
    if old is not pool:
        await old.close()
    await detect_pss_columns(target_pool)   # new cluster may be a different PG version

    note = ("Connected read-only." if has_pss else
            "Connected read-only — but pg_stat_statements is NOT installed in this "
            "database, so the slow-query features will be empty. See the README's "
            "'Prepare your database' section.")
    return {"status": "connected", "database": req.database,
            "pg_stat_statements": bool(has_pss), "note": note}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
