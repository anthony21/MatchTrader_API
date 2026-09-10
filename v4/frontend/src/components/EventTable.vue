<script setup>
import { localTime as timestamp } from '../time.js'
defineProps({ events: Array })
const display = value => value === null || value === undefined || value === '' ? '—' : value
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Source time · local</th><th>Bridge receipt · local</th><th>Instrument / side</th><th>Event / type</th>
        <th class="number">Lots</th><th class="number">Entry</th><th class="number">Stop loss</th>
        <th class="number">Take profit</th><th>Status</th><th>Broker ID</th>
      </tr></thead>
      <tbody>
        <tr v-for="event in events" :key="event.id" :title="`${event.source_order_id || ''} · ${event.reason}`">
          <td class="time">{{ timestamp(event.emitted_at) }}</td>
          <td class="time">{{ timestamp(event.received_at) }}</td>
          <td><strong>{{ event.symbol }}</strong><span class="subtext">{{ event.side }}</span></td>
          <td>{{ event.action }}<span class="subtext">{{ display(event.order_type) }}</span></td>
          <td class="number">{{ display(event.volume) }}</td><td class="number">{{ display(event.price) }}</td>
          <td class="number">{{ display(event.sl) }}</td><td class="number">{{ display(event.tp) }}</td>
          <td><span class="badge" :class="event.status">{{ event.status }}</span></td>
          <td>{{ display(event.broker_order_id) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-if="!events.length" class="empty">
    <span class="empty-icon" aria-hidden="true">↳</span>
    <strong>Waiting for new events</strong>
    <span>Start the bridge to observe fresh R01 activity. Historical ledger rows are not replayed.</span>
  </div>
</template>
