<script setup>
import { computed, onMounted, ref } from 'vue'
import { request } from '../api.js'
const props = defineProps({ state: Object })
const emit = defineEmits(['saved'])
const config = ref({ machine_id: '', source: 'chain', connection_name: '', destination_account: '', exclusive_destination: true })
const rows = ref([{ source: '', destination: '', fixed_lots: '', order_type: 'SOURCE', same_price_scale: true }])
const live = computed(() => !!props.state?.signal_copying)
function selectP01() {
  if (config.value.p01_log_enabled) {
    config.value.source = 'P01_LOG'
    config.value.additional_sources = []
    config.value.machine_id = props.state?.p01_log?.machine || ''
    config.value.connection_name = ''
    rows.value.forEach(row => { row.order_type = 'SOURCE' })
  }
}
function selectX17P01() {
  config.value.source = 'chain'
  config.value.additional_sources = ['panel']
  config.value.p01_log_enabled = false
  config.value.x17_only = true
  config.value.machine_id = props.state?.p01_log?.machine || config.value.machine_id
  rows.value.forEach(row => { row.order_type = 'ENTRY' })
}
const busy = ref(false), error = ref(''), message = ref('')
onMounted(async () => {
  try {
    const saved = await request('signal-copy-settings')
    if (saved.config) {
      const { symbols, ...other } = saved.config
      config.value = other
      rows.value = Object.entries(symbols).map(([source, value]) => ({ source, ...value }))
    } else config.value.destination_account = props.state?.account_id || ''
  } catch (err) { error.value = err.message }
})
async function save() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    if (new Set(rows.value.map(row => row.source.trim())).size !== rows.value.length) throw Error('Source symbols must be unique.')
    const symbols = Object.fromEntries(rows.value.map(({ source, ...value }) => [source.trim(), { ...value, same_price_scale: true, destination: value.destination.trim() }]))
    await request('signal-copy-settings', { ...config.value, exclusive_destination: true, machine_id: config.value.machine_id.trim(), source: config.value.source.trim(), connection_name: config.value.connection_name.trim(), symbols })
    message.value = 'Copy settings saved. Use the account Live control when ready.'
    emit('saved')
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <section class="card signal-settings" aria-label="Signal copy settings">
    <h2>Copy settings</h2>
    <p>Choose the source, destination, symbol mapping and lots per trade. Copies use the destination account's existing login.</p>
    <p v-if="live">Turn Live off in the account controls before changing settings.</p>
    <form @submit.prevent="save">
      <fieldset :disabled="busy || live || state?.copying">
        <legend>Signal source and destination</legend>
        <button type="button" @click="selectX17P01">Use X17 + manual P01 at logged entry</button>
        <label class="check"><input type="checkbox" :checked="config.additional_sources?.includes('panel')" @change="config.additional_sources = $event.target.checked ? ['panel'] : []" />Also accept structured P01 panel signals</label>
        <label class="check"><input v-model="config.x17_only" type="checkbox" />Require X17 attribution for chain intents</label>
        <p>Intervals remain separate when tracking orders. A blank chart filter accepts all intervals; P01 panel signals use their own labels.</p>
        <p class="unwind-rule">A cancel or closed signal always acts on a trade you already sent: the resting order is cancelled or the open position closed at once, whatever these switches or the copy controls say. Cancellation never closes a filled position. Nothing is ever opened automatically.</p>
        <label class="check"><input v-model="config.p01_log_enabled" type="checkbox" @change="selectP01" />Copy P01 chart intents from the local log</label>
        <p v-if="config.p01_log_enabled">Start capture to read P01 chart intents. Copies keep the source Limit or Stop type and use your lot size.</p>
        <div class="settings-grid">
          <label>Signal machine ID<input v-model="config.machine_id" required placeholder="machineId from the request" /></label>
          <label>Signal source<input v-model="config.source" required /></label>
          <label>Chart connection name (optional)<input v-model="config.connection_name" placeholder="For example, Time - 15s" /></label>
          <label>MatchTrader destination<select v-model="config.destination_account" required><option value="">Select an account</option><option v-for="account in state?.accounts || []" :key="account.id" :value="account.id">{{ account.id }}</option></select></label>
        </div>
      </fieldset>
      <fieldset :disabled="busy || live || state?.copying">
        <legend>Symbols and lot size</legend>
        <div v-for="(row, index) in rows" :key="index" class="mapping-row">
          <label>Signal symbol<input v-model="row.source" required placeholder="US TECH 100" /></label>
          <label>Destination symbol<input v-model="row.destination" required /></label>
          <label>Copy volume (lots)<input v-model="row.fixed_lots" type="number" min="0.00000001" step="any" required /></label>
          <details><summary>Order handling</summary><label>Copy order type<select v-model="row.order_type" required><option value="">Choose explicitly</option><option value="ENTRY">Pending at logged entry (source type or broker quote)</option><option value="SOURCE">Use source order type</option><option value="MARKET">Market - current price</option><option value="LIMIT">Limit - signal entry</option><option value="STOP">Stop - signal entry</option></select></label><p>Keep the source order type, or preserve an existing explicit override. Pending at logged entry uses a fresh broker quote to choose Limit/Stop when the source type is blank; prices and source volume are unchanged.</p></details>
          <button type="button" :disabled="rows.length === 1" @click="rows.splice(index, 1)">Remove signal symbol</button>
        </div>
        <button type="button" @click="rows.push({ source: '', destination: '', fixed_lots: '', order_type: config.additional_sources?.includes('panel') ? 'ENTRY' : 'SOURCE', same_price_scale: true })">Add signal symbol</button>
        <p>Entry, stop and target come from the intent. Market orders use the current execution price; limit and stop orders use the signal entry. Destination lot limits are checked before submission.</p>
        <button type="submit" class="primary">Save copy settings</button>
      </fieldset>
    </form>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.signal-settings{padding:24px}.signal-settings p{line-height:1.6}.signal-settings fieldset{border:0;padding:0;margin:24px 0}.signal-settings legend{font-weight:650;margin-bottom:16px}.signal-settings label{display:flex;flex-direction:column;gap:6px;font-size:14px}.signal-settings .check{flex-direction:row;margin-bottom:16px}.signal-settings .settings-grid,.signal-settings .mapping-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.signal-settings .mapping-row{padding:16px;background:#f5f8fb;border-radius:10px;margin-bottom:16px}.signal-settings input,.signal-settings select{min-width:0;width:100%;box-sizing:border-box}.signal-settings .check input{width:auto}.signal-settings details{font-size:13px}.signal-settings summary{cursor:pointer}.signal-settings button{cursor:pointer}@media(max-width:600px){.signal-settings .settings-grid,.signal-settings .mapping-row{grid-template-columns:1fr}}
</style>
