<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { request } from '../api.js'
// Saved wire-driven copy configurations. Each copies one strategy (its wire machineId + source)
// to one account, with its own sizing, grades and its own Paper/Live and On/Off. No global copy.
const props = defineProps({ configs: { type: Array, default: () => [] },
  accounts: { type: Array, default: () => [] },   // logged-in accounts: {account_id, profile, broker, capture}
  machines: { type: Array, default: () => [] },   // wire sources seen: {machine_id, source, count}
  selectedAccount: { type: String, default: '' } })
const GRADES = ['PRIME', 'STRONG', 'FAIR', 'POOR', 'WEAK', 'AVOID']
const SOURCES = ['r01Auto', 'chain', 'panel']
const SIZING = [['lots', 'Fixed lots (Symbol map)'], ['dollar', 'Fixed dollar risk'], ['percent', 'Percent of equity']]
const busy = ref(''), error = ref(''), message = ref('')
const editing = ref('')
const blank = () => ({ id: '', name: '', machine_id: '', source: 'r01Auto', connection_name: '',
  destination_broker: '', destination_account: '', sizing: 'lots', sizing_value: '',
  min_box: '', min_box_enabled: false, accepted_grades: [] })
const form = reactive(blank())
// Connected brokers (distinct), and the accounts available under the chosen one, from the
// logged-in accounts list. The machine picker offers the identities seen on the wire.
const brokers = computed(() => {
  const seen = new Map()
  for (const a of props.accounts) if (!seen.has(a.profile)) seen.set(a.profile, { profile: a.profile, broker: a.broker })
  return [...seen.values()]
})
const brokerAccounts = computed(() => props.accounts.filter(a => a.profile === form.destination_broker))
const machinePick = ref('')   // "machine_id|source" chosen from the wire list, or '' for manual entry
watch(machinePick, value => {
  if (!value) return
  const [machine_id, source] = value.split('|')
  form.machine_id = machine_id; form.source = source || form.source
})
watch(() => form.destination_broker, () => {
  if (!brokerAccounts.value.some(a => a.account_id === form.destination_account)) form.destination_account = ''
})
function prefillDestination() {
  // A new config defaults its destination to the Selected account, so it "holds the keys" already.
  const a = props.accounts.find(x => x.account_id === props.selectedAccount)
  if (a) { form.destination_broker = a.profile; form.destination_account = a.account_id }
}
function reset() { Object.assign(form, blank()); editing.value = ''; machinePick.value = ''; prefillDestination() }
watch(() => props.selectedAccount, () => { if (!editing.value && !form.destination_account) prefillDestination() }, { immediate: true })
function edit(c) {
  Object.assign(form, { ...blank(), ...c, sizing_value: c.sizing_value ?? '',
    min_box: c.min_box ?? '', min_box_enabled: !!c.min_box_enabled, accepted_grades: [...(c.accepted_grades || [])] })
  machinePick.value = props.machines.some(m => m.machine_id === c.machine_id && m.source === c.source) ? `${c.machine_id}|${c.source}` : ''
  editing.value = c.id
}
function toggleGrade(g, on) {
  const set = new Set(form.accepted_grades)
  if (on) set.add(g); else set.delete(g)
  form.accepted_grades = GRADES.filter(x => set.has(x))
}
async function save() {
  error.value = ''; message.value = ''
  if (!form.name.trim() || !form.machine_id.trim() || !form.destination_account) {
    error.value = 'Name, machine ID (source), and a destination account are required.'; return
  }
  busy.value = 'save'
  const body = { ...form, id: form.id || `cfg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    name: form.name.trim(), machine_id: form.machine_id.trim(), connection_name: form.connection_name.trim(),
    min_box_enabled: !!form.min_box_enabled, min_box: form.min_box_enabled ? String(form.min_box || 0).trim() : '0',
    ...(form.sizing === 'lots' ? { sizing_value: null } : { sizing_value: String(form.sizing_value).trim() }) }
  try { await request('copy-configs', body); message.value = `Saved "${body.name}".`; reset() }
  catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
async function act(path, body, tag) {
  busy.value = tag; error.value = ''
  try { await request(path, body) } catch (e) { error.value = e.message } finally { busy.value = '' }
}
const setMode = c => act('copy-configs/state', { id: c.id, mode: c.mode === 'live' ? 'paper' : 'live' }, `mode:${c.id}`)
const setEnabled = c => act('copy-configs/state', { id: c.id, enabled: !c.enabled }, `on:${c.id}`)
const remove = c => act('copy-configs/delete', { id: c.id }, `del:${c.id}`)
const brokerLabel = p => (brokers.value.find(b => b.profile === p)?.broker) || p
</script>

<template>
  <section class="card copy-configs" aria-label="Copy configurations">
    <h2>Copy configurations</h2>
    <p>Each configuration copies one strategy's live signals, matched by the machine ID it sends on the wire, to one broker account.
      Lots and order handling come from the Symbol map. The minimum box is set here per config with its own switch. Each config has its own Paper/Live and On/Off; there is no global switch.</p>

    <div v-if="!configs.length" class="empty-note">No configurations yet. Define one below and save it.</div>
    <article v-for="c in configs" :key="c.id" class="config-row" :class="{ live: c.mode === 'live' && c.enabled }">
      <div class="config-head">
        <strong>{{ c.name }}</strong>
        <span class="tag">{{ c.machine_id }} · {{ c.source }} → {{ brokerLabel(c.destination_broker) }} · {{ c.destination_account }}</span>
        <span v-if="c.min_box_enabled" class="tag">Min box {{ c.min_box }}</span>
      </div>
      <div class="config-switches">
        <button type="button" class="pill" :class="{ 'pill-live': c.mode === 'live' }" :disabled="busy === `mode:${c.id}`" @click="setMode(c)">{{ c.mode === 'live' ? 'Live' : 'Paper' }}</button>
        <button type="button" class="pill" :class="{ 'pill-on': c.enabled }" :disabled="busy === `on:${c.id}`" @click="setEnabled(c)">{{ c.enabled ? 'On' : 'Off' }}</button>
        <button type="button" class="link" @click="edit(c)">Edit</button>
        <button type="button" class="link" :disabled="busy === `del:${c.id}`" @click="remove(c)">Delete</button>
      </div>
    </article>

    <form class="config-form" @submit.prevent="save">
      <h3>{{ editing ? 'Edit configuration' : 'New configuration' }}</h3>
      <div class="grid">
        <label>Name<input v-model="form.name" required placeholder="MAD to GTR" /></label>
        <label>Signal source (machine ID seen on the wire)<select v-model="machinePick">
          <option value="">Type it manually…</option>
          <option v-for="m in machines" :key="`${m.machine_id}|${m.source}`" :value="`${m.machine_id}|${m.source}`">{{ m.machine_id }} · {{ m.source }}{{ m.count ? ` (${m.count})` : '' }}</option>
        </select></label>
        <label v-if="!machinePick">Machine ID<input v-model="form.machine_id" required placeholder="HCAMM_MAD" /></label>
        <label v-if="!machinePick">Signal family<select v-model="form.source"><option v-for="s in SOURCES" :key="s" :value="s">{{ s }}</option></select></label>
        <label>Connection ID (optional)<input v-model="form.connection_name" placeholder="leave blank to accept any" /></label>
        <label>Broker<select v-model="form.destination_broker"><option value="">Select a broker</option>
          <option v-for="b in brokers" :key="b.profile" :value="b.profile">{{ b.broker }}</option></select></label>
        <label>Account<select v-model="form.destination_account" required><option value="">Select an account</option>
          <option v-for="a in brokerAccounts" :key="a.account_id" :value="a.account_id">{{ a.account_id }}</option></select></label>
        <label>Sizing<select v-model="form.sizing"><option v-for="[v, l] in SIZING" :key="v" :value="v">{{ l }}</option></select></label>
        <label v-if="form.sizing !== 'lots'">{{ form.sizing === 'percent' ? 'Percent of equity' : 'Dollar risk' }}<input v-model="form.sizing_value" type="number" min="0.00000001" step="any" required /></label>
        <label class="check-inline"><input type="checkbox" v-model="form.min_box_enabled" />Filter by minimum box (TP→SL)</label>
        <label v-if="form.min_box_enabled">Minimum box<input v-model="form.min_box" type="number" min="0" step="any" placeholder="e.g. 75" /></label>
      </div>
      <div class="grades"><span>Accepted grades (none = all):</span>
        <label v-for="g in GRADES" :key="g" class="check"><input type="checkbox" :checked="form.accepted_grades.includes(g)" @change="toggleGrade(g, $event.target.checked)" />{{ g }}</label>
      </div>
      <div class="actions">
        <button type="submit" class="primary" :disabled="busy === 'save'">{{ busy === 'save' ? 'Saving…' : editing ? 'Save changes' : 'Save configuration' }}</button>
        <button v-if="editing" type="button" @click="reset">Cancel</button>
      </div>
    </form>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
.copy-configs{padding:24px}.copy-configs p{line-height:1.6;color:#52647a}
.empty-note{color:#7c8b9e;padding:12px 0}
.config-row{border:1px solid #e0e6ee;border-radius:10px;padding:14px 16px;margin:12px 0;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.config-row.live{border-color:#9b2226;background:#fff5f5}
.config-head{display:flex;flex-direction:column;gap:4px;min-width:0}.config-head strong{font-size:15px}.config-head .tag{font-size:12px;color:#6a7e94;overflow-wrap:anywhere}
.config-switches{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.pill{background:#eef2f6;border:1px solid #d7dfe9;border-radius:30px;padding:7px 15px;font-weight:600;cursor:pointer;min-height:auto}
.pill-live{background:#9b2226;color:#fff;border-color:#9b2226}.pill-on{background:#146e5b;color:#fff;border-color:#146e5b}
.copy-configs .link{background:none;border:0;color:#3a6ea5;cursor:pointer;padding:6px}
.config-form{border-top:1px solid #e6ebf2;margin-top:20px;padding-top:16px}.config-form h3{margin:0 0 12px;font-size:15px}
.copy-configs .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.copy-configs label{display:flex;flex-direction:column;gap:6px;font-size:13px}
.copy-configs input,.copy-configs select{padding:10px;border:1px solid #ced8e4;border-radius:7px;min-width:0}
.copy-configs .check-inline{flex-direction:row;align-items:center;gap:8px;align-self:end}.copy-configs .check-inline input{width:auto;padding:0}
.grades{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:16px 0;font-size:13px}.grades .check{flex-direction:row;gap:6px}.grades .check input{width:auto}
.copy-configs .actions{display:flex;gap:12px;margin-top:8px}.copy-configs .actions button{padding:10px 16px;border-radius:7px;cursor:pointer;border:1px solid #ced8e4}
.copy-configs .primary{background:#146e5b;border-color:#146e5b;color:#fff}
@media(max-width:700px){.copy-configs .grid{grid-template-columns:1fr}}
</style>
