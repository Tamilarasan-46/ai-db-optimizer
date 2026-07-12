<template>
  <!-- ── Toast stack (top-right) ─────────────────────────────────────────── -->
  <div class="fixed top-4 right-4 z-[60] space-y-2 w-80 max-w-[calc(100vw-2rem)]">
    <transition-group name="toast">
      <div
        v-for="t in ui.toasts"
        :key="t.id"
        class="flex items-start gap-2.5 rounded-lg border shadow-lg px-3.5 py-3 text-[13px] leading-relaxed bg-white"
        :class="border(t.type)"
      >
        <span class="mt-1 w-2 h-2 rounded-full shrink-0" :class="dot(t.type)"></span>
        <p class="flex-1 min-w-0 text-slate-700 whitespace-pre-line break-words">{{ t.message }}</p>
        <button @click="dismiss(t.id)" class="text-slate-300 hover:text-slate-500 shrink-0 leading-none text-base">×</button>
      </div>
    </transition-group>
  </div>

  <!-- ── Confirm dialog ──────────────────────────────────────────────────── -->
  <div v-if="ui.confirm" class="fixed inset-0 z-[70] flex items-center justify-center p-4">
    <div class="absolute inset-0 bg-slate-900/50" @click="settleConfirm(false)"></div>
    <div class="relative bg-white rounded-xl shadow-2xl border border-slate-200 w-full max-w-lg overflow-hidden">
      <div class="px-5 pt-4 pb-3 border-b border-slate-100">
        <h3 class="text-sm font-semibold text-slate-800">{{ ui.confirm.title }}</h3>
      </div>
      <div class="px-5 py-4 space-y-3">
        <p class="text-[13px] text-slate-600 leading-relaxed whitespace-pre-line">{{ ui.confirm.message }}</p>
        <div v-if="ui.confirm.code" class="relative">
          <pre class="text-[11px] bg-slate-900 text-emerald-300 rounded-lg p-3 pr-14 overflow-x-auto scroll-slim whitespace-pre-wrap">{{ ui.confirm.code }}</pre>
          <button
            @click="copyCode"
            class="absolute top-2 right-2 text-[10px] bg-slate-700 hover:bg-slate-600 text-slate-200 px-2 py-0.5 rounded"
          >{{ copied ? '✓ copied' : 'copy' }}</button>
        </div>
      </div>
      <div class="px-5 py-3 bg-slate-50 flex justify-end gap-2">
        <button
          @click="settleConfirm(false)"
          class="text-xs font-medium text-slate-500 hover:text-slate-700 px-3.5 py-2 rounded-md hover:bg-slate-100 transition-colors"
        >Cancel</button>
        <button
          @click="settleConfirm(true)"
          class="text-xs font-semibold text-white px-4 py-2 rounded-md transition-colors"
          :class="ui.confirm.danger ? 'bg-red-600 hover:bg-red-700' : 'bg-emerald-600 hover:bg-emerald-700'"
        >{{ ui.confirm.confirmText }}</button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { ui, dismiss, settleConfirm } from '../ui.js'

const copied = ref(false)
const copyCode = () => {
  navigator.clipboard?.writeText(ui.confirm?.code || '')
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

const dot = (t) => ({
  success: 'bg-emerald-500', error: 'bg-red-500', warning: 'bg-amber-500', info: 'bg-blue-400',
}[t] || 'bg-slate-400')

const border = (t) => ({
  success: 'border-emerald-200', error: 'border-red-200', warning: 'border-amber-200', info: 'border-slate-200',
}[t] || 'border-slate-200')
</script>
<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(12px); }
.toast-leave-to { opacity: 0; transform: translateX(12px); }
</style>