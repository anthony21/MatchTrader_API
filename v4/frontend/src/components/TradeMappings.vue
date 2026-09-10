<script setup>
import { localTime } from '../time.js'
defineProps({ mappings: { type: Array, default: () => [] } })
const ids = (trade, side, kind) => trade.links.filter(l => l.side === side && l.kind === kind).map(l => l.native_id).join(', ') || '—'
</script>

<template>
  <section class="card broker-panel" aria-label="Trade mappings">
    <div class="section-heading"><div><h2>Trade mappings</h2>
      <p>Source and broker identities, partial fills and position contributions. Missing evidence stays unconfirmed.</p></div></div>
    <p v-if="!mappings.length" class="quiet">No captured trade mappings for this account yet.</p>
    <article v-for="trade in mappings" :key="trade.trade_id" class="mapping-record">
      <h3>{{ trade.trade_id }} · {{ trade.mapping_status }} · {{ trade.state }}</h3>
      <p>{{ trade.broker || 'Broker not configured' }} / {{ trade.account_id || 'Destination not assigned' }} · {{ localTime(trade.updated_at) }}</p>
      <p>Quantower source: {{ trade.source_scope?.join(' / ') || '—' }}</p>
      <p v-for="reason in trade.reasons" :key="reason" class="quiet">{{ reason }}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Quantower orders</th><th>Quantower positions</th><th>Broker orders</th><th>Broker positions</th></tr></thead>
        <tbody><tr><td>{{ ids(trade, 'source', 'order') }}</td><td>{{ ids(trade, 'source', 'position') }}</td>
          <td>{{ ids(trade, 'destination', 'order') }}</td><td>{{ ids(trade, 'destination', 'position') }}</td></tr></tbody>
      </table></div>
      <details><summary>Quantities, fills and action history</summary>
        <p>Source and destination quantities use different units. Recorded fills may be incomplete; position snapshots are not fill confirmations.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Side</th><th>Units</th><th>Requested</th><th>Reported filled</th><th>Reported remaining</th><th>Partial</th></tr></thead>
          <tbody><tr v-for="q in trade.quantities" :key="q.side + q.scope"><td>{{ q.side }}</td><td>{{ q.unit }}</td>
            <td>{{ q.requested ?? '—' }}</td><td>{{ q.cumulative ?? '—' }}</td><td>{{ q.remaining ?? '—' }}</td><td>{{ q.partial ? 'Partial fill' : '—' }}</td></tr></tbody>
        </table></div>
        <div v-for="link in trade.links.filter(l => l.kind === 'position')" :key="link.side + link.scope + link.native_id">
          <p>{{ link.side }} position {{ link.native_id }} · {{ link.scope.join(' / ') }}
            · {{ link.contributors.length > 1 ? 'Merged position' : 'Position relationship' }}</p>
          <p>Contributing trade IDs: {{ link.contributors.join(', ') }}. Recorded opening quantity: {{ link.observed_open_contribution }};
            recorded closing quantity: {{ link.observed_close_contribution }}. Allocation: {{ link.allocation_confirmed ? 'confirmed' : 'unconfirmed' }}.</p>
          <p v-if="link.position_snapshot">Latest whole-position volume: {{ link.position_snapshot.volume }} · {{ localTime(link.position_snapshot.updated_at) }}</p>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th>Side</th><th>Execution ID</th><th>Order / position</th><th>Effect</th><th>Quantity</th><th>Price</th><th>Time · local</th></tr></thead>
          <tbody><tr v-for="fill in trade.fills" :key="fill.side + fill.scope + fill.execution_id"><td>{{ fill.side }}</td><td>{{ fill.execution_id }}</td>
            <td>{{ fill.order_id || '—' }} / {{ fill.position_id || '—' }}</td><td>{{ fill.effect }}</td><td>{{ fill.quantity }}</td><td>{{ fill.price }}</td><td>{{ localTime(fill.emitted_at) }}</td></tr>
            <tr v-if="!trade.fills.length"><td colspan="7">No executions with stable fill IDs recorded.</td></tr></tbody>
        </table></div>
        <div v-for="action in trade.actions" :key="action.action_key">
          <p>{{ action.action }} · {{ action.outcome }} · request {{ action.request_id }} · {{ localTime(action.updated_at) }}</p>
          <p>Broker order {{ action.broker_order_id || '—' }} / position {{ action.broker_position_id || '—' }}</p>
          <pre>{{ JSON.stringify(action.request, null, 2) }}</pre>
        </div>
      </details>
    </article>
  </section>
</template>
