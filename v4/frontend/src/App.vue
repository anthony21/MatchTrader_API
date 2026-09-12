<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request } from './api.js'
import { followDashboard } from './stream.js'
import AccountControls from './components/AccountControls.vue'
import OrdersWorkspace from './components/OrdersWorkspace.vue'
import TokenSession from './components/TokenSession.vue'
import NativeEvents from './components/NativeEvents.vue'
import CopySettings from './components/CopySettings.vue'
import SignalCopySettings from './components/SignalCopySettings.vue'
import SignalActivity from './components/SignalActivity.vue'
import RawEvents from './components/RawEvents.vue'
import LoggingEvents from './components/LoggingEvents.vue'
import BrokerProfiles from './components/BrokerProfiles.vue'
import CopyControls from './components/CopyControls.vue'
import VerifiedTrades from './components/VerifiedTrades.vue'
import PaperTrades from './components/PaperTrades.vue'

const PAGES = ['bridge', 'orders', 'verified', 'paper', 'brokers', 'logging', 'raw', 'settings']
// Pages that carry the service status grid and token panel above their workspace.
const OVERVIEW_PAGES = ['bridge', 'settings']
const TITLES = { bridge: 'Trading bridge', orders: 'Orders & positions', verified: 'Verified trades', paper: 'Paper trades',
  brokers: 'Broker accounts', logging: 'Event logging', raw: 'Raw events', settings: 'Copy settings' }
const DESCRIPTIONS = {
  orders: 'Positions, pending orders and copy activity — organized by trade.',
  raw: 'Inspect recorded requests and replies.',
  verified: 'What the broker read back for each copied trade, on its own clock, beside what was sent on this one.',
  paper: 'Requests composed in paper mode. Never sent to a broker; never verifiable.',
}
const state = ref({ accounts: [], running: false, connection: 'disconnected', orders: [], orders_at: null })
const selected = ref('')
const events = ref([])
const nativeEvents = ref([])
const mappings = ref([])
const brokerProfiles = ref(null)
// The three ledger sections. Absent until the server pushes them; CopyControls renders
// the safe reading (paper, all off) from null, and both tables render an empty state.
const copyControls = ref(null)
const verifiedTrades = ref([])
const paperSends = ref([])
const copyMode = computed(() => copyControls.value?.mode === 'live' ? 'live' : 'paper')
const requestedPage = new URLSearchParams(window.location.search).get('page')
const page = ref(PAGES.includes(requestedPage) ? requestedPage : 'bridge')
const busy = ref(false)
const activeAction = ref('')
const error = ref('')
const signalsExpanded = ref(false)
const streamStatus = ref('connecting')
let disposed = false, stopStream, brokerTimer

// Broker orders and positions live upstream, so they are the only state the server
// cannot observe and push. Refresh them solely while something is pending or open;
// the timer re-arms itself only while that stays true and stops on its own otherwise.
function brokerWorkOutstanding() {
  return state.value.connection === 'connected'
    && ((state.value.orders?.length || 0) + (state.value.positions?.length || 0)) > 0
}
function scheduleBrokerRefresh() {
  if (disposed || brokerTimer || !brokerWorkOutstanding()) return
  brokerTimer = setTimeout(runBrokerRefresh, 5000)
}
async function runBrokerRefresh() {
  brokerTimer = undefined
  if (disposed) return
  if (!busy.value && brokerWorkOutstanding()) {
    try { await readBroker() } catch (err) { error.value = err.message }
  }
  scheduleBrokerRefresh()
}
async function readBroker() {
  state.value = await request('orders/refresh', { account_id: selected.value })
  state.value = await request('positions/refresh', { account_id: selected.value })
}
// Explicit refresh from the Orders workspace or on opening it.
async function refreshBroker() {
  busy.value = true
  activeAction.value = 'orders/refresh'
  error.value = ''
  try { await readBroker() } catch (err) { error.value = err.message }
  finally { busy.value = false; activeAction.value = ''; scheduleBrokerRefresh() }
}

