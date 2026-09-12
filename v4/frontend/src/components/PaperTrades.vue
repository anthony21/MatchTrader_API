<script setup>
import { localTime } from '../time.js'
// Paper sends are requests the copier composed while in paper mode. None reached a
// broker, so none can be verified, and they never appear in the verified ledger.
defineProps({ rows: { type: Array, default: () => [] }, mode: { type: String, default: 'paper' } })
</script>

<template>
  <section class="card broker-panel paper-trades" aria-label="Paper trades">
    <div class="section-heading"><div><h2>Paper trades</h2>
      <p>Requests composed in paper mode and recorded locally. Nothing on this page was sent to a broker.</p></div>
      <span class="badge" :class="mode === 'live' ? 'mode-live' : 'mode-paper'">Copy mode now: {{ mode === 'live' ? 'LIVE' : 'paper' }}</span></div>
    <p class="notice" role="note">These trades were never sent to a broker and can never be verified. They are kept apart from the verified ledger on purpose.</p>
    <p v-if="!rows.length" class="quiet">No paper sends recorded for this account.</p>
    <div v-else class="table-wrap"><table>
      <thead><tr><th>Source</th><th>Symbol</th><th>Side</th><th>Lots</th><th>Request that would have been sent</th><th>Verdict</th><th>Reason</th><th>Decided at<span class="clock">local clock</span></th></tr></thead>
      <tbody><tr v-for="row in rows" :key="row.trade_id" class="paper-row" :data-trade="row.trade_id">
        <td>{{ row.source || '—' }}<span class="subtext">{{ row.trade_id }}</span></td>
        <td>{{ row.symbol || '—' }}</td><td>{{ row.side || '—' }}</td><td class="number">{{ row.lots ?? '—' }}</td>
        <td class="request"><pre>{{ row.request == null ? 'No request recorded' : JSON.stringify(row.request, null, 2) }}</pre></td>
        <td><span class="badge">{{ row.verdict || 'verdict not recorded' }}</span></td>
        <td class="reason">{{ row.reason || 'no reason supplied' }}</td>
        <td class="time">{{ localTime(row.decided_at) }}</td>
      </tr></tbody>
    </table></div>
  </section>
</template>

<style scoped>
.notice{margin:0 24px 18px;padding:12px 16px;border:1px solid #e2d7b4;background:#fdf8e7;color:#6f5a1c;border-radius:8px;font-size:12px;line-height:1.5}
.clock{display:block;font-size:9px;letter-spacing:.6px;text-transform:uppercase;color:#8a96a7;margin-top:3px}
.request pre{margin:0;font-size:11px;max-width:360px;max-height:160px;overflow:auto;background:#f8fafc;padding:8px;border-radius:6px;white-space:pre}
.reason{white-space:normal;max-width:260px}
.badge{text-transform:none}
.badge.mode-live{background:#9b2226;color:#fff;font-weight:700}
</style>
