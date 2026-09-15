<script setup>
import { computed, onMounted, ref } from 'vue'
import { request } from '../api.js'
const props = defineProps({ state: Object })
const ORDER_TYPES = [
  ['SOURCE', 'Use source order type'], ['ENTRY', 'Pending at logged entry (source type or broker quote)'],
  ['MARKET', 'Market - current price'], ['LIMIT', 'Limit - signal entry'], ['STOP', 'Stop - signal entry']]
const rows = ref([])
const busy = ref(false), error = ref(''), message = ref('')
const live = computed(() => !!props.state?.signal_copying)
function blank() { return { source: '', destination: '', lots: '', order_type: 'SOURCE' } }
async function load() {
  error.value = ''
  try {
    const saved = await request('symbol-map')
    rows.value = Object.entries(saved).map(([source, value]) => ({ source, ...value }))
    if (!rows.value.length) rows.value = [blank()]
  } catch (err) { error.value = err.message }
}
onMounted(load)
async function save() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    const sources = rows.value.map(row => row.source.trim())
    if (sources.some(s => !s)) throw Error('Every row needs a Quantower symbol.')
    if (new Set(sources).size !== sources.length) throw Error('Quantower symbols must be unique.')
    const map = Object.fromEntries(rows.value.map(({ source, destination, lots, order_type }) =>
      [source.trim(), { destination: destination.trim(), lots: String(lots).trim(), order_type }]))
    const saved = await request('symbol-map', map)
    rows.value = Object.entries(saved).map(([source, value]) => ({ source, ...value }))
    message.value = `Symbol map saved: ${rows.value.length} symbol${rows.value.length === 1 ? '' : 's'}.`
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <section class="card symbol-map" aria-label="Symbol map">
    <h2>Symbol map</h2>
    <p>One row per Quantower symbol: the AquaFunded instrument it becomes, the lot size sent, and how the order type is chosen.
      The signal engine looks this table up for every intent; it is not part of the lane settings and is saved on its own.
      Use the destination name exactly as AquaFunded lists it (for example SPX500, NAS100, XAUUSD).
      The minimum box (take-profit to stop-loss distance) is set per copy configuration, with its own switch, not here.</p>
    <form @submit.prevent="save">
      <fieldset :disabled="busy || live">
        <table>
          <thead><tr><th>Quantower symbol</th><th>AquaFunded instrument</th><th>Lots</th><th>Order handling</th><th></th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="index" class="mapping-row">
              <td><input v-model="row.source" aria-label="Quantower symbol" required placeholder="US 500" /></td>
              <td><input v-model="row.destination" aria-label="AquaFunded instrument" required placeholder="SPX500" /></td>
              <td><input v-model="row.lots" aria-label="Lots" type="number" min="0.00000001" step="any" required /></td>
              <td><select v-model="row.order_type" aria-label="Order handling" required>
                <option v-for="[value, label] in ORDER_TYPES" :key="value" :value="value">{{ label }}</option></select></td>
              <td><button type="button" :disabled="rows.length === 1" @click="rows.splice(index, 1)">Remove</button></td>
            </tr>
          </tbody>
        </table>
        <div class="actions">
          <button type="button" @click="rows.push(blank())">Add symbol</button>
          <button type="submit" class="primary">Save symbol map</button>
          <button type="button" @click="load">Reload</button>
        </div>
      </fieldset>
    </form>
    <p v-if="live" class="note">Turn live signal copying off before editing the map.</p>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.symbol-map{padding:24px}.symbol-map p{line-height:1.6}.symbol-map fieldset{border:0;padding:0;margin:16px 0}
.symbol-map table{width:100%;border-collapse:collapse}.symbol-map th{text-align:left;font-size:13px;padding:6px 8px;color:#556}
.symbol-map td{padding:6px 8px;vertical-align:middle}.symbol-map input,.symbol-map select{width:100%;min-width:0;box-sizing:border-box}
.symbol-map .actions{display:flex;gap:12px;margin-top:16px;flex-wrap:wrap}.symbol-map button{cursor:pointer}.symbol-map .note{color:#8a6d00}
@media(max-width:700px){.symbol-map table,.symbol-map thead,.symbol-map tbody,.symbol-map tr,.symbol-map td{display:block}.symbol-map th{display:none}.symbol-map tr{margin-bottom:16px;padding:8px;background:#f5f8fb;border-radius:10px}}
</style>
