<script setup>
import { computed, onMounted, ref } from 'vue'
import { request } from '../api.js'
const props = defineProps({ state: Object })
const emit = defineEmits(['saved'])
// The lane: which machine and source, to which account, and how attribution is proven.
// Symbols are not here; the Symbol map page owns them and the engine looks them up.
const config = ref({ machine_id: '', source: 'chain', connection_name: '', destination_account: '', exclusive_destination: true })
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
const busy = ref(false), error = ref(''), message = ref('')
onMounted(async () => {
  try {
    const saved = await request('signal-copy-settings')
    if (saved.config) {
      const { symbols, ...lane } = saved.config
      config.value = lane
    } else config.value.destination_account = props.state?.account_id || ''
  } catch (err) { error.value = err.message }
})
async function save() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    await request('signal-copy-settings', { ...config.value, exclusive_destination: true, machine_id: config.value.machine_id.trim(), source: config.value.source.trim(), connection_name: config.value.connection_name.trim() })
    message.value = 'Lane saved.'
    emit('saved')
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <section class="card signal-settings" aria-label="Signal copy settings">
    <h2>Strategy signal lane</h2>
    <p>Which machine and source this API copies from, and to which account. Symbols, lot sizes and order handling live on the Symbol map page.</p>
    <form @submit.prevent="save">
      <fieldset :disabled="busy || live || state?.copying">
        <legend>Signal source and destination</legend>
        <button type="button" @click="selectX17P01">Use X17 + manual P01 at logged entry</button>
        <label class="check"><input type="checkbox" :checked="config.additional_sources?.includes('panel')" @change="config.additional_sources = $event.target.checked ? ['panel'] : []" />Also accept structured P01 panel signals</label>
        <label class="check"><input v-model="config.x17_only" type="checkbox" />Require X17 attribution for chain intents</label>
        <label class="check"><input v-model="config.p01_log_enabled" type="checkbox" @change="selectP01" />Copy P01 chart intents from the local log</label>
        <div class="settings-grid">
          <label>Signal machine ID<input v-model="config.machine_id" required placeholder="machineId from the request" /></label>
          <label>Signal source<input v-model="config.source" required /></label>
          <label>Chart connection name (optional)<input v-model="config.connection_name" placeholder="For example, Time - 15s" /></label>
          <label>MatchTrader destination<select v-model="config.destination_account" required><option value="">Select an account</option><option v-for="account in state?.accounts || []" :key="account.id" :value="account.id">{{ account.id }}</option></select></label>
        </div>
        <button type="submit" class="primary">Save lane</button>
      </fieldset>
    </form>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.signal-settings{padding:24px}.signal-settings p{line-height:1.6}.signal-settings fieldset{border:0;padding:0;margin:24px 0}.signal-settings legend{font-weight:650;margin-bottom:16px}.signal-settings label{display:flex;flex-direction:column;gap:6px;font-size:14px}.signal-settings .check{flex-direction:row;margin-bottom:16px}.signal-settings .settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:16px}.signal-settings input,.signal-settings select{min-width:0;width:100%;box-sizing:border-box}.signal-settings .check input{width:auto}.signal-settings button{cursor:pointer}@media(max-width:600px){.signal-settings .settings-grid{grid-template-columns:1fr}}
</style>
