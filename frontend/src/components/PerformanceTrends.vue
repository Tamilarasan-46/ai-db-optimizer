<template>
  <div class="card h-full">
    <div class="card-header !h-10">
      <h3 class="card-title !text-xs">
        <svg class="w-3.5 h-3.5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>
        Latency Trend
      </h3>
      <span v-if="bars.length" class="text-[10px] text-slate-400 metric">{{ bars[bars.length-1].value }}ms now</span>
    </div>
    <div class="card-body px-4 py-3 flex flex-col">
      <div v-if="bars.length" class="flex-1 min-h-0 flex items-end gap-0.5">
        <div
          v-for="(b, i) in bars"
          :key="i"
          class="flex-1 rounded-t transition-all"
          :class="b.color"
          :style="{ height: b.height + '%' }"
          :title="`${b.label}: ${b.value}ms`"
        ></div>
      </div>
      <div v-if="bars.length" class="flex justify-between text-[10px] text-slate-400 mt-1.5 shrink-0 metric">
        <span>{{ bars[0].label }}</span>
        <span>{{ bars[bars.length - 1].label }}</span>
      </div>
      <div v-if="!bars.length" class="flex-1 flex flex-col items-center justify-center text-center text-slate-400 text-[11px] gap-0.5">
        <span>No samples yet</span>
        <span class="text-slate-300">accrues every ~30s refresh</span>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const bars = ref([])

const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

const load = async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/stats/trends`)
    if (!data.length) { bars.value = []; return }
    const max = Math.max(...data.map(d => d.avg_latency_ms), 1)
    bars.value = data.map(d => {
      const pct = Math.max(6, Math.round((d.avg_latency_ms / max) * 100))
      // absolute latency scale (not relative): red only when actually slow
      const color = d.avg_latency_ms > 500 ? 'bg-red-300'
        : d.avg_latency_ms > 100 ? 'bg-amber-200' : 'bg-blue-200'
      return { height: pct, value: d.avg_latency_ms, label: fmtTime(d.timestamp), color }
    })
  } catch (e) {
    console.error('Failed to fetch performance trends:', e)
  }
}

onMounted(() => {
  load()
  setInterval(load, 30000)
})
</script>