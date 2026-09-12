<script setup>
import { computed, ref, watch } from 'vue'
import { request } from '../api.js'
// Sending is always an explicit click. Nothing here runs on mount, on a timer or
// when the stream replaces the row; only the lot size is editable.
const props = defineProps({ row: { type: Object, required: true }, mode: { type: String, default: 'paper' } })
const volume = ref(String(props.row.lots ?? ''))
const busy = ref(false), error = ref(''), sent = ref('')
watch(() => props.row.trade_id, () => { volume.value = String(props.row.lots ?? ''); error.value = ''; sent.value = '' })
const live = computed(() => props.mode === 'live')
const blocked = computed(() => {
  if (props.row.state !== 'candidate') return 'Only a candidate can be sent.'
  if (!props.row.source_enabled) return `Source ${props.row.source?.code || '(unknown)'} is off in copy controls.`
  return ''
})
async function send() {
  if (busy.value || blocked.value) return
  // v-model on a number input yields a number once parseable; the API receives it as text.
  const value = String(volume.value ?? '').trim()
  if (!(Number(value) > 0)) { error.value = 'Enter a lot size greater than zero.'; return }
  busy.value = true; error.value = ''; sent.value = ''
  try {
    const result = await request('trades/send', { trade_id: props.row.trade_id, volume: value })
    const detail = result?.message || result?.state || ''
    sent.value = (live.value ? 'Live order submitted · awaiting broker read-back' : 'Paper send recorded · no broker order was placed') + (detail ? ` · ${detail}` : '')
  } catch (err) {
    error.value = err?.message || `Send of ${props.row.trade_id} failed and the local API returned no message.`
  } finally { busy.value = false }
}
</script>

<template>
  <div class="trade-send" :class="{ live }">
    <label>Lots<input v-model="volume" type="number" step="any" min="0" :disabled="busy || !!blocked"
      :aria-label="`Lots to send for ${row.trade_id}`" /></label>
    <button type="button" :class="live ? 'primary send-live' : 'secondary send-paper'" :disabled="busy || !!blocked" :title="blocked || undefined" @click="send">
      {{ busy ? 'Sending…' : live ? 'Send LIVE order' : 'Send as paper · no broker order' }}
    </button>
    <span v-if="blocked" class="subtext">{{ blocked }}</span>
    <span v-else-if="!live" class="subtext">Paper mode: this records a request and sends nothing to a broker.</span>
    <span v-if="sent" class="subtext" role="status">{{ sent }}</span>
    <span v-if="error" class="send-error" role="alert">{{ error }}</span>
  </div>
</template>

<style scoped>
.trade-send{display:flex;flex-direction:column;gap:6px;min-width:200px;white-space:normal}
.trade-send label{display:flex;align-items:center;gap:8px;font-size:11px;color:#6d7d92}
.trade-send input{width:96px;min-height:34px;padding:6px 8px}
.trade-send button{min-height:34px;padding:6px 12px;font-size:12px}
.trade-send .send-live{background:#9b2226;border-color:#9b2226}
.trade-send .send-live:hover:enabled{background:#7a1a1d}
.send-error{display:block;font-size:11px;color:#a34f37;background:#fff3ef;border:1px solid #edc2b9;border-radius:6px;padding:6px 8px}
</style>
