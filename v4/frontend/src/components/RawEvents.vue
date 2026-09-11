<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { followNativeEvents } from '../stream.js'
import { localTime } from '../time.js'
defineProps({ state: Object })
const rows = ref([]), status = ref('connecting'), search = ref(''), direction = ref('all'), paused = ref(false)
let stop, latest = []
const visible = computed(() => rows.value.filter(row =>
  (direction.value === 'all' || row.direction === direction.value) &&
  `${row.transport} ${row.raw}`.toLowerCase().includes(search.value.toLowerCase())))
function pause() { paused.value = !paused.value; if (!paused.value) rows.value = latest }
function pretty(raw) { try { return JSON.stringify(JSON.parse(raw), null, 2) } catch { return raw } }
function label(raw) {
  try { const value = JSON.parse(raw); return [value.type || value.kind || 'Message', value.event?.kind, value.event?.source, value.code || value.result?.status].filter(Boolean).join(' · ') }
  catch { return 'Unparsed message' }
}
onMounted(() => { stop = followNativeEvents(value => { latest = value; if (!paused.value) rows.value = value }, value => { status.value = value }, 'raw/stream') })
onUnmounted(() => stop?.())
</script>

<template>
  <section class="raw-workspace" aria-label="Raw event monitor">
    <div class="raw-heading"><div><h2>Raw events</h2><p>Inspect what the sender delivers and how the receiver replies.</p></div>
      <strong role="status">{{ paused ? 'Display paused' : status === 'live' ? 'Live messages' : status }}</strong></div>
    <div class="raw-facts"><span>{{ state?.capture_websocket?.connected_senders ?? 0 }} WebSocket senders</span>
      <span>{{ rows.length }} buffered messages</span><span>Memory only · 500 messages / 2 MB maximum</span></div>
    <p>Oldest messages roll off automatically. Restarting the app clears this buffer. Trade journal records are separate and remain on disk.</p>
    <div class="raw-tools"><label>Search raw JSON<input v-model="search" placeholder="X17, event ID, symbol, rejection…" /></label>
      <label>Direction<select v-model="direction"><option value="all">All messages</option><option value="in">Incoming</option><option value="out">Receiver replies</option></select></label>
      <button @click="pause">{{ paused ? 'Resume display' : 'Pause display' }}</button></div>
    <p class="raw-note">Authenticated WebSocket application messages and native HTTP events. Hello, ready, events and ACK/NACK replies are visible. Authentication headers and network Ping/Pong frames are excluded; secrets are redacted. Individual messages over 32 KB are truncated. Pause freezes this view only.</p>
    <div v-if="!visible.length" class="raw-empty">{{ rows.length ? 'No matching messages. Try another filter.' : 'Waiting for sender messages. Existing journal history is not loaded into this live buffer.' }}</div>
    <details v-for="row in visible" :key="row.id" class="raw-message">
      <summary><span :class="['raw-direction', row.direction]">{{ row.direction === 'in' ? 'IN' : 'OUT' }}</span>
        <time>{{ localTime(row.received_at) }}</time><strong>{{ label(row.raw) }}</strong><small>{{ row.transport }} · #{{ row.id }}</small></summary>
      <p v-if="row.truncated">Message truncated to the diagnostic size limit.</p>
      <pre tabindex="0">{{ pretty(row.raw) }}</pre>
    </details>
  </section>
</template>

<style scoped>
.raw-workspace{background:#fff;border:1px solid #dbe3ed;border-radius:18px;padding:24px;min-width:0}
.raw-heading{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.raw-heading h2{margin:0}.raw-heading>strong{color:#087c68}
.raw-workspace p{color:#536278;line-height:1.6}.raw-facts{display:flex;gap:12px;flex-wrap:wrap}.raw-facts span{background:#eef4f8;padding:8px 12px;border-radius:8px;font-size:13px}
.raw-tools{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:20px 0}.raw-tools label{display:grid;gap:6px;flex:1;min-width:180px}.raw-tools input,.raw-tools select{padding:10px;border:1px solid #c8d4df;border-radius:8px;width:100%;box-sizing:border-box}.raw-tools button{padding:11px 16px;border:1px solid #c8d4df;border-radius:8px;background:#edf6f4;cursor:pointer}
.raw-note{font-size:12px}.raw-empty{padding:40px;text-align:center;background:#f5f8fb;border-radius:12px}.raw-message{border-top:1px solid #e2e8f0;padding:12px 0}.raw-message summary{cursor:pointer;display:flex;align-items:center;gap:12px;flex-wrap:wrap}.raw-message small{margin-left:auto;color:#5e6f80}.raw-message time{font-size:12px}.raw-direction{font-size:11px;padding:5px 8px;border-radius:6px;background:#e8effd;color:#2757a7}.raw-direction.out{background:#e0f4ed;color:#087c68}.raw-message pre{background:#101e30;color:#d4e6f7;padding:16px;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:500px;overflow:auto;font-size:12px}
@media(max-width:600px){.raw-workspace{padding:14px}.raw-message small{margin-left:0}.raw-message strong{overflow-wrap:anywhere;min-width:0}}
</style>
