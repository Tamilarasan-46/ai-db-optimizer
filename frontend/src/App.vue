<template>
  <div class="min-h-screen">
    <UiHost />
    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <header class="bg-slate-900 text-white">
      <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 bg-emerald-500 rounded-lg flex items-center justify-center shrink-0">
            <Database class="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 class="text-base font-bold leading-tight">AI Database Optimizer</h1>
            <p class="text-slate-400 text-[11px] leading-tight">audit · analyze · fix · verify</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <span class="hidden sm:inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-full px-2.5 py-1"
            title="Connections to analysed databases are forced read-only at the server level">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
            Read-only
          </span>
          <TargetSwitcher />
        </div>
      </div>
    </header>

    <main class="max-w-7xl mx-auto p-6 space-y-6">
      <!-- ── KPI strip ──────────────────────────────────────────────────── -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Slow Queries" :value="stats.slow_queries" subtitle="> 100ms mean" color="red" />
        <StatCard title="Index Suggestions" :value="stats.pending_recommendations" subtitle="pending review" color="amber" />
        <StatCard title="Avg Latency" :value="stats.avg_latency_ms + 'ms'" :subtitle="stats.total_queries.toLocaleString() + ' queries tracked'" color="emerald" />
        <StatCard title="Cache Hit Rate" :value="stats.cache_hit_rate + '%'" subtitle="shared buffers" color="blue" />
      </div>

      <!-- ── 1. AUDIT (hero) + AI insights ──────────────────────────────── -->
      <div class="section-label">Audit &amp; AI Insights</div>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 !mt-2">
        <div class="lg:col-span-2">
          <AuditPanel />
        </div>
        <div class="card h-[30rem]">
          <div class="card-header">
            <h2 class="card-title">
              <Zap class="w-4 h-4 text-purple-500" />
              AI Insights
              <span v-if="insights.length" class="card-count">{{ insights.length }}</span>
            </h2>
          </div>
          <div class="card-body p-3 space-y-3">
            <InsightCard v-for="insight in insights" :key="insight.id" :insight="insight" />
            <div v-if="insights.length === 0" class="h-full flex flex-col items-center justify-center text-center text-slate-400 gap-1 py-10">
              <Zap class="w-6 h-6 text-slate-300" />
              <span class="text-sm">No insights yet</span>
              <span class="text-xs">Analyze a slow query to generate one</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ── 2. INVESTIGATE: slow queries + context column ──────────────── -->
      <div class="section-label">Investigate</div>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 !mt-2">
        <div class="lg:col-span-2 card h-[30rem]">
          <div class="card-header">
            <h2 class="card-title">
              <AlertTriangle class="w-4 h-4 text-red-500" />
              Slow Queries
              <span v-if="slowQueries.length" class="card-count">{{ slowQueries.length }}</span>
            </h2>
            <button
              @click="refreshQueries"
              :disabled="loading"
              class="text-xs font-medium bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-600 px-3 py-1.5 rounded-md transition-colors"
            >{{ loading ? 'Refreshing…' : 'Refresh' }}</button>
          </div>
          <div class="card-body divide-y divide-slate-50">
            <button
              v-for="query in slowQueries"
              :key="query.queryid"
              @click="analyzeQuery(query.queryid)"
              class="w-full text-left px-4 py-3 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-inset"
              :class="selectedQueryId === query.queryid ? 'bg-emerald-50/70' : 'hover:bg-slate-50'"
            >
              <div class="flex items-center gap-3">
                <code class="flex-1 min-w-0 truncate text-xs text-slate-700">{{ query.query }}</code>
                <span class="metric shrink-0 text-xs font-semibold px-2 py-0.5 rounded" :class="latencyClass(query.mean_time)">
                  {{ query.mean_time.toFixed(0) }}ms
                </span>
              </div>
              <div class="mt-1.5 flex items-center gap-4 text-[11px] text-slate-400 metric">
                <span class="flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full" :class="query.shared_blks_read > query.shared_blks_hit ? 'bg-orange-400' : 'bg-sky-400'"></span>
                  {{ query.shared_blks_read > query.shared_blks_hit ? 'disk-read heavy' : 'cpu heavy' }}
                </span>
                <span>{{ query.calls.toLocaleString() }} calls</span>
                <span>{{ query.rows.toLocaleString() }} rows</span>
                <span v-if="selectedQueryId === query.queryid" class="ml-auto text-emerald-600 font-medium">analyzing ▸</span>
              </div>
            </button>
            <div v-if="slowQueries.length === 0" class="h-full flex flex-col items-center justify-center text-center text-slate-400 gap-1 py-10">
              <AlertTriangle class="w-6 h-6 text-slate-300" />
              <span class="text-sm">No slow queries detected</span>
              <span class="text-xs">Run some workload against the target, then Refresh</span>
            </div>
          </div>
        </div>

        <!-- context column: schema / trends / rag, equal thirds -->
        <div class="grid grid-rows-3 gap-6 h-[30rem]">
          <SchemaHealthCard :health="schemaHealth" />
          <PerformanceTrends />
          <RAGStatus />
        </div>
      </div>

      <!-- ── 3. Plan visualization (appears on analyze) ─────────────────── -->
      <div v-if="selectedPlan" class="card">
        <div class="card-header">
          <h2 class="card-title">
            <BarChart3 class="w-4 h-4 text-blue-500" />
            Query Plan
            <span v-if="deepDone" class="card-count normal-case bg-emerald-100 text-emerald-700">actual timings</span>
          </h2>
          <div class="flex items-center gap-2">
            <button
              v-if="canDeepAnalyze && !deepDone"
              @click="deepAnalyze"
              :disabled="deepBusy"
              class="text-xs font-medium px-3 py-1.5 rounded-md transition-colors"
              :class="deepBusy ? 'bg-slate-100 text-slate-400' : 'bg-blue-600 hover:bg-blue-700 text-white'"
              title="Runs EXPLAIN ANALYZE: executes the query (SELECT-only, 30s timeout) for real timings + estimate checks"
            >{{ deepBusy ? 'Running…' : '⚡ Deep analyze' }}</button>
            <button @click="closePlan" class="text-slate-400 hover:text-slate-600 transition-colors">
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>
        <div class="card-body max-h-[26rem] p-4">
          <QueryPlanVisualizer :plan="selectedPlan" />

          <!-- deep-analyze findings (estimate divergence + sargability) -->
          <div v-if="deepFindings.length" class="mt-4 space-y-2">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500">Deep-analysis findings</h3>
            <div v-for="(f, i) in deepFindings" :key="i" class="border border-slate-100 rounded-lg p-3">
              <div class="flex items-center gap-2 text-[13px] font-medium text-slate-800">
                <span class="w-1.5 h-1.5 rounded-full shrink-0"
                  :class="f.severity === 'Critical' ? 'bg-red-500' : f.severity === 'Warning' ? 'bg-amber-500' : 'bg-blue-400'"></span>
                {{ f.title }}
                <code class="text-[11px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-500">{{ f.object_name }}</code>
              </div>
              <p class="text-xs text-slate-500 mt-1 leading-relaxed">{{ f.detail }}</p>
              <pre v-if="f.suggestion" class="mt-2 text-[11px] bg-slate-900 text-emerald-300 rounded-lg p-2.5 overflow-x-auto scroll-slim whitespace-pre-wrap">{{ f.suggestion }}</pre>
            </div>
          </div>
          <div v-else-if="deepDone" class="mt-3 text-xs text-emerald-600">
            ✓ Deep analysis found no estimate divergence or sargability issues in this query.
          </div>

          <div v-if="selectedInsight" class="mt-4 bg-slate-50 border border-slate-100 rounded-lg p-4">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">AI Explanation</h3>
            <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-line">{{ selectedInsight }}</p>
          </div>
        </div>
      </div>

      <!-- ── 4. ACT: index recommendations ──────────────────────────────── -->
      <div class="section-label">Act</div>
      <div class="card h-80 !mt-2">
        <div class="card-header">
          <h2 class="card-title">
            <List class="w-4 h-4 text-amber-500" />
            Index Recommendations
            <span v-if="recommendations.length" class="card-count">{{ recommendations.length }}</span>
          </h2>
        </div>
        <div class="card-body">
          <table class="w-full text-sm">
            <thead class="bg-slate-50/90 backdrop-blur text-slate-500 sticky top-0 z-10">
              <tr class="text-left text-[11px] uppercase tracking-wide">
                <th class="px-4 py-2.5 font-semibold">Table</th>
                <th class="px-4 py-2.5 font-semibold">Recommended Index</th>
                <th class="px-4 py-2.5 font-semibold">Est. Improvement</th>
                <th class="px-4 py-2.5 font-semibold">Impact</th>
                <th class="px-4 py-2.5 font-semibold text-right">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-50">
              <tr v-for="rec in recommendations" :key="rec.id || rec.index_def" class="hover:bg-slate-50 transition-colors">
                <td class="px-4 py-2.5 font-mono text-xs text-slate-600">{{ rec.table_name }}</td>
                <td class="px-4 py-2.5 font-mono text-xs text-emerald-700 max-w-md truncate" :title="rec.index_def">{{ rec.index_def }}</td>
                <td class="px-4 py-2.5 metric">
                  <span class="text-emerald-600 font-semibold">-{{ rec.estimated_improvement_pct.toFixed(0) }}%</span>
                  <span class="text-slate-400 text-xs ml-1">({{ rec.current_cost.toFixed(0) }} → {{ rec.new_cost.toFixed(0) }})</span>
                </td>
                <td class="px-4 py-2.5"><ImpactBadge :impact="rec.impact" /></td>
                <td class="px-4 py-2.5 text-right">
                  <button
                    @click="applyRecommendation(rec)"
                    class="text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
                  >Apply</button>
                </td>
              </tr>
              <tr v-if="recommendations.length === 0">
                <td colspan="5" class="px-4 py-12 text-center text-slate-400 text-sm">
                  No recommendations yet — analyze a slow query or run the Full Audit.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ── 5. VERIFY: rewrite parity ───────────────────────────────────── -->
      <div class="section-label">Verify</div>
      <ParityCard class="!mt-2" />

      <footer class="text-center text-[11px] text-slate-400 pb-4">
        Read-only against the target database · EXPLAIN estimates unless deep-analyze is used
      </footer>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import {
  Database, AlertTriangle, Zap, BarChart3, X, List
} from 'lucide-vue-next'
import StatCard from './components/StatCard.vue'
import InsightCard from './components/InsightCard.vue'
import QueryPlanVisualizer from './components/QueryPlanVisualizer.vue'
import ImpactBadge from './components/ImpactBadge.vue'
import SchemaHealthCard from './components/SchemaHealthCard.vue'
import PerformanceTrends from './components/PerformanceTrends.vue'
import RAGStatus from './components/RAGStatus.vue'
import AuditPanel from './components/AuditPanel.vue'
import TargetSwitcher from './components/TargetSwitcher.vue'
import ParityCard from './components/ParityCard.vue'
import UiHost from './components/UiHost.vue'
import { notify, confirmDialog } from './ui.js'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

