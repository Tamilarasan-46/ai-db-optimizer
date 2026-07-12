<template>
  <div class="card h-[30rem]">
    <div class="card-header">
      <h2 class="card-title">
        <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.031 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
        Full Database Audit
        <span v-if="meta.database" class="card-count normal-case">{{ meta.database }} · PG {{ meta.version }}</span>
      </h2>
      <button
        @click="runAudit"
        :disabled="running"
        class="text-xs font-semibold px-3.5 py-1.5 rounded-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        :class="running ? 'bg-slate-100 text-slate-400 cursor-wait' : 'bg-emerald-600 hover:bg-emerald-700 text-white'"
      >
        {{ running ? 'Auditing…' : '▶ Run Full Audit' }}
      </button>
    </div>

    <!-- summary chips (fixed) -->
    <div v-if="findings.length || audited || running" class="px-4 py-2.5 flex flex-wrap items-center gap-2 border-b border-slate-100 shrink-0 text-[11px]">
      <template v-if="running">
        <span class="flex items-center gap-2 text-slate-400">
          <span class="w-3 h-3 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin"></span>
          scanning slow queries, every plpgsql function body, plans &amp; schema…
        </span>
      </template>
      <template v-else>
        <span class="px-2.5 py-0.5 rounded-full font-semibold metric bg-red-100 text-red-700">{{ counts.Critical || 0 }} Critical</span>
        <span class="px-2.5 py-0.5 rounded-full font-semibold metric bg-amber-100 text-amber-700">{{ counts.Warning || 0 }} Warning</span>
        <span class="px-2.5 py-0.5 rounded-full font-semibold metric bg-blue-100 text-blue-700">{{ counts.Info || 0 }} Info</span>
        <span v-if="meta.functions_scanned" class="px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-500 metric">
          {{ meta.functions_scanned }}/{{ meta.functions_total }} functions · {{ meta.slow_queries_scanned }} queries scanned
        </span>
      </template>
    </div>

    <!-- findings (scrollable) -->
    <div v-if="findings.length" class="card-body">
      <div v-for="(group, cat) in grouped" :key="cat">
        <div class="sticky top-0 z-10 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400 bg-slate-50/95 backdrop-blur border-y border-slate-100">
          {{ catLabel(cat) }} · {{ group.length }}
        </div>
        <div v-for="(f, i) in group" :key="cat + i" class="px-4 py-2.5 border-b border-slate-50 hover:bg-slate-50/60 transition-colors">
          <div class="flex items-start gap-2.5 cursor-pointer" @click="toggle(cat + i)">
            <span class="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0" :class="dotClass(f.severity)"></span>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] font-medium text-slate-800 flex items-baseline gap-2 flex-wrap">
                {{ f.title }}
                <code class="text-[11px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-500 truncate max-w-[16rem]" :title="f.object_name">{{ f.object_name }}</code>
              </div>
              <p class="text-xs text-slate-500 mt-0.5 leading-relaxed">{{ f.detail }}</p>
              <div v-if="f.suggestion && open[cat + i]" class="mt-2 relative">
                <pre class="text-[11px] bg-slate-900 text-emerald-300 rounded-lg p-3 pr-14 overflow-x-auto scroll-slim whitespace-pre-wrap leading-relaxed">{{ f.suggestion }}</pre>
                <button
                  @click.stop="copy(f.suggestion, cat + i)"
                  class="absolute top-2 right-2 text-[10px] bg-slate-700 hover:bg-slate-600 text-slate-200 px-2 py-0.5 rounded transition-colors"
                >{{ copied === cat + i ? '✓ copied' : 'copy' }}</button>
              </div>
              <button v-else-if="f.suggestion" @click.stop="toggle(cat + i)"
                class="mt-1 text-[11px] font-medium text-emerald-600 hover:text-emerald-700">show fix ▸</button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="audited && !running" class="card-body flex flex-col items-center justify-center text-center text-slate-400 gap-1">
      <span class="text-2xl">🎉</span>
      <span class="text-sm">Clean audit — no issues found</span>
    </div>
    <div v-else-if="!running" class="card-body flex flex-col items-center justify-center text-center gap-2 px-10">
      <svg class="w-8 h-8 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.031 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
      <span class="text-sm text-slate-500 font-medium">One click audits the whole database</span>
      <span class="text-xs text-slate-400 leading-relaxed">Slow queries, every plpgsql function body, query plans, schema and config —
        each finding comes with a copy-paste fix.</span>
    </div>
    <div v-else class="card-body flex items-center justify-center">
      <div class="w-full max-w-sm space-y-3 px-6">
        <div class="h-3 bg-slate-100 rounded animate-pulse"></div>
        <div class="h-3 bg-slate-100 rounded animate-pulse w-5/6"></div>
        <div class="h-3 bg-slate-100 rounded animate-pulse w-4/6"></div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import axios from 'axios'
import { notify } from '../ui.js'

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const running = ref(false)
const audited = ref(false)
const findings = ref([])
const counts = ref({})
const meta = ref({})
const open = reactive({})
const copied = ref('')

const grouped = computed(() => {
  const g = {}
  for (const f of findings.value) (g[f.category] = g[f.category] || []).push(f)
  return g
})

const catLabel = (c) => ({
  sargability: 'Sargability — predicates that defeat indexes',
  function: 'Function bodies (plpgsql)',
  plan: 'Query plans',
  schema: 'Schema health',
  config: 'Configuration',
}[c] || c)

const dotClass = (s) => ({
  Critical: 'bg-red-500', Warning: 'bg-amber-500', Info: 'bg-blue-400',
}[s] || 'bg-slate-300')

const toggle = (k) => { open[k] = !open[k] }
const copy = (t, k) => {
  navigator.clipboard?.writeText(t)
  copied.value = k
  setTimeout(() => { if (copied.value === k) copied.value = '' }, 1500)
}

const runAudit = async () => {
  running.value = true
  try {
    const { data } = await axios.post(`${API_BASE}/audit/full`, null, { timeout: 300000 })
    findings.value = data.findings
    counts.value = data.counts
    meta.value = data.meta
    audited.value = true
    notify(`Audit complete: ${data.counts.Critical || 0} critical, ${data.counts.Warning || 0} warnings. `
      + 'AI insights are being generated in the background.', 'success')
  } catch (e) {
    console.error('Audit failed:', e)
    notify('Audit failed: ' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/audit/findings`)
    if (data.findings?.length) {
      findings.value = data.findings
      audited.value = true
      counts.value = data.findings.reduce((a, f) => (a[f.severity] = (a[f.severity] || 0) + 1, a), {})
    }
  } catch { /* no prior audit */ }
})
</script>