// Sections keep their object identity across merges, so an unchanged one is skipped.
const applied = {}
function changed(snapshot, key) {
  if (!snapshot[key] || applied[key] === snapshot[key]) return false
  applied[key] = snapshot[key]
  return true
}
function apply(snapshot) {
  if (disposed) return
  const statusChanged = changed(snapshot, 'status')
  if (statusChanged) {
    const current = snapshot.status
    const accountChanged = current.account_id !== state.value.account_id
    state.value = current
    if (accountChanged || !selected.value || !current.accounts.some(account => account.id === selected.value)) selected.value = current.account_id
    scheduleBrokerRefresh()
  }
  // Account-scoped feeds are filtered against the account in view, so re-derive them
  // when either the feed or the account changed.
  if (changed(snapshot, 'events') || (statusChanged && applied.events)) {
    events.value = applied.events.account_id === state.value.account_id ? applied.events.events ?? [] : []
  }
  if (changed(snapshot, 'capture_events')) nativeEvents.value = applied.capture_events.events ?? []
  if (changed(snapshot, 'mappings') || (statusChanged && applied.mappings)) {
    mappings.value = applied.mappings.account_id === state.value.account_id ? applied.mappings.mappings ?? [] : []
  }
  if (changed(snapshot, 'broker_profiles')) brokerProfiles.value = applied.broker_profiles
  if (changed(snapshot, 'copy_controls')) copyControls.value = applied.copy_controls
  if (changed(snapshot, 'verified_trades') || (statusChanged && applied.verified_trades)) {
    verifiedTrades.value = applied.verified_trades.account_id === state.value.account_id ? applied.verified_trades.rows ?? [] : []
  }
  if (changed(snapshot, 'paper_sends') || (statusChanged && applied.paper_sends)) {
    paperSends.value = applied.paper_sends.account_id === state.value.account_id ? applied.paper_sends.rows ?? [] : []
  }
}
async function openPage(value) {
  page.value = value
  if (value === 'orders' && state.value.connection === 'connected' && !busy.value) await refreshBroker()
}
async function action(name) {
  busy.value = true
  activeAction.value = name
  error.value = ''
  try {
    state.value = await request(name, { account_id: selected.value })
  } catch (err) { error.value = err.message }
  finally { busy.value = false; activeAction.value = ''; scheduleBrokerRefresh() }
}
onMounted(() => {
  // The server pushes status, events, capture events, mappings, broker profiles,
  // copy controls, verified trades and paper sends; nothing here polls for them.
  stopStream = followDashboard(apply, value => { streamStatus.value = value })
})
onUnmounted(() => { disposed = true; stopStream?.(); clearTimeout(brokerTimer) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">H</span> HCAMM</div>
      <div class="nav-label">WORKSPACE</div>
      <button class="nav-item" :class="{ active: page === 'bridge' }" @click="openPage('bridge')">Trading bridge</button>
      <button class="nav-item" :class="{ active: page === 'orders' }" @click="openPage('orders')">Orders</button>
      <button class="nav-item" :class="{ active: page === 'verified' }" @click="openPage('verified')">Verified trades</button>
      <button class="nav-item" :class="{ active: page === 'paper' }" @click="openPage('paper')">Paper trades</button>
      <button class="nav-item" :class="{ active: page === 'brokers' }" @click="openPage('brokers')">Broker accounts</button>
      <button class="nav-item" :class="{ active: page === 'logging' }" @click="openPage('logging')">Event logging</button>
      <button class="nav-item" :class="{ active: page === 'raw' }" @click="openPage('raw')">Raw events</button>
      <button class="nav-item" :class="{ active: page === 'settings' }" @click="openPage('settings')">Copy settings</button>
      <div class="sidebar-bottom"><span class="small-dot"></span> Local application<br><small>Match-Trader integration</small></div>
    </aside>
    <main>
      <header>
        <div><div class="eyebrow">QUANTOWER → MATCH-TRADER</div><h1>{{ TITLES[page] || 'Trading bridge' }}</h1>
          <p>{{ DESCRIPTIONS[page] || 'Choose your account. Control the connection. Follow every incoming event.' }}</p></div>
        <div class="mode-pill" :class="{ 'copy-live': copyMode === 'live' }"><span class="small-dot"></span>TradingBox {{ state.tradingbox_forwarding?.live ? 'LIVE' : state.tradingbox_forwarding?.enabled ? 'preview' : 'off' }} · Copy {{ copyMode === 'live' ? 'LIVE' : 'paper' }}</div>
      </header>
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
      <AccountControls v-if="page === 'bridge'" :state="state" :selected="selected" :busy="busy"
        @start="action('start')" @stop="action('stop')" />
      <section v-if="OVERVIEW_PAGES.includes(page)" class="status-grid" aria-label="Service status">
        <article class="card metric"><span class="metric-label">BRIDGE</span>
          <strong><span class="status-dot" :class="{ on: state.running }"></span>{{ state.running ? 'Observing' : 'Stopped' }}</strong>
          <p>{{ state.capture_message || 'Loading local service…' }}</p></article>
        <article class="card metric"><span class="metric-label">BROKER CONNECTION</span>
          <strong class="capitalize">{{ state.connection }}</strong><p>{{ state.connection_message }}</p></article>
        <article class="card metric"><span class="metric-label">ACCOUNT IN VIEW</span>
          <strong>{{ state.account_id || '—' }}</strong><p>Orders sent by this bridge: {{ state.broker_orders_sent ?? 0 }}</p></article>
      </section>
      <TokenSession v-if="OVERVIEW_PAGES.includes(page)" :state="state" :busy="busy" :refreshing="activeAction === 'token/refresh'"
        @refresh="action('token/refresh')" />
      <template v-if="page === 'bridge'">
      <NativeEvents :events="nativeEvents" :legacy-events="events" :stream-status="streamStatus" :state="state" :busy="busy" />
      </template>
      <template v-else-if="page === 'verified'">
        <CopyControls :pushed="copyControls" />
        <VerifiedTrades :rows="verifiedTrades" :mode="copyMode" />
      </template>
      <PaperTrades v-else-if="page === 'paper'" :rows="paperSends" :mode="copyMode" />
      <BrokerProfiles v-else-if="page === 'brokers'" :pushed="brokerProfiles" />
      <LoggingEvents v-else-if="page === 'logging'" />
      <template v-else-if="page === 'raw'">
        <RawEvents :state="state" />
        <details class="card" style="margin-top:20px;padding:20px" @toggle="signalsExpanded = $event.target.open">
          <summary style="cursor:pointer">Recent signal activity</summary>
          <SignalActivity v-if="signalsExpanded" />
        </details>
      </template>
      <template v-else-if="page === 'settings'">
        <CopyControls :pushed="copyControls" />
        <CopySettings :state="state" />
        <details class="card" style="margin-top:20px;padding:20px"><summary>Strategy signal mapping</summary><SignalCopySettings :state="state" /></details>
      </template>
      <template v-else>
      <OrdersWorkspace :state="state" :mappings="mappings" :busy="busy" @refresh="refreshBroker" />
      </template>
      <footer>Version {{ state.version || '—' }} · Native event receipt and broker acceptance are separate stages. CSV observations are never copied.</footer>
    </main>
  </div>
</template>
