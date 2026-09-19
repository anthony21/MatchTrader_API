<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { price, signalRows, timestamp } from './signalRows.js'
import { columnValue, displayValue, loadColumns, saveColumns, SIGNAL_COLUMNS } from './signalColumns.js'
import SignalColumnPicker from './SignalColumnPicker.vue'
const props = defineProps({ port: { type: Number, default: 8766 } })
const origin = location.origin
const events = ref([]), lane = ref(''), machine = ref(''), kind = ref(''), search = ref(''), status = ref('Connecting')
const expanded = ref(null)
const selectedColumns = ref(loadColumns())
const columns = computed(() => SIGNAL_COLUMNS.filter(column => selectedColumns.value.includes(column.key)))
watch(selectedColumns, saveColumns, { deep: true })
const numericColumn = key => ['entry', 'stopLoss', 'takeProfit', 'volume', 'stamp', 'sequence', 'l2DbandDigit', 'l2BirthRank'].includes(key)
let socket, retry, disposed = false
const base = computed(() => `ws://${location.hostname}:${props.port}`)
const rows = computed(() => signalRows(events.value))
const lanes = computed(() => [...new Set(['R01', 'P01', 'P02', 'X17', ...rows.value.map(e => e.lane)])])
const laneRows = computed(() => rows.value.filter(e => !lane.value || e.lane === lane.value))
const machines = computed(() => [...new Set(laneRows.value.map(e => e.machineId).filter(Boolean))].sort())
const kinds = computed(() => [...new Set(laneRows.value.map(e => e.kind).filter(Boolean))].sort())
const visible = computed(() => laneRows.value.filter(e => (!machine.value || e.machineId === machine.value) &&
  (!kind.value || e.kind === kind.value) && e.searchable.includes(search.value.toLowerCase())))
function selectLane(value) { lane.value = value; machine.value = ''; kind.value = ''; expanded.value = null }
function toggle(row) { expanded.value = expanded.value === row.id ? null : row.id }
function connect() {
  clearTimeout(retry)
  if (socket) { socket.onclose = null; socket.close() }
  status.value = 'Connecting'
  const current = new WebSocket(`${base.value}/events`)
  socket = current
  current.onopen = () => { if (socket === current) status.value = 'Live' }
  current.onmessage = ({ data }) => {
    if (socket !== current || disposed) return
    try {
      const message = JSON.parse(data)
      const incoming = message.type === 'snapshot' ? message.events : message.type === 'signal' ? [message.event] : []
      const rows = message.type === 'snapshot' ? incoming : [...events.value, ...incoming]
      events.value = [...new Map(rows.map(e => [e.id, e])).values()].sort((a, b) => b.id - a.id).slice(0, 200)
    } catch { status.value = 'Unreadable update' }
  }
  current.onerror = () => { if (socket === current) status.value = 'Reconnecting' }
  current.onclose = () => {
    if (disposed || socket !== current) return
    status.value = 'Reconnecting'
    retry = setTimeout(connect, 1000)
  }
}
onMounted(connect)
watch(() => props.port, connect)
onUnmounted(() => { disposed = true; clearTimeout(retry); if (socket) { socket.onclose = null; socket.close() } })
</script>

