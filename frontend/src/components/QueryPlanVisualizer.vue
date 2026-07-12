<template>
  <div>
    <!-- Error / non-EXPLAIN-able statement -->
    <div v-if="plan?.error" class="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
      <div class="font-semibold mb-1">Plan unavailable</div>
      <p>{{ plan.error }}</p>
      <code v-if="plan.query" class="block mt-2 text-xs bg-white/60 rounded p-2 font-mono text-amber-900 whitespace-pre-wrap">{{ plan.query }}</code>
    </div>

    <!-- Real recursive plan tree -->
    <div v-else-if="nodes.length" class="font-mono text-xs">
      <div
        v-for="(n, i) in nodes"
        :key="i"
        class="flex items-center gap-2 py-1.5 border-b border-slate-50 last:border-0"
        :style="{ paddingLeft: (n.depth * 20) + 'px' }"
      >
        <span class="text-slate-300 select-none">{{ n.depth ? '└─' : '' }}</span>
        <span class="px-2 py-0.5 rounded font-semibold text-white text-[11px]" :style="{ backgroundColor: nodeColor(n.type) }">
          {{ n.type }}
        </span>
        <span v-if="n.relation" class="text-slate-500">on <span class="text-slate-700">{{ n.relation }}</span></span>
        <span v-if="n.index" class="text-emerald-600">using {{ n.index }}</span>
        <span class="text-slate-400">cost={{ fmt(n.cost) }}</span>
        <span class="text-slate-400">rows={{ fmt(n.rows) }}</span>
        <template v-if="n.actualRows != null">
          <span :class="n.estOff ? 'text-red-500 font-semibold' : 'text-slate-500'">actual={{ fmt(n.actualRows) }}</span>
          <span v-if="n.actualTime != null" class="text-blue-500">{{ n.actualTime.toFixed(1) }}ms</span>
        </template>
        <span v-if="n.isSeqScan" class="ml-1 text-red-500">⚠ seq scan</span>
        <span v-if="n.estOff" class="ml-1 text-red-500" title="Planner estimate is >=10x off — run ANALYZE on this table">⚠ estimate off</span>
      </div>

      <div v-if="seqScanTables.length" class="mt-3 flex flex-wrap gap-2">
        <span
          v-for="t in seqScanTables"
          :key="t"
          class="px-2 py-1 rounded-full text-[11px] bg-emerald-50 text-emerald-700 border border-emerald-200"
        >✓ consider an index on {{ t }}</span>
      </div>
    </div>

    <div v-else class="text-slate-400 text-sm text-center py-6">No plan to display.</div>
  </div>
</template>
<script setup>
import { computed } from 'vue'

const props = defineProps({ plan: Object })

const nodeColor = (type) => {
  const t = type || ''
  if (t.includes('Seq Scan')) return '#ef4444'
  if (t.includes('Index Only Scan')) return '#059669'
  if (t.includes('Index Scan')) return '#10b981'
  if (t.includes('Bitmap')) return '#14b8a6'
  if (t.includes('Hash')) return '#3b82f6'
  if (t.includes('Nested Loop')) return '#8b5cf6'
  if (t.includes('Merge')) return '#6366f1'
  if (t.includes('Aggregate') || t.includes('Group')) return '#0ea5e9'
  if (t.includes('Sort')) return '#f59e0b'
  return '#64748b'
}

const fmt = (v) => (v == null ? '?' : Number(v).toLocaleString())

// Flatten the EXPLAIN plan tree (real keys have spaces: "Node Type", "Total Cost", ...)
const flatten = (node, depth, out) => {
  if (!node || typeof node !== 'object') return
  const type = node['Node Type'] || 'Node'
  const est = node['Plan Rows']
  const act = node['Actual Rows'] != null ? node['Actual Rows'] * (node['Actual Loops'] || 1) : null
  out.push({
    depth,
    type,
    cost: node['Total Cost'],
    rows: est,
    actualRows: act,
    actualTime: node['Actual Total Time'] ?? null,
    estOff: act != null && est != null && Math.max(est, 1) * 10 <= Math.max(act, 1),
    relation: node['Relation Name'] || null,
    index: node['Index Name'] || null,
    isSeqScan: type === 'Seq Scan',
  })
  for (const child of node['Plans'] || []) flatten(child, depth + 1, out)
}

const nodes = computed(() => {
  const out = []
  if (props.plan && !props.plan.error) flatten(props.plan, 0, out)
  return out
})

const seqScanTables = computed(() =>
  [...new Set(nodes.value.filter(n => n.isSeqScan && n.relation).map(n => n.relation))]
)
</script>