<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { request } from '../api.js'
// Forwarding status is part of the pushed dashboard status; when the shell supplies it
// nothing here fetches. A standalone mount reads it once and never on a timer.
const props = defineProps({ pushed: Object })
const current = ref({ enabled: false, live: false, url: '', key_configured: false, generation: -1 })
const url = ref(''), busy = ref(false), error = ref('')
let disposed = false
function apply(value) {
  if (disposed || (value.generation ?? 0) < current.value.generation) return
  current.value = value
  if (!url.value) url.value = value.url || ''
}
async function load() {
  try { apply(await request('tradingbox-forwarding')) }
  catch (e) { if (!disposed) error.value = e.message }
}
async function save(value) {
  busy.value = true; error.value = ''
  try { apply(await request('tradingbox-forwarding', value)) }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch(() => props.pushed, value => { if (value) apply(value) }, { immediate: true })
onMounted(() => { if (!props.pushed) load() })
onUnmounted(() => { disposed = true })
</script>
<template>
  <section class="forwarding-settings" aria-label="TradingBox forwarding">
    <h3>TradingBox signal forwarding</h3>
    <strong role="status">{{ !current.enabled ? 'Off · logging only' : current.live ? 'LIVE · sending new signals to TradingBox' : 'Preview · no signals sent' }}</strong>
    <p>Point the indicator’s TB endpoint to <code>http://127.0.0.1:8765/api/hcamm/events</code>. Keep its TradingBox key. Signal requests, command polling and replies under /api/hcamm/ pass through when both controls are on. Keep every X17 TradingBox URL on this local host so replies and acknowledgements use the same connection path.</p>
    <label>TradingBox destination URL<input v-model="url" :disabled="busy || current.enabled || current.in_flight > 0" placeholder="https://tradingbox.pro/api/hcamm/events" /></label>
    <button type="button" :disabled="busy || current.enabled || current.in_flight > 0" @click="save({ url, enabled: false, live: false })">Save TradingBox destination</button>
    <p>{{ current.key_configured ? `Sender key configured (${current.auth_header})` : 'Set TB_FORWARD_API_KEY in .env to the indicator’s TradingBox key, then restart.' }}</p>
    <div class="forwarding-buttons">
      <button type="button" :disabled="busy || (!current.enabled && !current.url)" @click="save({ url: current.url, enabled: !current.enabled, live: false })">{{ current.enabled ? 'Turn forwarding off' : 'Turn forwarding on' }}</button>
      <button type="button" :disabled="busy || !current.enabled || !current.key_configured" @click="save({ url: current.url, enabled: true, live: !current.live })">{{ current.live ? 'Return to preview' : 'Go live with TradingBox' }}</button>
    </div>
    <p>Live delivery can trigger TradingBox’s configured trading actions. Aqua API copying is controlled separately. Forwarding and Live reset to off on restart. Old signals are not replayed; requests already in flight may finish.</p>
    <p>{{ current.sent ?? 0 }} upstream replies · {{ current.failed ?? 0 }} uncertain deliveries · {{ current.in_flight ?? 0 }} in flight</p>
    <p v-if="current.last_result">Last delivery: {{ current.last_result.upstream_status ?? current.last_result.status }}<span v-if="current.last_result.response_log_failed"> · Response could not be archived</span></p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.forwarding-settings{padding:20px;margin:20px 0;border:1px solid #cbdadf;border-radius:12px;background:#f3f8f8}.forwarding-settings label{display:grid;gap:8px;margin:12px 0}.forwarding-settings input{padding:10px;width:100%;box-sizing:border-box}.forwarding-settings p{overflow-wrap:anywhere;line-height:1.5}.forwarding-buttons{display:flex;gap:12px;flex-wrap:wrap}.forwarding-settings button{padding:10px;border:1px solid #afc8c3;border-radius:8px;cursor:pointer}.forwarding-settings [role=status]{color:#146456}
</style>