<template>
  <section class="card live-signals" aria-label="Live strategy signals">
    <div class="section-heading">
      <div><h2>Live signal stream <span class="count">{{ visible.length }}</span></h2>
        <p>Strategy events and trade levels as they arrive.</p></div>
      <span class="stream-state" :class="{ live: status === 'Live' }" role="status"><span aria-hidden="true">●</span> {{ status }}</span>
    </div>
    <div class="lane-filters" role="group" aria-label="Filter by sender">
      <button class="lane-filter" :class="{ selected: !lane }" :aria-pressed="!lane" @click="selectLane('')">All <span>{{ rows.length }}</span></button>
      <button v-for="value in lanes" :key="value" class="lane-filter" :class="{ selected: lane === value }"
        :aria-pressed="lane === value" @click="selectLane(value)">{{ value }} <span>{{ rows.filter(e => e.lane === value).length }}</span></button>
    </div>
    <div class="signal-filters">
      <label>Machine ID<select v-model="machine" aria-label="Machine ID"><option value="">All machines</option><option v-for="value in machines" :key="value">{{ value }}</option></select></label>
      <label>Event type<select v-model="kind" aria-label="Event type"><option value="">All event types</option><option v-for="value in kinds" :key="value">{{ value }}</option></select></label>
      <label class="search-field">Search<input v-model="search" aria-label="Search signals" placeholder="Symbol, machine or signal content" /></label>
    </div>
    <div class="table-wrap" tabindex="0" role="region" aria-label="Incoming signal table">
      <table>
        <thead><tr>
          <th scope="col" class="first-column" :class="{ number: numericColumn(columns[0].key) }">
            <SignalColumnPicker v-model="selectedColumns" />{{ columns[0].label }}
          </th>
          <th v-for="column in columns.slice(1)" :key="column.key" scope="col" :class="{ number: numericColumn(column.key) }">{{ column.label }}</th>
        </tr></thead>
        <tbody>
          <template v-for="row in visible" :key="row.id">
            <tr class="signal-row" :data-signal-id="row.id">
              <td v-for="column in columns" :key="column.key" :class="{ number: numericColumn(column.key), 'signal-time': column.key === 'timestampUtc' }"
                :title="displayValue(columnValue(row, column.key))">
                <template v-if="column.key === 'lane'"><button class="payload-toggle" :aria-expanded="expanded === row.id" :aria-controls="`payload-${row.id}`"
                :aria-label="`${expanded === row.id ? 'Hide' : 'Show'} ${row.lane} ${row.kind} payload`" @click="toggle(row)">
                <span class="lane-name">{{ row.lane }}</span><span class="expand-icon" aria-hidden="true">{{ expanded === row.id ? '−' : '+' }}</span></button>
                <small class="subtext event-kind">{{ row.kind || 'signal' }}</small></template>
                <template v-else-if="column.key === 'machineId'"><strong class="machine-name">{{ row.machineId || '—' }}</strong><small class="subtext">{{ row.symbol }}</small></template>
                <template v-else-if="column.key === 'side'"><span v-if="row.side" class="side-pill" :class="row.side.toLowerCase()">{{ row.side }}</span><span v-else class="muted">—</span></template>
                <template v-else-if="['entry', 'stopLoss', 'takeProfit'].includes(column.key)">{{ price(columnValue(row, column.key)) }}</template>
                <template v-else-if="column.key === 'ladderGrade'"><span v-if="row.ladderGrade" class="grade-pill" :class="row.ladderGrade.toLowerCase()">{{ row.ladderGrade }}</span><span v-else class="muted">—</span></template>
                <template v-else-if="column.key === 'timestampUtc'">{{ timestamp(row.timestamp) }}</template>
                <span v-else class="schema-value">{{ displayValue(columnValue(row, column.key)) }}</span>
              </td>
            </tr>
            <tr v-if="expanded === row.id" :id="`payload-${row.id}`" class="payload-row"><td :colspan="columns.length">
              <div class="payload-heading"><strong>{{ row.source }} · {{ row.kind }}</strong><span>Received {{ timestamp(row.receivedAt) }} UTC</span></div>
              <p v-if="row.issues.length" class="parse-issues">{{ row.issues.map(issue => `${issue.field || issue.stage}: ${issue.message}`).join(' · ') }}</p>
              <pre>{{ row.payload === null || row.payload === undefined ? row.raw : JSON.stringify(row.payload, null, 2) }}</pre>
              <details><summary>Original message</summary><pre>{{ row.raw }}</pre></details>
            </td></tr>
          </template>
          <tr v-if="!visible.length"><td :colspan="columns.length" class="signal-empty">{{ events.length ? 'No signals match these filters.' : 'Waiting for signals.' }}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="signal-footer"><span>{{ rows.length }} events from the latest {{ events.length }} messages · Live updates</span>
      <details class="signal-endpoints"><summary>Sender endpoints</summary><div><span>WebSocket: <code>{{ base }}/signals</code></span>
        <span>HTTP: <code>{{ origin }}/signals</code></span></div></details>
    </div>
  </section>
