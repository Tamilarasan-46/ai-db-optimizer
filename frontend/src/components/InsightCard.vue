<template>
  <div class="border rounded-lg p-3" :class="bgClass">
    <div class="flex items-center gap-2 mb-1.5">
      <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="dotClass"></span>
      <span class="text-[10px] font-semibold uppercase tracking-wide" :class="textClass">{{ insight.severity }}</span>
      <span v-if="insight.category" class="text-[10px] text-slate-400">· {{ insight.category }}</span>
    </div>
    <div v-if="insight.title" class="text-xs font-semibold text-slate-700 mb-1">{{ insight.title }}</div>
    <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-line max-h-40 overflow-y-auto scroll-slim">{{ insight.description }}</p>
    <div v-if="insight.suggested_action" class="mt-2">
      <code
        class="block text-[10px] bg-white/70 border rounded-md px-2 py-1.5 truncate cursor-pointer"
        :class="btnClass"
        :title="insight.suggested_action"
        @click="copyAction"
      >{{ copied ? '✓ copied to clipboard' : insight.suggested_action }}</code>
    </div>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ insight: Object })
const copied = ref(false)
const copyAction = () => {
  navigator.clipboard?.writeText(props.insight.suggested_action)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
const config = computed(() => ({
  Critical: { bg: 'bg-red-50/60 border-red-100', dot: 'bg-red-500', text: 'text-red-700', btn: 'border-red-200 text-red-700' },
  Warning: { bg: 'bg-amber-50/60 border-amber-100', dot: 'bg-amber-500', text: 'text-amber-700', btn: 'border-amber-200 text-amber-700' },
  Info: { bg: 'bg-blue-50/60 border-blue-100', dot: 'bg-blue-500', text: 'text-blue-700', btn: 'border-blue-200 text-blue-700' },
  Optimization: { bg: 'bg-emerald-50/60 border-emerald-100', dot: 'bg-emerald-500', text: 'text-emerald-700', btn: 'border-emerald-200 text-emerald-700' }
}[props.insight.severity] || { bg: 'bg-slate-50 border-slate-100', dot: 'bg-slate-400', text: 'text-slate-600', btn: 'border-slate-200 text-slate-600' }))
const bgClass = computed(() => config.value.bg)
const dotClass = computed(() => config.value.dot)
const textClass = computed(() => config.value.text)
const btnClass = computed(() => config.value.btn)
</script>