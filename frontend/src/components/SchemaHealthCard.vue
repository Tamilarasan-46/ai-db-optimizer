<template>
  <div class="card h-full">
    <div class="card-header !h-10">
      <h3 class="card-title !text-xs">
        <svg class="w-3.5 h-3.5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        Schema Health
      </h3>
    </div>
    <div class="card-body px-4 py-2 grid grid-cols-2 gap-x-4 content-center">
      <div v-for="m in metrics" :key="m.label" class="flex items-baseline justify-between py-1">
        <span class="text-[11px] text-slate-500">{{ m.label }}</span>
        <span class="text-sm font-semibold metric" :class="m.cls">{{ m.value }}</span>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ health: Object })
const metrics = computed(() => {
  const h = props.health || {}
  return [
    { label: 'No primary key', value: h.tables_without_pk || 0, cls: (h.tables_without_pk || 0) > 0 ? 'text-red-500' : 'text-emerald-600' },
    { label: 'Missing FK idx', value: h.missing_fk_indexes || 0, cls: (h.missing_fk_indexes || 0) > 0 ? 'text-red-500' : 'text-emerald-600' },
    { label: 'Unused indexes', value: (h.unused_indexes || 0).toLocaleString(), cls: (h.unused_indexes || 0) > 0 ? 'text-amber-500' : 'text-emerald-600' },
    { label: 'Dead tuples', value: (h.bloat_ratio || 0).toFixed(1) + '%', cls: (h.bloat_ratio || 0) > 20 ? 'text-red-500' : 'text-emerald-600' },
  ]
})
</script>