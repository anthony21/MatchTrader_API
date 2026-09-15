<script setup>
import { computed, onMounted, ref } from 'vue'
import { request } from '../api.js'
// One form serves both lanes. The P01/X17 lane posts to signal-copy-settings; the R01 lane
// posts to r01-lane, has its source fixed to R01, and adds grade gating and dollar risk.
const props = defineProps({ state: Object, endpoint: { type: String, default: 'signal-copy-settings' },
  title: { type: String, default: 'Strategy signal lane' }, r01: { type: Boolean, default: false },
  destinations: { type: Array, default: () => [] } })
const emit = defineEmits(['saved'])
const GRADES = ['PRIME', 'STRONG', 'FAIR', 'POOR', 'WEAK', 'AVOID']
// The lane: which machine and source, to which account, and how attribution is proven.
// Symbols are not here; the Symbol map page owns them and the engine looks them up.
const config = ref({ machine_id: '', source: props.r01 ? 'R01' : 'chain', connection_name: '', destination_account: '',
  exclusive_destination: true, accepted_grades: [], retract_on_downgrade: true, risk_usd: '',
  min_box: '', min_box_enabled: false })
const live = computed(() => !!props.state?.signal_copying)
function selectP01() {
  if (config.value.p01_log_enabled) {
    config.value.source = 'P01_LOG'
    config.value.additional_sources = []
    config.value.machine_id = props.state?.p01_log?.machine || ''
    config.value.connection_name = ''
  }
}
function selectX17P01() {
  config.value.source = 'chain'
  config.value.additional_sources = ['panel']
  config.value.p01_log_enabled = false
  config.value.x17_only = true
  config.value.machine_id = props.state?.p01_log?.machine || config.value.machine_id
}
function toggleGrade(grade, checked) {
  const set = new Set(config.value.accepted_grades || [])
  if (checked) set.add(grade); else set.delete(grade)
  config.value.accepted_grades = GRADES.filter(g => set.has(g))
}
const busy = ref(false), error = ref(''), message = ref('')
onMounted(async () => {
  try {
    const saved = await request(props.endpoint)
    if (saved.config) {
      const { symbols, ...lane } = saved.config
      config.value = { accepted_grades: [], retract_on_downgrade: true, risk_usd: '', min_box: '', min_box_enabled: false,
        ...lane, risk_usd: lane.risk_usd ?? '', min_box: lane.min_box ?? '', min_box_enabled: !!lane.min_box_enabled }
    } else {
      config.value.destination_account = props.state?.account_id || ''
      if (props.r01) config.value.machine_id = props.state?.p01_log?.machine || ''
    }
  } catch (err) { error.value = err.message }
})
async function save() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    const { risk_usd, ...lane } = config.value
    const body = { ...lane, exclusive_destination: true, machine_id: config.value.machine_id.trim(),
      source: props.r01 ? 'R01' : config.value.source.trim(), connection_name: (config.value.connection_name || '').trim(),
      min_box_enabled: !!config.value.min_box_enabled,
      min_box: config.value.min_box_enabled ? String(config.value.min_box || 0).trim() : '0' }
    if (String(risk_usd ?? '').trim() !== '') body.risk_usd = String(risk_usd).trim()
    await request(props.endpoint, body)
    message.value = 'Lane saved.'
    emit('saved')
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <section class="card signal-settings" aria-label="Signal copy settings">
    <h2>{{ title }}</h2>
    <p v-if="r01">R01 ledger intents copied automatically: which machine writes the ledger, to which account, which grades may open,
      and the dollar risk per trade. Symbols, lot sizes and order handling live on the Symbol map page; a dollar risk here overrides the map's lots.</p>
    <p v-else>Which machine and source this API copies from, and to which account. Symbols, lot sizes and order handling live on the Symbol map page.</p>
    <form @submit.prevent="save">
      <fieldset :disabled="busy || live || state?.copying">
        <legend>Signal source and destination</legend>
        <template v-if="!r01">
          <button type="button" @click="selectX17P01">Use X17 + manual P01 at logged entry</button>
          <label class="check"><input type="checkbox" :checked="config.additional_sources?.includes('panel')" @change="config.additional_sources = $event.target.checked ? ['panel'] : []" />Also accept structured P01 panel signals</label>
          <label class="check"><input v-model="config.x17_only" type="checkbox" />Require X17 attribution for chain intents</label>
          <label class="check"><input v-model="config.p01_log_enabled" type="checkbox" @change="selectP01" />Copy P01 chart intents from the local log</label>
        </template>
        <div class="settings-grid">
          <label>Signal machine ID<input v-model="config.machine_id" required placeholder="machineId from the request" /></label>
          <label>Signal source<input v-model="config.source" :readonly="r01" required /></label>
          <label v-if="!r01">Chart connection name (optional)<input v-model="config.connection_name" placeholder="For example, Time - 15s" /></label>
          <label>MatchTrader destination<select v-model="config.destination_account" required><option value="">Select an account</option>
            <option v-for="account in destinations" :key="`${account.profile}:${account.id}`" :value="account.id">{{ account.broker }} · {{ account.id }}</option>
            <option v-if="config.destination_account && !destinations.some(a => a.id === config.destination_account)" :value="config.destination_account">{{ config.destination_account }} (not connected)</option>
          </select></label>
        </div>
        <template v-if="r01">
          <legend>Grades and risk</legend>
          <div class="grades">
            <label v-for="grade in GRADES" :key="grade" class="check"><input type="checkbox" :checked="config.accepted_grades?.includes(grade)" @change="toggleGrade(grade, $event.target.checked)" />{{ grade }}</label>
          </div>
          <p class="hint">No grade ticked means every grade may open.</p>
          <label class="check"><input v-model="config.retract_on_downgrade" type="checkbox" />Cancel a resting copy when R01 regrades it below the accepted grades</label>
          <div class="settings-grid">
            <label>Risk per trade (USD, optional)<input v-model="config.risk_usd" type="number" min="0" step="any" placeholder="Leave blank to use the map's lots" /></label>
          </div>
        </template>
        <legend>Minimum box</legend>
        <label class="check"><input v-model="config.min_box_enabled" type="checkbox" />Skip intents whose box (take-profit to stop-loss distance) is below a minimum</label>
        <div v-if="config.min_box_enabled" class="settings-grid">
          <label>Minimum box (TP→SL)<input v-model="config.min_box" type="number" min="0" step="any" placeholder="e.g. 75" /></label>
        </div>
        <p class="hint">One minimum for every instrument this lane copies. Tight boxes stop out on entry noise. Off accepts any size.</p>
        <button type="submit" class="primary">Save lane</button>
      </fieldset>
    </form>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.signal-settings{padding:24px}.signal-settings p{line-height:1.6}.signal-settings fieldset{border:0;padding:0;margin:24px 0}.signal-settings legend{font-weight:650;margin-bottom:16px}.signal-settings label{display:flex;flex-direction:column;gap:6px;font-size:14px}.signal-settings .check{flex-direction:row;margin-bottom:16px}.signal-settings .settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:16px}.signal-settings .grades{display:flex;gap:18px;flex-wrap:wrap}.signal-settings .grades .check{margin-bottom:8px}.signal-settings .hint{font-size:13px;color:#556;margin:0 0 12px}.signal-settings input,.signal-settings select{min-width:0;width:100%;box-sizing:border-box}.signal-settings .check input{width:auto}.signal-settings button{cursor:pointer}@media(max-width:600px){.signal-settings .settings-grid{grid-template-columns:1fr}}
</style>