const stats = ref({
  slow_queries: 0,
  total_queries: 0,
  avg_latency_ms: 0,
  cache_hit_rate: 0,
  pending_recommendations: 0
})

const slowQueries = ref([])
const insights = ref([])
const recommendations = ref([])
const schemaHealth = ref({})
const selectedPlan = ref(null)
const selectedInsight = ref('')
const selectedQueryId = ref(null)
const loading = ref(false)
const deepBusy = ref(false)
const deepDone = ref(false)
const deepFindings = ref([])

// deep analyze executes the query, so only offer it for SELECT/WITH statements
const canDeepAnalyze = computed(() => {
  const q = slowQueries.value.find(x => x.queryid === selectedQueryId.value)
  return q && /^\s*(SELECT|WITH)\b/i.test(q.query)
})

const closePlan = () => {
  selectedPlan.value = null
  selectedQueryId.value = null
  deepDone.value = false
  deepFindings.value = []
}

const deepAnalyze = async () => {
  deepBusy.value = true
  try {
    const { data } = await axios.post(
      `${API_BASE}/queries/deep-analyze/${selectedQueryId.value}`, null, { timeout: 60000 })
    selectedPlan.value = data.plan
    deepFindings.value = data.findings
    deepDone.value = true
  } catch (e) {
    notify('Deep analyze failed: ' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    deepBusy.value = false
  }
}

// latency severity scale: <250 slate, <1000 amber, >=1000 red
const latencyClass = (ms) => {
  if (ms >= 1000) return 'bg-red-50 text-red-600'
  if (ms >= 250) return 'bg-amber-50 text-amber-600'
  return 'bg-slate-100 text-slate-500'
}

const fetchStats = async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/stats/summary`)
    stats.value = data
  } catch (e) {
    console.error('Failed to fetch stats:', e)
  }
}

const fetchSlowQueries = async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/queries/slow`)
    slowQueries.value = data
  } catch (e) {
    console.error('Failed to fetch slow queries:', e)
  }
}

