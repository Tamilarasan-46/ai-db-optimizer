<template>
  <div class="card">
    <div class="card-header">
      <h2 class="card-title">
        <svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
        Rewrite Parity Check
        <span class="card-count normal-case tracking-normal">prove a rewrite is identical before shipping</span>
      </h2>
    </div>
    <div class="p-4 grid grid-cols-2 gap-4">
      <div>
        <label class="text-xs font-semibold text-slate-500">A — original (SELECT / function call)</label>
        <textarea v-model="qa" rows="4" spellcheck="false" placeholder="SELECT * FROM my_schema.slow_report_function('2025-04-01','2026-03-31')"
          class="mt-1 w-full text-xs font-mono border border-slate-200 rounded-lg p-2.5 focus:outline-none focus:ring-2 focus:ring-blue-400"></textarea>
      </div>
      <div>
        <label class="text-xs font-semibold text-slate-500">B — optimized rewrite</label>
        <textarea v-model="qb" rows="4" spellcheck="false" placeholder="WITH ... SELECT ...  (your faster version)"
          class="mt-1 w-full text-xs font-mono border border-slate-200 rounded-lg p-2.5 focus:outline-none focus:ring-2 focus:ring-blue-400"></textarea>
      </div>
      <div class="col-span-2 flex items-center gap-3">
        <button @click="run" :disabled="running || !qa.trim() || !qb.trim()"
          class="text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          :class="running ? 'bg-slate-100 text-slate-400' : 'bg-blue-600 hover:bg-blue-700 text-white'">
          {{ running ? 'Comparing…' : 'Compare Results' }}
        </button>
        <span class="text-xs text-slate-400">Both run read-only with a 120s timeout. Floats rounded to 2dp.</span>
      </div>

      <div v-if="result" class="col-span-2 rounded-lg p-4 text-sm"
        :class="result.identical ? 'bg-emerald-50 border border-emerald-200' : 'bg-red-50 border border-red-200'">
        <div class="font-semibold" :class="result.identical ? 'text-emerald-700' : 'text-red-700'">
          {{ result.verdict }}
        </div>
        <div class="mt-2 grid grid-cols-4 gap-3 text-xs text-slate-600">
          <div>rows A: <b>{{ result.rows_a.toLocaleString() }}</b></div>
          <div>rows B: <b>{{ result.rows_b.toLocaleString() }}</b></div>
          <div>time A: <b>{{ result.time_ms_a }}ms</b></div>
          <div>time B: <b>{{ result.time_ms_b }}ms</b>
            <span v-if="result.speedup > 1" class="ml-1 text-emerald-600 font-semibold">({{ result.speedup }}x faster)</span>
          </div>
        </div>
        <div v-if="!result.identical" class="mt-2 text-xs text-red-600">
          {{ result.rows_only_in_a }} rows only in A · {{ result.rows_only_in_b }} rows only in B —
          first differing rows: <code class="bg-white/60 px-1 rounded">{{ JSON.stringify(result.sample_diff_a[0] || result.sample_diff_b[0]) }}</code>
        </div>
      </div>
      <div v-if="error" class="col-span-2 rounded-lg p-3 text-xs bg-amber-50 border border-amber-200 text-amber-800">{{ error }}</div>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const qa = ref(''), qb = ref(''), running = ref(false), result = ref(null), error = ref('')

const run = async () => {
  running.value = true; result.value = null; error.value = ''
  try {
    const { data } = await axios.post(`${API_BASE}/parity/check`,
      { query_a: qa.value, query_b: qb.value }, { timeout: 300000 })
    result.value = data
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    running.value = false
  }
}
</script>