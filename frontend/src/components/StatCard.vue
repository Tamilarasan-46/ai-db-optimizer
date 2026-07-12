<template>
  <div class="card px-4 py-3.5">
    <div class="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
      <span class="w-1.5 h-1.5 rounded-full" :class="dotClass"></span>
      {{ title }}
    </div>
    <div class="text-2xl font-semibold metric leading-tight mt-1 text-slate-900">{{ value }}</div>
    <div class="text-[11px] text-slate-400 mt-0.5 truncate">{{ subtitle }}</div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({
  title: String, value: [String, Number], subtitle: String, color: { type: String, default: 'slate' }
})
const dotMap = { red: 'bg-red-400', amber: 'bg-amber-400', emerald: 'bg-emerald-400', blue: 'bg-blue-400', slate: 'bg-slate-300' }
const dotClass = computed(() => dotMap[props.color] || dotMap.slate)
</script>