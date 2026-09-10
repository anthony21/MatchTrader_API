<script setup>
import { localTime } from '../time.js'
defineProps({ positions: Array, updatedAt: String, connected: Boolean, busy: Boolean })
defineEmits(['refresh'])
</script>

<template>
  <section class="card broker-panel">
    <div class="section-heading">
      <div><h2>Open positions <span class="count">{{ positions?.length ?? 0 }}</span></h2>
        <p>Current broker P/L for filled trades. Net profit is shown when provided; otherwise profit is shown.</p></div>
      <button class="secondary" :disabled="!connected || busy" @click="$emit('refresh')">Refresh positions</button>
    </div>
    <p class="quiet">{{ updatedAt ? `Snapshot: ${localTime(updatedAt)} · local time` : 'No open-position snapshot loaded.' }}
      {{ !connected && updatedAt ? ' · disconnected; snapshot may be stale' : '' }}</p>
    <div v-if="updatedAt" class="table-wrap"><table>
      <thead><tr><th>Position ID</th><th>Instrument</th><th>Side</th><th>Lots</th><th>Entry</th><th>SL</th><th>TP</th><th>Profit / loss</th><th>Opened · local</th></tr></thead>
      <tbody><tr v-for="position in positions" :key="position.id">
        <td>{{ position.id }}</td><td>{{ position.symbol }}</td><td>{{ position.side }}</td>
        <td>{{ position.volume }}</td><td>{{ position.openPrice }}</td><td>{{ position.stopLoss ?? '—' }}</td>
        <td>{{ position.takeProfit ?? '—' }}</td><td>{{ position.netProfit ?? position.profit ?? '—' }}</td>
        <td>{{ localTime(position.openTime, position.openTimeMillis) }}</td>
      </tr><tr v-if="!positions?.length"><td colspan="9">No open positions in this snapshot.</td></tr></tbody>
    </table></div>
  </section>
</template>
