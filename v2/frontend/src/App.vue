<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request } from './api.js'
import AccountControls from './components/AccountControls.vue'
import EventTable from './components/EventTable.vue'
import BrokerOrders from './components/BrokerOrders.vue'
import TokenSession from './components/TokenSession.vue'

const state = ref({ accounts: [], running: false, connection: 'disconnected', orders: [], orders_at: null })
const selected = ref('')
const events = ref([])
const busy = ref(false)
const activeAction = ref('')
const error = ref('')
const filter = ref('')
let timer, disposed = false
const visible = computed(() => events.value.filter(event =>
  `${event.symbol} ${event.side} ${event.action} ${event.status} ${event.source_order_id}`
    .toLowerCase().includes(filter.value.toLowerCase())))
const observations = computed(() => events.value.filter(event => event.status === 'observation').length)
const previews = computed(() => events.value.filter(event => event.status === 'preview').length)
const held = computed(() => events.value.filter(event => event.status === 'held').length)

async function refresh() {
  const current = await request('status')
  state.value = current
  if (!selected.value || !current.accounts.some(account => account.id === selected.value)) selected.value = current.account_id
  const feed = await request('events')
  events.value = feed.account_id === current.account_id ? feed.events : []
}
async function poll() {
  if (!busy.value) {
    try { await refresh(); error.value = '' } catch (err) { error.value = err.message }
  }
  if (!disposed) timer = setTimeout(poll, 1500)
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
onMounted(poll)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">H</span> HCAMM</div>
      <div class="nav-label">WORKSPACE</div>
      <div class="nav-item active"><span aria-hidden="true">▤</span> Trading bridge</div>
      <div class="sidebar-bottom"><span class="small-dot"></span> Local application<br><small>Match-Trader integration</small></div>
    </aside>
    <main>
      <header>
        <div><div class="eyebrow">QUANTOWER → MATCH-TRADER</div><h1>Trading bridge</h1>
          <p>Choose your account. Control the connection. Follow every incoming event.</p></div>
        <div class="mode-pill"><span class="small-dot"></span> Shadow mode</div>
      </header>
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
      <AccountControls :state="state" v-model:selected="selected" :busy="busy"
        @connect="action('connect')" @start="action('start')" @stop="action('stop')" />
      <section class="status-grid" aria-label="Service status">
        <article class="card metric"><span class="metric-label">BRIDGE</span>
          <strong><span class="status-dot" :class="{ on: state.running }"></span>{{ state.running ? 'Observing' : 'Stopped' }}</strong>
          <p>{{ state.capture_message || 'Loading local service…' }}</p></article>
        <article class="card metric"><span class="metric-label">BROKER CONNECTION</span>
          <strong class="capitalize">{{ state.connection }}</strong><p>{{ state.connection_message }}</p></article>
        <article class="card metric"><span class="metric-label">ACCOUNT IN VIEW</span>
          <strong>{{ state.account_id || '—' }}</strong><p>Orders sent by this bridge: {{ state.broker_orders_sent ?? 0 }}</p></article>
      </section>
      <TokenSession :state="state" :busy="busy" :refreshing="activeAction === 'token/refresh'"
        @refresh="action('token/refresh')" />
      <section class="card feed-panel">
        <div class="section-heading">
          <div><h2>Incoming activity <span class="count">{{ events.length }}</span></h2>
            <p>Latest 200 events for the account in view · refreshes every 1.5 seconds</p></div>
          <input aria-label="Filter events" v-model="filter" placeholder="Filter instrument, event, status…" />
        </div>
        <div class="feed-legend"><span>{{ observations }} observations</span><span>{{ previews }} request previews</span>
          <span>{{ held }} held</span><span class="legend-note">Preview and observation do not mean broker acceptance.</span></div>
        <EventTable :events="visible" />
      </section>
      <BrokerOrders :orders="state.orders" :updated-at="state.orders_at" :connected="state.connection === 'connected'"
        :busy="busy" @refresh="action('orders/refresh')" />
      <footer>Shadow mode records and validates events without placing trades. R01 ledger observations have no lot size.
        Broker credentials stay in your local .env file.</footer>
    </main>
  </div>
</template>
