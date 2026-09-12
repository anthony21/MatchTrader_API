<script setup>
import { onMounted, ref } from 'vue'
import { request } from '../api.js'
const events = ref([]), error = ref(''), busy = ref(false)
async function refresh() {
  busy.value = true; error.value = ''
  try { events.value = (await request('signal-copy-events')).events || [] }
  catch (err) { error.value = err.message }
  finally { busy.value = false }
}
onMounted(refresh)
</script>
<template>
  <section class="card signal-activity" aria-label="Recent signal activity">
    <h2>Recent signal activity</h2><button :disabled="busy" @click="refresh">Refresh signal activity</button>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="!events.length">No signal decisions recorded.</p>
    <article v-for="row in events" :key="`${row.machineId}:${row.clientEventId}`">
      <strong>{{ row.kind }} · {{ row.status }}</strong><p>{{ row.reason }}</p>
      <details><summary>Request and response</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details>
    </article>
  </section>
</template>
<style scoped>.signal-activity{margin-top:20px}.signal-activity article{padding:14px 0;border-top:1px solid #ddd}.signal-activity pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}</style>
