<script setup>
import { localTime } from '../time.js'
defineProps({ orders: Array, updatedAt: String, connected: Boolean, busy: Boolean })
defineEmits(['refresh'])
</script>

<template>
  <section class="card broker-panel">
    <div class="section-heading">
      <div><h2>Broker pending orders</h2><p>Pending orders have no profit or loss until filled. See open positions below for P/L.</p></div>
      <button class="secondary" :disabled="!connected || busy" @click="$emit('refresh')">Refresh orders</button>
    </div>
    <p v-if="!updatedAt" class="quiet">No broker snapshot loaded. Connect the account, then refresh orders.</p>
    <template v-else>
      <p class="quiet">Snapshot: {{ localTime(updatedAt) }} · local time{{ connected ? '' : ' · disconnected; snapshot may be stale' }}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Broker ID</th><th>Instrument</th><th>Side / type</th><th>Lots</th><th>Entry</th><th>SL</th><th>TP</th><th>Profit / loss</th><th>Created · local</th></tr></thead>
        <tbody><tr v-for="order in orders" :key="order.id">
          <td>{{ order.id }}</td><td>{{ order.symbol }}</td><td>{{ order.side }} / {{ order.type }}</td>
          <td>{{ order.volume }}</td><td>{{ order.activationPrice }}</td><td>{{ order.stopLoss ?? '—' }}</td>
          <td>{{ order.takeProfit ?? '—' }}</td>
          <td>— (pending)</td><td>{{ localTime(order.creationTimeIso || order.creationTime) }}</td>
        </tr><tr v-if="!orders.length"><td colspan="9" class="quiet">No active pending orders in this snapshot.</td></tr></tbody>
      </table></div>
    </template>
  </section>
</template>
