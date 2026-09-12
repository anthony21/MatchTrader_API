<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { request } from '../api.js'
import { localTime } from '../time.js'
// The profile snapshot arrives on the dashboard stream; this never polls for it.
const props = defineProps({ pushed: Object })
const profiles = ref([]), busy = ref([]), error = ref('')
const loginProfile = ref(''), tradingAccount = ref('')
const selectedProfile = computed(() => profiles.value.find(p => p.profile === loginProfile.value))
const loginStatus = computed(() => selectedProfile.value?.login_status || 'disconnected')
watch(loginProfile, () => { tradingAccount.value = '' })
let disposed = false, timer
function apply(value) {
  if (disposed) return
  profiles.value = value.profiles.map(row => {
    const prior = profiles.value.find(p => p.profile === row.profile)
    return prior && prior.revision > row.revision ? prior : row
  })
  if (!profiles.value.some(p => p.profile === loginProfile.value)) loginProfile.value = profiles.value.some(p => p.profile === value.active_profile) ? value.active_profile : profiles.value[0]?.profile || ''
  if (!selectedProfile.value?.accounts?.some(a => a.id === tradingAccount.value)) tradingAccount.value = ''
}
async function act(profile, action, account_id) {
  if (busy.value.includes(profile)) return
  busy.value = [...busy.value, profile]
  try { apply(await request('broker-profiles/action', { profile, action, ...(account_id ? { account_id } : {}) })); error.value = '' }
  catch (e) { if (!disposed) error.value = e.message }
  finally { busy.value = busy.value.filter(p => p !== profile) }
}
// Balances, pending orders and open positions are broker-owned and cannot be pushed,
// so refresh them only for connected profiles that actually have something working.
function working(row) {
  return row.connection === 'connected' && ((row.orders?.length || 0) + (row.positions?.length || 0)) > 0
}
async function refreshWorking() {
  timer = undefined
  if (disposed) return
  const live = profiles.value.filter(working)
  if (live.length) {
    try { await Promise.all(live.map(p => act(p.profile, 'refresh'))) }
    catch (e) { if (!disposed) error.value = e.message }
  }
  schedule()
}
function schedule() {
  if (disposed || timer || !profiles.value.some(working)) return
  timer = setTimeout(refreshWorking, 5000)
}
watch(() => props.pushed, value => { if (value) { apply(value); schedule() } }, { immediate: true })
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>
<template>
  <section class="brokers-page">
    <div class="card broker-intro"><h2>Broker accounts</h2><p>Choose a login from .env, then select a trading account returned by that broker.</p>
      <div class="login-picker">
        <label>Platform<select v-model="loginProfile" aria-label="Platform" :disabled="!profiles.length">
          <option v-for="p in profiles" :key="p.profile" :value="p.profile">{{ p.label || p.profile }}</option>
        </select></label>
        <button :disabled="!loginProfile || busy.includes(loginProfile) || loginStatus === 'connected'" @click="act(loginProfile, loginStatus === 'disconnected' ? 'login' : 'refresh_login')">{{ busy.includes(loginProfile) ? 'Working…' : loginStatus === 'connected' ? 'Logged in' : loginStatus === 'disconnected' ? 'Log in' : 'Refresh login' }}</button>
        <p class="platform-status" role="status">{{ selectedProfile?.label || loginProfile }}: {{ loginStatus === 'connected' ? 'Connected' : loginStatus === 'expired' ? 'Session expired — refresh login' : loginStatus === 'expiry unknown' ? 'Logged in — token expiry unavailable; refresh to verify' : 'Not connected' }}<span v-if="selectedProfile?.login_expires_at"> · Expires {{ localTime(selectedProfile.login_expires_at) }}</span></p>
        <template v-if="selectedProfile?.accounts?.length">
          <label class="account-picker">Available trading accounts<select v-model="tradingAccount" aria-label="Available trading accounts" :disabled="busy.includes(loginProfile)">
            <option value="" disabled>Select an account</option>
            <option v-for="a in selectedProfile.accounts" :key="`${loginProfile}:${a.id}`" :value="a.id">{{ a.id }}{{ a.demo ? ' · Demo' : '' }}</option>
          </select></label>
          <button :disabled="!tradingAccount || busy.includes(loginProfile)" @click="act(loginProfile, 'select', tradingAccount)">Use selected account</button>
        </template>
      </div>
      <p v-if="selectedProfile?.accounts?.length">{{ selectedProfile.accounts.length }} accounts returned by {{ loginProfile }}. Selecting one opens its account session; credentials and tokens stay on the backend.</p>
      <p>Only the selected platform is shown. Other platform sessions stay separate. Profiles arrive from the server as they change; broker balances, orders and positions refresh every five seconds only while a connected account has something pending or open.</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="selectedProfile?.error" role="alert">{{ selectedProfile.error }}</p>
      <p v-if="!profiles.length">No profiles loaded. Restart the v4 backend after editing .env.</p></div>
    <article v-for="p in profiles.filter(p => p.profile === loginProfile)" :key="p.profile" class="card broker-card" :aria-label="`${p.profile} broker account`">
      <h3>{{ p.label || p.profile }} ({{ p.profile }}) · Account {{ p.account_id || 'not configured' }}</h3><p>{{ p.broker }}</p>
      <strong>{{ p.connection }}</strong><p v-if="p.error" role="alert">{{ p.error }}</p>
      <p v-if="p.connection === 'connected'">Session: {{ p.profile }} / {{ p.account_id }} · {{ p.session_expires_at ? `Expires ${localTime(p.session_expires_at)}` : 'Expiration unavailable' }}</p>
      <div class="broker-actions">
        <button :disabled="busy.includes(p.profile) || p.connection !== 'connected'" @click="act(p.profile, 'refresh')">Refresh {{ p.profile }}</button>
        <button :disabled="busy.includes(p.profile) || p.connection !== 'connected'" @click="act(p.profile, 'disconnect')">Disconnect {{ p.profile }}</button></div>
      <div v-if="p.balance" class="broker-balance"><span>Balance <strong>{{ p.balance.balance }} {{ p.balance.currency }}</strong></span><span>Equity <strong>{{ p.balance.equity }} {{ p.balance.currency }}</strong></span></div>
      <p>Last successful snapshot: {{ localTime(p.updated_at) }}</p>
      <template v-if="p.connection === 'connected'">
        <h4>Pending orders · {{ p.orders?.length ?? 0 }}</h4>
        <div v-for="o in p.orders" :key="`${p.profile}:order:${o.id}`" class="broker-trade"><strong>{{ o.symbol }} {{ o.side }}</strong> · {{ o.volume }} lots · {{ o.type }} @ {{ o.activationPrice }}<small>SL {{ o.stopLoss ?? '—' }} · TP {{ o.takeProfit ?? '—' }} · Order {{ o.id }}</small></div>
        <h4>Open positions · {{ p.positions?.length ?? 0 }}</h4>
        <div v-for="o in p.positions" :key="`${p.profile}:position:${o.id}`" class="broker-trade"><strong>{{ o.symbol }} {{ o.side }}</strong> · {{ o.volume }} lots @ {{ o.openPrice }}<small>P/L {{ o.netProfit ?? o.profit ?? 'Unavailable' }} · Position {{ o.id }}</small></div>
      </template>
    </article>
  </section>
</template>
<style scoped>
.login-picker{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin:16px 0}.login-picker label{display:grid;gap:8px;min-width:0;max-width:100%}.login-picker select{padding:10px;max-width:100%;border:1px solid #ced8e4;border-radius:7px}
.platform-status{flex-basis:100%;margin:0}.account-picker{min-width:240px}
.brokers-page{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:18px}.broker-intro{grid-column:1/-1}.broker-intro,.broker-card{padding:22px;min-width:0}.broker-card p,.broker-card small{overflow-wrap:anywhere;color:#52647a}.broker-actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.brokers-page button{padding:9px;border:1px solid #ced8e4;border-radius:7px;cursor:pointer}.broker-balance{display:flex;gap:22px;flex-wrap:wrap}.broker-balance strong{display:block;font-size:21px}.broker-trade{border-top:1px solid #dbe3ed;padding:12px 0;overflow-wrap:anywhere}.broker-trade small{display:block;margin-top:6px}
</style>
