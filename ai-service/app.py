"""
AI Database Optimizer - AI/RAG Service
Lightweight Python service for generating natural-language insights.
Uses sentence-transformers for embeddings and a local LLM (or mock for demo).
"""
import os
import json
import asyncio
from typing import List, Dict, Any

from flask import Flask, request, jsonify
import asyncpg
from sentence_transformers import SentenceTransformer
import numpy as np

app = Flask(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5432/optimizer")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Load embedding model (lightweight, ~80MB)
print("Loading embedding model...")
model = SentenceTransformer(EMBEDDING_MODEL)
print("Embedding model loaded.")

# ── Knowledge Base (seed data for RAG) ────────────────────────────────────
KNOWLEDGE_BASE = [
    {
        "content": "Sequential scans on large tables are a primary cause of slow queries. Adding a B-tree index on the filtered/joined column typically enables an Index Scan and reduces query time by 90-99%.",
        "category": "indexing",
        "tags": ["seq_scan", "index", "performance"]
    },
    {
        "content": "Hash joins are efficient for large datasets but require memory. If work_mem is too small, the database will spill to disk (temp files), causing severe slowdowns. Increase work_mem or enable parallel hash joins.",
        "category": "join_optimization",
        "tags": ["hash_join", "memory", "work_mem"]
    },
    {
        "content": "Lock contention in UPDATE statements often occurs when multiple transactions update the same rows. Consider using advisory locks, batching updates, or reducing transaction scope.",
        "category": "concurrency",
        "tags": ["lock", "update", "contention"]
    },
    {
        "content": "Partial indexes (with WHERE clauses) are smaller and faster than full indexes when queries always filter on the same condition. Example: CREATE INDEX idx ON orders(status) WHERE status = 'pending'.",
        "category": "indexing",
        "tags": ["partial_index", "where_clause"]
    },
    {
        "content": "Table bloat occurs when UPDATE/DELETE leaves dead tuples. Run VACUUM ANALYZE regularly. For severe bloat, use pg_repack or CLUSTER to rebuild the table without locking.",
        "category": "maintenance",
        "tags": ["bloat", "vacuum", "pg_repack"]
    },
    {
        "content": "Covering indexes (INCLUDE columns) allow Index-Only Scans, avoiding heap fetches entirely. This is ideal for queries that select a few columns from a large table.",
        "category": "indexing",
        "tags": ["covering_index", "include", "index_only_scan"]
    },
    {
        "content": "For time-series data, consider range partitioning by month or day. This enables partition pruning, where the planner only scans relevant partitions for time-range queries.",
        "category": "partitioning",
        "tags": ["partitioning", "time_series", "pruning"]
    },
    {
        "content": "High cache hit rate (shared_buffers) should be >99%. If below 95%, increase shared_buffers or investigate why working set doesn't fit in memory.",
        "category": "memory",
        "tags": ["cache", "shared_buffers", "memory"]
    },
    {
        "content": "Casting a column inside a comparison (e.g. transaction_date::date >= '2025-01-01') is non-sargable: it defeats btree indexes AND partition pruning, forcing full scans. Rewrite as a half-open range on the raw column: col >= '2025-01-01'::timestamp AND col < '2025-01-02'::timestamp.",
        "category": "sargability",
        "tags": ["cast", "date", "partition_pruning", "sargable"]
    },
    {
        "content": "Calling a user-defined plpgsql function per row inside WHERE (e.g. check_if_null(col) IS NOT NULL) adds microseconds per row and blocks index use. Inline the logic as plain boolean SQL: col IS NOT NULL AND col <> 0. On large tables this alone can save seconds per query.",
        "category": "sargability",
        "tags": ["plpgsql", "per_row_function", "where"]
    },
    {
        "content": "CASE WHEN used as a WHERE filter (CASE WHEN param IS NULL THEN 1=1 ELSE col = param END) is opaque to the planner: no index use, no pruning. Rewrite as boolean logic the planner understands: (param IS NULL OR col = param).",
        "category": "sargability",
        "tags": ["case_when", "where", "planner"]
    },
    {
        "content": "Aggregate-then-join beats join-then-aggregate on large fact tables: aggregate the big table down to a small result FIRST, then join dimension/master tables. This prevents the planner from choosing pathological nested-loop probes and shrinks every downstream step.",
        "category": "query_shape",
        "tags": ["aggregate", "join_order", "fact_table"]
    },
    {
        "content": "Chained temp tables inside a function (CREATE TEMP TABLE t1 AS ...; t2 AS SELECT FROM t1; ...) block the planner from optimizing across steps and churn the catalogs — especially with random-generated names. Restructure as a single WITH (CTE) pipeline so the whole query is planned at once.",
        "category": "plpgsql",
        "tags": ["temp_table", "cte", "function"]
    },
    {
        "content": "String-spliced dynamic SQL via quote_literal(param) re-plans on every call and is fragile. Use EXECUTE format(...) USING $1, $2: parameterized, plan-cacheable, injection-safe.",
        "category": "plpgsql",
        "tags": ["dynamic_sql", "quote_literal", "execute_using"]
    },
    {
        "content": "When the planner's row estimate diverges >=10x from actual rows (visible in EXPLAIN ANALYZE), join strategy choices go wrong — e.g. nested loops over hash joins. Fix with ANALYZE on the table, raise the column's statistics target, or CREATE STATISTICS for correlated columns.",
        "category": "planner",
        "tags": ["estimates", "statistics", "analyze"]
    },
    {
        "content": "A covering partial index — CREATE INDEX ON t (key_col) INCLUDE (needed_cols) WHERE common_filter — enables index-only scans for a specific hot query, so wide heap rows (100+ columns) are never touched. Match the WHERE clause to the query's exact predicates.",
        "category": "indexing",
        "tags": ["covering_index", "partial_index", "index_only_scan"]
    },
    {
        "content": "Before shipping any query rewrite, prove result parity: run original and rewrite side by side, compare row multisets with floats rounded to 2 decimals, in both directions. Identical results plus timings gives a safe, quantified speedup.",
        "category": "verification",
        "tags": ["parity", "rewrite", "testing"]
    },
]

# Precompute KB embeddings once at startup — retrieval then is a fast dot product.
print("Embedding knowledge base...")
KB_EMBEDDINGS = model.encode([item["content"] for item in KNOWLEDGE_BASE], normalize_embeddings=True)
print(f"Knowledge base embedded ({len(KNOWLEDGE_BASE)} entries).")

def kb_search(query_text: str, top_k: int = 3):
    """Cosine-similarity search over the precomputed KB embeddings."""
    q = model.encode(query_text, normalize_embeddings=True)
    sims = KB_EMBEDDINGS @ q
    order = sims.argsort()[::-1][:top_k]
    return [(float(sims[i]), KNOWLEDGE_BASE[i]) for i in order]

# ── Database Helpers ─────────────────────────────────────────────────────────
async def get_db_pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

async def seed_knowledge_base():
    """Embed and store knowledge base in pgvector."""
    pool = await get_db_pool()
    try:
        # NOTE: pool.close() must happen AFTER the acquire block exits — closing
        # while a connection is still checked out hangs Pool.close() forever.
        async with pool.acquire() as conn:
            # The backend usually creates this table, but this service can start
            # first — create it ourselves so seeding never depends on startup order.
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

            # Re-seed whenever the KB content changes size (simple version check).
            count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
            if count == len(KNOWLEDGE_BASE):
                return
            await conn.execute("DELETE FROM knowledge_embeddings")

            for item in KNOWLEDGE_BASE:
                # asyncpg has no codec for the pgvector type: pass the vector as
                # its text form ('[0.1,0.2,...]') and cast server-side.
                embedding_text = "[" + ",".join(f"{x:.6f}" for x in model.encode(item["content"]).tolist()) + "]"
                await conn.execute("""
                    INSERT INTO knowledge_embeddings (content, embedding, category)
                    VALUES ($1, $2::vector, $3)
                """, item["content"], embedding_text, item["category"])
        print(f"Knowledge base seeded ({len(KNOWLEDGE_BASE)} entries).")
    finally:
        await pool.close()

# ── RAG Functions ────────────────────────────────────────────────────────
def retrieve_context(query_text: str, plan: dict, top_k: int = 3) -> List[str]:
    """Retrieve relevant knowledge base entries using vector similarity."""
    # Build a search query from the plan + query text
    search_terms = []

    def extract_plan_info(node):
        if node.get("Node Type") == "Seq Scan":
            search_terms.append("seq_scan indexing")
        if node.get("Node Type") == "Hash Join":
            search_terms.append("hash_join memory")
        if node.get("Node Type") == "Nested Loop":
            search_terms.append("nested_loop optimization")
        for child in node.get("Plans", []):
            extract_plan_info(child)

    extract_plan_info(plan)
    search_query = " ".join(search_terms) + " " + query_text[:200]
    return [item["content"] for _, item in kb_search(search_query, top_k)]

def generate_insight(query: str, plan: dict, recommendations: List[Dict]) -> Dict[str, str]:
    """Generate a natural-language insight using RAG + rule-based generation."""

    # Retrieve relevant context
    context = retrieve_context(query, plan)

    # Analyze plan structure
    def analyze_plan(node, depth=0):
        issues = []
        if node.get("Node Type") == "Seq Scan":
            rel = node.get("Relation Name", "a table")
            rows = node.get("Plan Rows", 0)
            issues.append(f"Sequential scan on {rel} scanning {rows:,} rows")
        if node.get("Node Type") == "Nested Loop":
            issues.append("Nested loop join detected — may be slow on large datasets")
        if node.get("Total Cost", 0) > 10000:
            issues.append("Very high estimated cost — query needs optimization")
        for child in node.get("Plans", []):
            issues.extend(analyze_plan(child, depth + 1))
        return issues

    plan_issues = analyze_plan(plan)

    # Determine severity
    severity = "Info"
    if any("Seq Scan" in i for i in plan_issues) and any(r.get("impact") == "High" for r in recommendations):
        severity = "Critical"
    elif plan_issues:
        severity = "Warning"

    # Generate explanation
    explanation_parts = []

    if plan_issues:
        explanation_parts.append(f"Query analysis found {len(plan_issues)} issue(s):")
        for issue in plan_issues:
            explanation_parts.append(f"  • {issue}")

    if recommendations:
        explanation_parts.append("\nRecommended indexes:")
        for rec in recommendations[:3]:
            explanation_parts.append(f"  → {rec['index_def']} (estimated {rec['estimated_improvement_pct']:.0f}% improvement)")

    # Add RAG context
    if context:
        explanation_parts.append(f"\nRelevant knowledge:")
        for ctx in context[:2]:
            explanation_parts.append(f"  - {ctx[:150]}...")

    description = "\n".join(explanation_parts)

    # Suggested action
    suggested_action = None
    if recommendations:
        suggested_action = recommendations[0]["index_def"]
    elif "Seq Scan" in str(plan_issues):
        suggested_action = "Review query filters and add appropriate indexes"

    return {
        "severity": severity,
        "category": "Performance",
        "title": ("Query Performance Analysis"
                  + (f" — {plan['Node Type']}" if isinstance(plan, dict) and plan.get('Node Type') else "")),
        "description": description,
        "suggested_action": suggested_action,
        "context_sources": len(context),
    }

# ── Flask Routes ───────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "model": EMBEDDING_MODEL})

@app.route("/generate-insight", methods=["POST"])
def generate_insight_endpoint():
    data = request.get_json()
    query = data.get("query", "")
    plan = data.get("plan", {})
    recommendations = data.get("recommendations", [])

    insight = generate_insight(query, plan, recommendations)
    return jsonify(insight)

@app.route("/embed", methods=["POST"])
def embed_text():
    """Embed arbitrary text for storage in vector DB."""
    data = request.get_json()
    text = data.get("text", "")
    embedding = model.encode(text).tolist()
    return jsonify({"embedding": embedding, "dimensions": len(embedding)})

@app.route("/search-knowledge", methods=["POST"])
def search_knowledge():
    """Search knowledge base by semantic similarity."""
    data = request.get_json()
    query = data.get("query", "")
    top_k = data.get("top_k", 3)
    results = [{"score": s, **item} for s, item in kb_search(query, top_k)]
    return jsonify({"results": results})

@app.route("/explain-finding", methods=["POST"])
def explain_finding():
    """RAG explanation for an audit finding: retrieve the most relevant tuning
    knowledge and compose a grounded, human-readable explanation."""
    data = request.get_json()
    title = data.get("title", "")
    detail = data.get("detail", "")
    category = data.get("category", "")
    object_name = data.get("object_name", "")
    suggestion = data.get("suggestion", "")

    context = kb_search(f"{category} {title} {detail}"[:400], top_k=2)

    parts = [f"Audit found: {title} (in {object_name})." if object_name else f"Audit found: {title}."]
    if detail:
        parts.append(detail)
    if context:
        parts.append("\nWhy this matters (from tuning knowledge base):")
        for score, item in context:
            parts.append(f"  • {item['content']}")
    if suggestion:
        parts.append(f"\nRecommended fix:\n  {suggestion}")

    severity = data.get("severity", "Warning")
    return jsonify({
        "severity": severity,
        "category": "Audit",
        "title": title,
        "description": "\n".join(parts),
        "suggested_action": suggestion or None,
        "context_sources": len(context),
    })

# ── Startup ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Seed knowledge base on startup — but never let a seeding failure take the
    # whole service down (insight generation works from the in-memory KB too).
    try:
        asyncio.run(seed_knowledge_base())
    except Exception as e:
        print(f"[warn] knowledge base seeding failed (service continues): {e}")
    # debug=False: Flask's auto-reloader re-imports the module (re-downloading the
    # model and re-seeding) and previously hung the whole service on a stuck pool.
    app.run(host="0.0.0.0", port=5000, debug=False)
