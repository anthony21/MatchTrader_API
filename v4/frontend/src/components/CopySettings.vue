<script setup>
import { onMounted, ref } from 'vue'
import { request } from '../api.js'
import TradingBoxForwarding from './TradingBoxForwarding.vue'

const props = defineProps({ state: Object })
const emit = defineEmits(['saved'])
const inventory = ref([]), rows = ref([{ source: '', destination: '', quantity_multiplier: '1', max_lots: '1', same_price_scale: false }])
const machine = ref(''), connection = ref(''), account = ref(''), destination = ref('')
const sources = ref(['P01', 'X17', 'R01', 'MANUAL']), csvLimit = ref(1000), exclusive = ref(false), legacyDisabled = ref(false)
const busy = ref(false), message = ref(''), error = ref('')
function selectSource(event) {
  const value = inventory.value[Number(event.target.value)]
  if (value) { machine.value = value.machine; connection.value = value.connection_id; account.value = value.account_id }
}
onMounted(async () => {
  try {
    const saved = await request('copy-settings')
    inventory.value = saved.inventory
    csvLimit.value = saved.csv_limit
    destination.value = props.state.account_id
    if (saved.route) {
      const r = saved.route
      machine.value = r.machine; connection.value = r.connection_id; account.value = r.account_id
      destination.value = r.destination_account; sources.value = r.sources
      exclusive.value = r.exclusive_destination; legacyDisabled.value = r.legacy_route_disabled
      rows.value = Object.entries(r.symbols).map(([source, value]) => ({ source, ...value }))
    } else if (inventory.value.length === 1) selectSource({ target: { value: 0 } })
  } catch (err) { error.value = err.message }
})
async function save() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    if (new Set(rows.value.map(row => row.source.trim())).size !== rows.value.length) throw Error('Each source symbol needs a unique mapping.')
    const symbols = Object.fromEntries(rows.value.map(({ source, ...mapping }) => [source.trim(), { ...mapping, same_price_scale: true, ...(mapping.fixed_lots ? { max_lots: mapping.fixed_lots } : {}), destination: mapping.destination.trim() }]))
    await request('copy-settings', { csv_limit: Number(csvLimit.value), route: {
      machine: machine.value.trim(), connection_id: connection.value.trim(), account_id: account.value.trim(),
      destination_account: destination.value, sources: sources.value, symbols,
      exclusive_destination: true, legacy_route_disabled: true,
    } })
    message.value = 'Settings saved.'
    emit('saved')
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <section class="card copy-settings">
    <h2>Copy settings</h2>
    <TradingBoxForwarding :pushed="state?.tradingbox_forwarding" />

    <form @submit.prevent="save">
      <fieldset :disabled="busy">
        <legend>Source and destination</legend>
        <label>Detected Quantower account
          <select aria-label="Detected Quantower account" :value="inventory.findIndex(item => item.machine === machine && item.connection_id === connection && item.account_id === account)" @change="selectSource"><option value="-1">Choose an account</option>
            <option v-for="(item, index) in inventory" :key="index" :value="index">{{ item.status }} · {{ item.machine }} · {{ item.connection_id }}</option>
          </select>
        </label>
        <div class="settings-grid">
          <label>Machine<input v-model="machine" required /></label>
          <label>Connection ID<input v-model="connection" required /></label>
          <label>Quantower internal account ID<input v-model="account" required /></label>
          <label>Broker destination<select v-model="destination" required><option v-for="item in state.accounts" :key="item.id" :value="item.id">{{ item.id }}</option></select></label>
        </div>
        <div class="settings-checks">
          <label><input type="checkbox" v-model="sources" value="X17" />X17</label>
          <label><input type="checkbox" v-model="sources" value="R01" />R01</label>
          <label><input type="checkbox" v-model="sources" value="P01" />P01 RR manual box</label>
          <label><input type="checkbox" v-model="sources" value="MANUAL" />Verified native manual sources</label>
        </div>
        
      </fieldset>
      <fieldset :disabled="busy">
        <legend>Symbol and quantity mapping</legend>
        
        <div v-for="(row, index) in rows" :key="index" class="mapping-row">
          <label>QT symbol<input v-model="row.source" required placeholder="EUR/USD" /></label>
          <label>Broker symbol<input v-model="row.destination" required placeholder="EURUSD" /></label>
          <label>Lot size<input v-model="row.fixed_lots" type="number" min="0.00000001" step="any" required /></label>
          <button type="button" class="secondary" :disabled="rows.length === 1" @click="rows.splice(index, 1)">Remove</button>
        </div>
        <button type="button" class="secondary" @click="rows.push({ source: '', destination: '', quantity_multiplier: '1', max_lots: '1', same_price_scale: false })">Add symbol</button>
      </fieldset>
      <fieldset :disabled="busy">
        

        


        <button class="primary" type="submit">{{ busy ? 'Saving…' : 'Save copy settings' }}</button>
      </fieldset>
    </form>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>

  </section>
</template>
