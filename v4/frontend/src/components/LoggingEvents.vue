<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api.js'
import { followNativeEvents } from '../stream.js'
import { localTime } from '../time.js'
const data = ref({ records: [] }), error = ref(''), status = ref('connecting'), search = ref(''), history = ref(false)
let stop, disposed = false, loading = false, dirty = false, last = 0
async function load(before = 0) {
  if (loading) { dirty = true; return }
  loading = true
  try { const value = await request(`logging/events?before=${before}`); if (!disposed) { data.value = value; error.value = '' } }
  catch (e) { if (!disposed) error.value = e.message }
  finally { loading = false; if (dirty && !disposed && !history.value) { dirty = false; load() } }
}
function live() { history.value = false; load() }
function older() { history.value = true; load(data.value.next_before) }
onMounted(() => {
  load()
  stop = followNativeEvents(rows => {
    const newest = rows.find(row => ['logging', 'tradingbox'].includes(row.transport))?.id
    if (newest && newest !== last) { last = newest; if (!history.value) load() }
  }, value => { status.value = value; if (value === 'live' && !history.value) load() }, 'raw/stream')
})
onUnmounted(() => { disposed = true; stop?.() })
</script>
<template>
  <section class="card logging-page">
    <h2>Event logging</h2>
    <p>Quantower and indicator observations · {{ history ? 'Saved history' : status }} · Observation archive</p>
    <p><code>POST http://127.0.0.1:8765/logging/events</code></p>
    <p>{{ data.count ?? 0 }} retained · {{ data.evicted ?? 0 }} rolled off · Maximum 2,000 records / 8 MiB of original bodies</p>
    <p>Logging only endpoint: /logging/events. TradingBox request/response records from /api/hcamm/ are also shown here; forwarding is controlled in Copy settings.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <label>Search this page <input v-model="search" placeholder="X17, symbol, event details" /></label>
    <button @click="live">Latest / resume</button> <button :disabled="!data.records.length" @click="older">Older records</button>
    <p v-if="!data.records.length">No records in this page. Send an authenticated observation to the logging endpoint.</p>
    <details v-for="row in data.records.filter(r => JSON.stringify(r).toLowerCase().includes(search.toLowerCase()))" :key="row.seq">
      <summary>{{ localTime(row.received_at) }} · {{ row.source || 'Source not supplied' }} · {{ row.kind || 'Unclassified event' }} · {{ row.body_bytes }} bytes</summary>
      <p>Receipt: {{ row.receipt_id }} · {{ row.content_type }}</p>
      <p v-if="row.metadata?.cycle_id">{{ row.metadata.method }} {{ row.metadata.path }} · TradingBox cycle {{ row.metadata.cycle_id }} · {{ row.metadata.direction === 'in' ? 'Indicator request' : 'Receiver / upstream response' }} · {{ row.metadata.upstream_status ?? row.metadata.status ?? 'Recorded' }}</p>
      <pre>{{ row.preview }}</pre><p v-if="row.preview_truncated">Preview truncated. Original bytes are stored locally.</p>
    </details>
  </section>
</template>
<style scoped>
.logging-page{padding:24px;min-width:0}.logging-page p{color:#52647a;overflow-wrap:anywhere}.logging-page input{padding:8px;margin:12px;max-width:100%}.logging-page button{padding:8px;margin:4px}.logging-page details{padding:14px 0;border-bottom:1px solid #dbe4ef}.logging-page summary{cursor:pointer;overflow-wrap:anywhere}.logging-page pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#101e30;color:#d4e6f7;padding:16px;max-height:450px;overflow:auto}
</style>
