<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { request } from './api.js'
import { followNativeEvents } from './stream.js'
import AccountControls from './components/AccountControls.vue'
import OrdersWorkspace from './components/OrdersWorkspace.vue'
import TokenSession from './components/TokenSession.vue'
import NativeEvents from './components/NativeEvents.vue'
import CopySettings from './components/CopySettings.vue'

const state = ref({ accounts: [], running: false, connection: 'disconnected', orders: [], orders_at: null })
const selected = ref('')
const events = ref([])
const nativeEvents = ref([])
const mappings = ref([])
const page = ref('bridge')
let lastBrokerRefresh = 0
const busy = ref(false)
const activeAction = ref('')
const error = ref('')
let timer, disposed = false, stopStream
const streamStatus = ref('connecting')

async function refresh() {
  const current = await request('status')
  state.value = current
  if (!selected.value || !current.accounts.some(account => account.id === selected.value)) selected.value = current.account_id
  const feed = await request('events')
  events.value = feed.account_id === current.account_id ? feed.events : []
  if (streamStatus.value !== 'live') {
    const snapshot = await request('capture/events')
    if (streamStatus.value !== 'live') nativeEvents.value = snapshot.events ?? []
  }
  const mappingFeed = await request('trade-mappings')
  mappings.value = mappingFeed.account_id === current.account_id ? mappingFeed.mappings ?? [] : []
}
async function poll() {
  if (!busy.value) {
    try { await refresh(); error.value = '' } catch (err) { error.value = err.message }
    if (page.value === 'orders' && state.value.connection === 'connected' && Date.now() - lastBrokerRefresh > 5000) {
      await refreshBroker()
    }
  }
  if (!disposed) timer = setTimeout(poll, 1500)
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
async function toggleCopying() {
  busy.value = true
  try { state.value = await request('copying', { enabled: !state.value.copying }) }
  catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function action(name) {
  busy.value = true
  activeAction.value = name
  error.value = ''
  try {
    state.value = await request(name, { account_id: selected.value })
    await refresh()
  } catch (err) { error.value = err.message }
  finally { busy.value = false; activeAction.value = '' }
}
onMounted(() => {
  stopStream = followNativeEvents(value => { nativeEvents.value = value }, value => { streamStatus.value = value })
  poll()
})
onUnmounted(() => { disposed = true; stopStream?.(); clearTimeout(timer) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">H</span> HCAMM</div>
      <div class="nav-label">WORKSPACE</div>
      <button class="nav-item" :class="{ active: page === 'bridge' }" @click="openPage('bridge')">Trading bridge</button>
      <button class="nav-item" :class="{ active: page === 'orders' }" @click="openPage('orders')">Orders</button>
      <button class="nav-item" :class="{ active: page === 'settings' }" @click="openPage('settings')">Copy settings</button>
      <div class="sidebar-bottom"><span class="small-dot"></span> Local application<br><small>Match-Trader integration</small></div>
    </aside>
    <main>
      <header>
        <div><div class="eyebrow">QUANTOWER → MATCH-TRADER</div><h1>{{ page === 'settings' ? 'Copy settings' : page === 'orders' ? 'Orders & positions' : 'Trading bridge' }}</h1>
          <p>{{ page === 'orders' ? 'Positions, pending orders and copy activity — organized by trade.' : 'Choose your account. Control the connection. Follow every incoming event.' }}</p></div>
        <div class="mode-pill"><span class="small-dot"></span>{{ state.copying ? 'API trading enabled' : 'API trading off' }}</div>
      </header>
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
      <AccountControls :state="state" v-model:selected="selected" :busy="busy"
        @connect="action('connect')" @start="action('start')" @stop="action('stop')" />
      <section v-if="page !== 'orders'" class="status-grid" aria-label="Service status">
        <article class="card metric"><span class="metric-label">BRIDGE</span>
          <strong><span class="status-dot" :class="{ on: state.running }"></span>{{ state.running ? 'Observing' : 'Stopped' }}</strong>
          <p>{{ state.capture_message || 'Loading local service…' }}</p></article>
        <article class="card metric"><span class="metric-label">BROKER CONNECTION</span>
          <strong class="capitalize">{{ state.connection }}</strong><p>{{ state.connection_message }}</p></article>
        <article class="card metric"><span class="metric-label">ACCOUNT IN VIEW</span>
          <strong>{{ state.account_id || '—' }}</strong><p>Orders sent by this bridge: {{ state.broker_orders_sent ?? 0 }}</p></article>
      </section>
      <TokenSession v-if="page !== 'orders'" :state="state" :busy="busy" :refreshing="activeAction === 'token/refresh'"
        @refresh="action('token/refresh')" />
      <template v-if="page === 'bridge'">
      <NativeEvents :events="nativeEvents" :legacy-events="events" :stream-status="streamStatus" :state="state" :busy="busy" @toggle="toggleCopying" />
      </template>
      <CopySettings v-else-if="page === 'settings'" :state="state" @saved="refresh" />
      <template v-else>
      <OrdersWorkspace :state="state" :mappings="mappings" :busy="busy" @refresh="refreshBroker" />
      </template>
      <footer>Version {{ state.version || '—' }} · Native event receipt and broker acceptance are separate stages. CSV observations are never copied.</footer>
    </main>
  </div>
</template>