</template>

<style scoped>
.live-signals { overflow: hidden; }
.stream-state { padding: 8px 14px; border-radius: 20px; background: #f1f4f8; color: #7b899b; font-size: 12px; white-space: nowrap; }
.stream-state.live { background: #e5f5ed; color: #197b56; }
.lane-filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 24px 20px; }
.lane-filter { display: flex; align-items: center; gap: 10px; background: #f6f8fb; border-color: #e3e9f0; border-radius: 22px; color: #53667e; min-height: 36px; padding: 8px 15px; font-size: 12px; }
.lane-filter span { margin: 0; padding: 2px 6px; border-radius: 10px; background: #e8edf3; font-size: 10px; }
.lane-filter.selected { background: #176e5c; border-color: #176e5c; color: white; }
.lane-filter.selected span { background: #ffffff24; color: white; }
.signal-filters { display: flex; gap: 14px; padding: 0 24px 22px; flex-wrap: wrap; }
.signal-filters label { display: grid; gap: 7px; font-size: 11px; color: #728198; flex: 1; min-width: 150px; }
.signal-filters .search-field { flex: 1.5; }
.signal-filters input, .signal-filters select { width: 100%; }
.schema-value { display: inline-block; max-width: 300px; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
.table-wrap { max-height: 620px; }
thead th { position: sticky; top: 0; z-index: 2; }
thead th.first-column { left: 0; z-index: 3; }
.signal-row td:first-child { position: sticky; left: 0; background: white; z-index: 1; }
th, td { padding: 13px 14px; }
.payload-toggle { display: flex; align-items: center; gap: 10px; min-height: 28px; background: transparent; border: 0; padding: 0; color: #225b62; }
.payload-toggle span { margin: 0; font-size: 12px; }
.payload-toggle .expand-icon { color: #8a9aaa; }
.event-kind { margin-top: 0; }
.machine-name { font-size: 12px; font-weight: 600; }
.side-pill, .grade-pill { display: inline-block; padding: 5px 8px; border-radius: 5px; font-size: 10px; font-weight: 650; background: #edf1f7; color: #52667e; }
.side-pill.buy { background: #e5f5ed; color: #197454; }
.side-pill.sell { background: #fceeee; color: #ae4d4d; }
.grade-pill.prime { background: #edf0ff; color: #6153a5; }
.grade-pill.strong { background: #eaf3ff; color: #386b9d; }
.signal-time { font-size: 11px; font-variant-numeric: tabular-nums; color: #687b92; }
.muted { color: #9aa6b5; }
.payload-row td { background: #f8fafc; white-space: normal; padding: 18px 24px; }
.payload-heading { display: flex; justify-content: space-between; gap: 10px; color: #5d7188; font-size: 11px; flex-wrap: wrap; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 300px; overflow: auto; background: #eef3f7; padding: 14px; border-radius: 8px; font-size: 11px; }
summary { cursor: pointer; color: #237461; }
.parse-issues { color: #976324; font-size: 12px; }
.signal-empty { text-align: center; padding: 42px 20px; white-space: normal; color: #718197; }
.signal-footer { display: flex; justify-content: space-between; gap: 18px; flex-wrap: wrap; padding: 17px 24px; font-size: 11px; color: #7d8ba0; border-top: 1px solid #edf1f6; }
.signal-endpoints div { display: grid; gap: 9px; padding-top: 12px; overflow-wrap: anywhere; }
.signal-endpoints code { color: #234b66; }
@media (max-width: 720px) { .lane-filters, .signal-filters { padding-inline: 16px; } .section-heading { padding-inline: 16px; } }
</style>
