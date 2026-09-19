<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { request } from './api.js'
import BrokerOrders from './components/BrokerOrders.vue'
import TokenSession from './components/TokenSession.vue'
import OpenPositions from './components/OpenPositions.vue'
import BrokerSessions from './components/BrokerSessions.vue'
import LiveSignals from './components/LiveSignals.vue'

const state = ref({ accounts: [], running: false, connection: 'disconnected', orders: [], orders_at: null })
const selected = ref('')
const pendingAccounts = ref({})
const page = ref('bridge')
let lastBrokerRefresh = 0
const busy = ref(false)
const activeAction = ref('')
const error = ref('')
let timer, disposed = false, polling = false, revision = 0

async function refresh() {
  const requestedRevision = revision
  const current = await request('status')
  if (disposed || requestedRevision !== revision) return
  const brokerChanged = state.value.broker_id !== current.broker_id
  state.value = current
  if (brokerChanged || !selected.value || !current.accounts.some(account => account.id === selected.value)) selected.value = current.account_id
}
async function poll() {
  if (disposed || polling) return
  polling = true
  clearTimeout(timer)
  try {
  if (!busy.value) {
    try { await refresh(); error.value = '' } catch (err) { error.value = err.message }
    if (page.value === 'orders' && state.value.connection === 'connected' && Date.now() - lastBrokerRefresh > 5000) {
      await refreshBroker()
    }
  }
  } finally {
    polling = false
    if (!disposed) timer = setTimeout(poll, 1500)
  }
}
async function refreshBroker() {
  lastBrokerRefresh = Date.now()
  await action('orders/refresh')
  await action('positions/refresh')
}
async function openPage(value) {
  page.value = value
  if (value === 'orders' && state.value.connection === 'connected' && !busy.value) await refreshBroker()
}
async function action(name) {
  revision++
  busy.value = true
  activeAction.value = name
  error.value = ''
  try {
    state.value = await request(name, { account_id: selected.value })
    await refresh()
  } catch (err) { error.value = err.message }
  finally { busy.value = false; activeAction.value = '' }
}
async function brokerAction(name, brokerId, accountId) {
  revision++
  busy.value = true
  error.value = ''
  try {
    if (name === 'connect' || name === 'account') {
      state.value = await request('brokers/select', { broker_id: brokerId })
      state.value = await request('connect', { account_id: accountId ?? pendingAccounts.value[brokerId] ?? state.value.account_id })
    } else {
      state.value = await request(`brokers/${name}`, { broker_id: brokerId })
    }
    selected.value = state.value.account_id
    await refresh()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
function onVisible() { if (document.visibilityState === 'visible') poll() }
function selectAccount({ brokerId, accountId }) {
  pendingAccounts.value[brokerId] = accountId
  if (state.value.brokers?.find(b => b.id === brokerId)?.state === 'connected') {
    return brokerAction('account', brokerId, accountId)
  }
}
onMounted(() => {
  window.addEventListener('focus', poll)
  document.addEventListener('visibilitychange', onVisible)
  poll()
})
onUnmounted(() => {
  disposed = true
  revision++
  clearTimeout(timer)
  window.removeEventListener('focus', poll)
  document.removeEventListener('visibilitychange', onVisible)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">H</span> HCAMM</div>
      <div class="nav-label">WORKSPACE</div>
      <button class="nav-item" :class="{ active: page === 'bridge' }" @click="openPage('bridge')">Trading bridge</button>
      <button class="nav-item" :class="{ active: page === 'orders' }" @click="openPage('orders')">Orders</button>
      <button class="nav-item" :class="{ active: page === 'brokers' }" @click="openPage('brokers')">Broker sessions</button>
      <div class="sidebar-bottom"><span class="small-dot"></span> Local application<br><small>Match-Trader integration</small></div>
    </aside>
    <main>
      <header>
        <div><div class="eyebrow">QUANTOWER → MATCH-TRADER</div><h1>{{ page === 'brokers' ? 'Broker sessions' : page === 'orders' ? 'Orders & positions' : 'Trading bridge' }}</h1>
          <p>{{ page === 'brokers' ? 'Manage your brokers, choose an account, and keep your sessions connected.' : page === 'bridge' ? 'Watch and filter raw signals as they arrive from your strategies.' : 'Follow your accounts and incoming trading activity.' }}</p></div>
        <div v-if="page === 'orders'" class="mode-pill"><span class="small-dot"></span>{{ state.copying ? 'Copying enabled' : 'Capture only' }}</div>
      </header>
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
      <BrokerSessions v-if="page === 'brokers'" :brokers="state.brokers ?? []" :selected="state.broker_id" :busy="busy"
        @select="brokerAction('select', $event)" @connect="brokerAction('connect', $event)"
        @account="selectAccount" @disconnect="brokerAction('disconnect', $event)" />
      <section v-if="page === 'orders'" class="status-grid" aria-label="Service status">
        <article class="card metric"><span class="metric-label">BRIDGE</span>
          <strong><span class="status-dot" :class="{ on: state.running }"></span>{{ state.running ? 'Observing' : 'Stopped' }}</strong>
          <p>{{ state.capture_message || 'Loading local service…' }}</p></article>
        <article class="card metric"><span class="metric-label">BROKER CONNECTION</span>
          <strong class="capitalize">{{ state.connection }}</strong><p>{{ state.connection_message }}</p></article>
        <article class="card metric"><span class="metric-label">ACCOUNT IN VIEW</span>
          <strong>{{ state.account_id || '—' }}</strong><p>Orders sent by this bridge: {{ state.broker_orders_sent ?? 0 }}</p></article>
      </section>
      <TokenSession v-if="page === 'brokers'" :state="state" :busy="busy" :refreshing="activeAction === 'token/refresh'"
        @refresh="action('token/refresh')" />
      <template v-if="page === 'bridge'">
        <LiveSignals :port="state.signal_port || 8766" />
      </template>
      <template v-else-if="page === 'orders'">
      <BrokerOrders :orders="state.orders" :updated-at="state.orders_at" :connected="state.connection === 'connected'"
        :busy="busy" @refresh="action('orders/refresh')" />
      <OpenPositions :positions="state.positions ?? []" :updated-at="state.positions_at" :connected="state.connection === 'connected'"
        :busy="busy" @refresh="action('positions/refresh')" />
      <p class="quiet">Broker snapshots refresh every 5 seconds while this page is open.</p>
      </template>
      <footer>{{ page === 'brokers' ? 'Sessions remain active when you navigate away. Disconnect ends only that broker session.' : page === 'bridge' ? 'Sender timestamps are shown in UTC. Expand a lane row to inspect its signal payload.' : 'Account orders and positions update from your connected broker.' }}</footer>
    </main>
  </div>
</template>
