<script setup>
defineProps({ events: Array, state: Object, busy: Boolean })
defineEmits(['toggle'])
</script>

<template>
  <section class="card broker-panel">
    <div class="section-heading">
      <div><h2>Quantower native activity <span class="count">{{ events.length }}</span></h2>
        <p>Direct C# events · source accounts shown below · copying {{ state.copying ? 'enabled' : 'off' }}</p></div>
      <button class="secondary" :disabled="busy || (!state.copying && (!state.route_configured || !state.running || state.connection !== 'connected'))"
        @click="$emit('toggle')">{{ state.copying ? 'Stop copying' : 'Enable copying' }}</button>
    </div>
    <p v-if="!state.route_configured" class="quiet">Copying needs a source account, symbol mapping and quantity rule.</p>
    <p v-if="state.csv_export_error" class="quiet" role="alert">CSV update failed. Close the CSV in Excel; the persistent trade journal is intact.</p>
    <p v-if="state.reconciliation_message" class="quiet" role="alert">{{ state.reconciliation_message }}</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Trade ID</th><th>Source / account</th><th>Event</th><th>Symbol / side</th><th>Quantity</th><th>Price / SL / TP</th><th>Result</th></tr></thead>
      <tbody><tr v-for="event in events" :key="event.id" :title="event.reason">
        <td>{{ event.trade_id ?? 'Unlinked' }}<small class="subtext">QT {{ event.order_id || event.position_id || event.request_id }}</small></td>
        <td>{{ event.source }} / {{ event.account_id }}<small class="subtext">{{ event.connection_id }}</small></td>
        <td>{{ event.kind }} / {{ event.action }}<small class="subtext">{{ event.emitted_at }}</small></td>
        <td>{{ event.symbol }} / {{ event.side }}</td><td>{{ event.quantity }}</td>
        <td>{{ event.price }} / {{ event.sl }} / {{ event.tp }}</td><td>{{ event.decision }}<small class="subtext">{{ event.reason }}</small></td>
      </tr><tr v-if="!events.length"><td colspan="7">Waiting for the Quantower capture extension.</td></tr></tbody>
    </table></div>
  </section>
</template>