const fetchInsights = async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/insights`)
    insights.value = data
  } catch (e) {
    console.error('Failed to fetch insights:', e)
  }
}

const fetchRecommendations = async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/recommendations`)
    recommendations.value = data
  } catch (e) {
    console.error('Failed to fetch recommendations:', e)
  }
}

const fetchSchemaHealth = async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/schema/health`)
    schemaHealth.value = data
  } catch (e) {
    console.error('Failed to fetch schema health:', e)
  }
}

const analyzeQuery = async (queryid) => {
  loading.value = true
  selectedQueryId.value = queryid
  deepDone.value = false
  deepFindings.value = []
  try {
    const { data } = await axios.post(`${API_BASE}/queries/analyze/${queryid}`)
    selectedPlan.value = data.plan
    // only show an explanation when there is something meaningful to say
    selectedInsight.value = data.recommendations?.[0]?.reason || ''
    await fetchRecommendations()
    await fetchInsights()
  } catch (e) {
    console.error('Analysis failed:', e)
    selectedPlan.value = { error: e.response?.data?.detail || e.message }
  } finally {
    loading.value = false
  }
}

const applyRecommendation = async (rec) => {
  if (!rec.id) {
    notify('This recommendation has no id yet — click Refresh and try again.', 'warning')
    return
  }
  // Honest + safe: we mark it applied and hand you the statement to run yourself.
  // We do NOT auto-run CREATE INDEX, because building an index can lock the table.
  const ok = await confirmDialog({
    title: 'Apply index recommendation',
    message: 'This marks the recommendation as applied and gives you the exact statement — '
      + 'it does NOT create the index automatically (index builds can lock the table).\n'
      + 'Run it yourself during a maintenance window (consider CREATE INDEX CONCURRENTLY):',
    code: rec.index_def,
    confirmText: 'Mark applied',
  })
  if (!ok) return
  try {
    await axios.post(`${API_BASE}/recommendations/${rec.id}/apply`)
    await fetchRecommendations()
    await fetchStats()
    notify('Marked as applied — remember to run the CREATE INDEX statement yourself.', 'success')
  } catch (e) {
    console.error('Apply failed:', e)
    notify('Apply failed: ' + (e.response?.data?.detail || e.message), 'error')
  }
}

const refreshQueries = async () => {
  loading.value = true
  await Promise.all([
    fetchStats(),
    fetchSlowQueries(),
    fetchInsights(),
    fetchRecommendations(),
    fetchSchemaHealth()
  ])
  loading.value = false
}

onMounted(() => {
  refreshQueries()
  // Auto-refresh every 30 seconds
  setInterval(refreshQueries, 30000)
})
</script>