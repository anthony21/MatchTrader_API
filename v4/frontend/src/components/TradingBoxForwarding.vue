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
    <label>TradingBox destination URL<input v-model="url" :disabled="busy || current.enabled || current.in_flight > 0" placeholder="https://tradingbox.pro/api/hcamm/events" /></label>
    <button type="button" :disabled="busy || current.enabled || current.in_flight > 0" @click="save({ url, enabled: false, live: false })">Save</button>
    <button type="button" role="switch" aria-label="Forwarding" :aria-checked="current.enabled && current.live" :disabled="busy || (!(current.enabled && current.live) && (!current.url || !current.key_configured))" @click="save({ url: current.url, enabled: !(current.enabled && current.live), live: !(current.enabled && current.live) })">Forwarding {{ current.enabled && current.live ? 'On' : 'Off' }}</button>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.forwarding-settings{padding:20px;margin:20px 0;border:1px solid #cbdadf;border-radius:12px;background:#f3f8f8}.forwarding-settings label{display:grid;gap:8px;margin:12px 0}.forwarding-settings input{padding:10px;width:100%;box-sizing:border-box}.forwarding-settings p{overflow-wrap:anywhere;line-height:1.5}.forwarding-buttons{display:flex;gap:12px;flex-wrap:wrap}.forwarding-settings button{padding:10px;border:1px solid #afc8c3;border-radius:8px;cursor:pointer}.forwarding-settings [role=status]{color:#146456}
</style>
