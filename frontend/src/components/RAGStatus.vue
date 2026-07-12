<template>
  <div class="card h-full">
    <div class="card-header !h-10">
      <h3 class="card-title !text-xs">
        <svg class="w-3.5 h-3.5 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/></svg>
        RAG Knowledge Base
      </h3>
    </div>
    <div class="card-body px-4 py-2 flex flex-col justify-center gap-1.5 text-[11px] text-slate-500">
      <div class="flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="status.knowledge_entries > 0 ? 'bg-emerald-400' : 'bg-slate-300'"></span>
        <span class="metric">{{ status.knowledge_entries.toLocaleString() }} tuning patterns · {{ status.categories }} categories</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0"></span>
        <span>{{ status.vector_store }} · {{ status.vector_dim }}-dim vectors</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0"></span>
        <span class="truncate">{{ status.embedding_model }}</span>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const status = ref({
  knowledge_entries: 0,
  categories: 0,
  embedding_model: 'all-MiniLM-L6-v2',
  vector_dim: 384,
  vector_store: 'pgvector',
})

onMounted(async () => {
  try {
    const { data } = await axios.get(`${API_BASE}/rag/status`)
    status.value = data
  } catch (e) {
    console.error('Failed to fetch RAG status:', e)
  }
})
</script>