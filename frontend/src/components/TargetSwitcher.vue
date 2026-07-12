<template>
  <div class="relative flex items-center gap-2 text-sm">
    <span class="text-slate-400 text-xs hidden md:inline">Analysing:</span>

    <select
      v-model="selected"
      class="bg-slate-800 text-emerald-300 border border-slate-700 rounded-md px-2 py-1 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500 max-w-[13rem]"
    >
      <option v-if="mode.includes('demo')" value="__demo__">demo database</option>
      <option v-for="db in databases" :key="db" :value="db">{{ db }}</option>
      <option value="__new__">＋ Connect database…</option>
    </select>

    <button
      v-if="selected && selected !== current && selected !== '__new__' && selected !== '__demo__'"
      @click="switchDb"
      :disabled="busy"
      class="text-xs bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1 rounded-md transition-colors"
    >{{ busy ? '…' : 'Switch' }}</button>
    <span v-else-if="selected !== '__new__'" class="w-2 h-2 rounded-full" :class="current ? 'bg-emerald-400' : 'bg-slate-500'" :title="mode"></span>

    <!-- Connect form (appears when '+ Connect database…' chosen) -->
    <div v-if="selected === '__new__'"
      class="absolute right-0 top-9 z-30 w-72 bg-white text-slate-700 rounded-xl border border-slate-200 shadow-lg p-4 space-y-2.5">
      <div class="text-xs font-semibold text-slate-700">Connect your PostgreSQL <span class="font-normal text-slate-400">(read-only)</span></div>
      <div class="grid grid-cols-3 gap-2">
        <input v-model="form.host" placeholder="host" class="col-span-2 inp" spellcheck="false" />
        <input v-model.number="form.port" placeholder="5432" type="number" class="inp" />
      </div>
      <input v-model="form.database" placeholder="database name" class="inp w-full" spellcheck="false" />
      <input v-model="form.username" placeholder="read-only username" class="inp w-full" spellcheck="false" />
      <input v-model="form.password" placeholder="password" type="password" class="inp w-full" />
      <p class="text-[10px] text-slate-400 leading-relaxed">
        Tip: from Docker, your host machine is <code class="bg-slate-100 px-1 rounded">host.docker.internal</code>.
        Credentials are used for this session only — set TARGET_DATABASE_URL in .env to make it permanent.
      </p>
      <div class="flex items-center justify-between gap-2">
        <button @click="selected = current || '__demo__'" class="text-xs text-slate-400 hover:text-slate-600">Cancel</button>
        <button @click="connectNew" :disabled="busy || !form.host || !form.database || !form.username"
          class="text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white px-3 py-1.5 rounded-md transition-colors">
          {{ busy ? 'Connecting…' : 'Connect' }}
        </button>
      </div>
      <p v-if="err" class="text-[10px] text-red-500 leading-relaxed">{{ err }}</p>
    </div>
  </div>
</template>
<script setup>
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'
import { notify } from '../ui.js'

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const databases = ref([])
const current = ref('')
const selected = ref('')
const mode = ref('')
const busy = ref(false)
const err = ref('')
const form = reactive({ host: 'host.docker.internal', port: 5432, database: '', username: '', password: '' })

const load = async () => {
  try {
    const [{ data: info }, { data: dbs }] = await Promise.all([
      axios.get(`${API_BASE}/target/info`),
      axios.get(`${API_BASE}/target/databases`),
    ])
    mode.value = info.mode
    current.value = info.mode.includes('demo') ? '__demo__' : info.database
    selected.value = current.value
    databases.value = info.mode.includes('demo') ? [] : dbs.databases
  } catch (e) { console.error('target info failed:', e) }
}

const switchDb = async () => {
  busy.value = true
  try {
    await axios.post(`${API_BASE}/target/connect`, { database: selected.value })
    window.location.reload()
  } catch (e) {
    notify('Switch failed: ' + (e.response?.data?.detail || e.message), 'error')
    selected.value = current.value
    busy.value = false
  }
}

const connectNew = async () => {
  busy.value = true; err.value = ''
  try {
    const { data } = await axios.post(`${API_BASE}/target/connect`, { ...form })
    if (!data.pg_stat_statements) {
      // connected but slow-query features will be empty — let the user read it,
      // then reload into the new target
      notify(data.note, 'warning', 6000)
      setTimeout(() => window.location.reload(), 3500)
    } else {
      window.location.reload()
    }
  } catch (e) {
    err.value = e.response?.data?.detail || e.message
    busy.value = false
  }
}

onMounted(load)
</script>
<style scoped>
.inp {
  @apply text-xs border border-slate-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-400 font-mono;
}
</style>