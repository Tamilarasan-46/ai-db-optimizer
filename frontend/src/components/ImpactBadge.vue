<template>
  <span class="px-2 py-0.5 rounded text-xs font-medium" :class="badgeClass">{{ impact }}</span>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ impact: String })
const badgeClass = computed(() => ({ 'High': 'bg-red-100 text-red-700', 'Medium': 'bg-amber-100 text-amber-700', 'Low': 'bg-blue-100 text-blue-700' }[props.impact] || 'bg-slate-100 text-slate-700'))
</script>