<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api.js'
import { localTime } from '../time.js'
const profiles = ref([]), busy = ref([]), error = ref('')
let disposed = false, timer
function apply(value) {
  if (disposed) return
  profiles.value = value.profiles.map(row => {
    const prior = profiles.value.find(p => p.profile === row.profile)
    return prior && prior.revision > row.revision ? prior : row
  })
}
async function act(profile, action) {
  if (busy.value.includes(profile)) return
  busy.value = [...busy.value, profile]
  try { apply(await request('broker-profiles/action', { profile, action })); error.value = '' }
  catch (e) { if (!disposed) error.value = e.message }
  finally { busy.value = busy.value.filter(p => p !== profile) }
}
async function poll() {
  try {
    apply(await request('broker-profiles'))
    await Promise.all(profiles.value.filter(p => p.connection === 'connected').map(p => act(p.profile, 'refresh')))
  } catch (e) { if (!disposed) error.value = e.message }
  if (!disposed) timer = setTimeout(poll, 5000)
}
function connectAll() { return Promise.all(profiles.value.filter(p => p.account_id && p.connection !== 'connected').map(p => act(p.profile, 'connect'))) }
onMounted(poll)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>
<template>
  <section class="brokers-page">
    <div class="card broker-intro"><h2>Broker accounts</h2><p>Up to five independent profiles. Each card keeps its own broker, account, currency and snapshots.</p>
      <button @click="connectAll">Connect configured accounts</button><p>Connected cards refresh every five seconds while this page is open. Connections stay open when you leave.</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="!profiles.length">No profiles loaded. Restart the v4 backend after editing .env.</p></div>
    <article v-for="p in profiles" :key="p.profile" class="card broker-card" :aria-label="`${p.profile} broker account`">
      <h3>{{ p.profile }} · Account {{ p.account_id || 'not configured' }}</h3><p>{{ p.broker }}</p>
      <strong>{{ p.connection }}</strong><p v-if="p.error" role="alert">{{ p.error }}</p>
      <div class="broker-actions"><button :disabled="busy.includes(p.profile) || !p.account_id || p.connection === 'connected'" @click="act(p.profile, 'connect')">Connect {{ p.profile }}</button>
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
.brokers-page{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:18px}.broker-intro{grid-column:1/-1}.broker-intro,.broker-card{padding:22px;min-width:0}.broker-card p,.broker-card small{overflow-wrap:anywhere;color:#52647a}.broker-actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.brokers-page button{padding:9px;border:1px solid #ced8e4;border-radius:7px;cursor:pointer}.broker-balance{display:flex;gap:22px;flex-wrap:wrap}.broker-balance strong{display:block;font-size:21px}.broker-trade{border-top:1px solid #dbe3ed;padding:12px 0;overflow-wrap:anywhere}.broker-trade small{display:block;margin-top:6px}
</style>
