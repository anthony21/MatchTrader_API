<script setup>
defineProps({ orders: Array, updatedAt: String, connected: Boolean, busy: Boolean })
defineEmits(['refresh'])
</script>

<template>
  <section class="card broker-panel">
    <div class="section-heading">
      <div><h2>Broker pending orders</h2><p>Read from the selected account. These are separate from the incoming feed.</p></div>
      <button class="secondary" :disabled="!connected || busy" @click="$emit('refresh')">Refresh orders</button>
    </div>
    <p v-if="!updatedAt" class="quiet">No broker snapshot loaded. Connect the account, then refresh orders.</p>
    <template v-else>
      <p class="quiet">Snapshot: {{ updatedAt }}{{ connected ? '' : ' · disconnected; snapshot may be stale' }}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Broker ID</th><th>Instrument</th><th>Side / type</th><th>Lots</th><th>Entry</th><th>SL</th><th>TP</th></tr></thead>
        <tbody><tr v-for="order in orders" :key="order.id">
          <td>{{ order.id }}</td><td>{{ order.symbol }}</td><td>{{ order.side }} / {{ order.type }}</td>
          <td>{{ order.volume }}</td><td>{{ order.activationPrice }}</td><td>{{ order.stopLoss ?? '—' }}</td>
          <td>{{ order.takeProfit ?? '—' }}</td>
        </tr><tr v-if="!orders.length"><td colspan="7" class="quiet">No active pending orders in this snapshot.</td></tr></tbody>
      </table></div>
    </template>
  </section>
</template>
