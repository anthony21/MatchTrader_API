<script setup>
import { computed } from 'vue'
import { localTime } from '../time.js'
// The record page. Local-clock and broker-clock columns stay separate and labelled;
// only verified_open / verified_closed are styled as verified; every cancelled row
// shows its reason and origin; TradingBox (PAMM) never confirms or invalidates a row.
const props = defineProps({ rows: { type: Array, default: () => [] }, mode: { type: String, default: 'paper' } })
const VERIFIED = new Set(['verified_open', 'verified_closed'])
const STATE_LABELS = {
  candidate: 'Candidate', paper_sent: 'Paper sent', sent_unconfirmed: 'Sent · unconfirmed',
  read_back_no_time: 'Read back · no open time', verified_open: 'Verified open', verified_closed: 'Verified closed',
  cancelled: 'Cancelled', rejected: 'Rejected', uncertain: 'Uncertain', guarded: 'Guarded', unattributed: 'Unattributed',
}
const NO_TIME = 'The broker confirmed this position but did not report its open time.'
// Paper sends have their own page; they are never mixed into this ledger.
const ledger = computed(() => props.rows.filter(row => row.state !== 'paper_sent'))
const paperHidden = computed(() => props.rows.length - ledger.value.length)
const join = values => (Array.isArray(values) && values.length ? values.join(', ') : '—')
const scope = value => (Array.isArray(value) ? value.join(' / ') : value || '—')
const stateLabel = state => STATE_LABELS[state] || state || 'state not recorded'
function reasonText(c) {
  if (typeof c.summary === 'string' && c.summary.trim()) return c.summary
  const code = c.code == null || c.code === '' ? (c.outcome || 'no code') : /^\d+$/.test(String(c.code)) ? `HTTP ${c.code}` : String(c.code)
  return `${code} · ${c.origin || 'origin not recorded'} · no message supplied`
}
function pammText(p) {
  if (!p?.published) return 'Not published'
  const ack = p.upstream_status == null || p.upstream_status === '' ? 'ack not received' : `TradingBox ${p.upstream_status}`
  return `Published ${localTime(p.published_at)} · ${ack}`
}
// A signal-driven cancel or close applied to this trade (or refused), with the broker's answer.
const UNWIND_VERB = { CANCEL: 'Cancel', CLOSE: 'Close' }
const UNWIND_OUTCOME = { accepted: 'broker accepted', uncertain: 'outcome unconfirmed', held: 'not sent', dispatching: 'in flight' }
function unwindText(u) {
  const verb = UNWIND_VERB[u.action] || u.action || 'Unwind'
  const outcome = UNWIND_OUTCOME[u.outcome] || u.outcome || 'outcome not recorded'
  return `${verb} on signal · ${outcome}`
}
</script>

<template>
  <section class="card broker-panel verified-trades" aria-label="Verified trades">
    <div class="section-heading"><div><h2>Verified trades</h2>
      <p>Every trade the copier has handled for this account, with the broker's own read-back as the only proof of arrival.</p></div>
      <span class="badge" :class="mode === 'live' ? 'mode-live' : 'mode-paper'">Copy mode: {{ mode === 'live' ? 'LIVE' : 'paper' }}</span></div>
    <p v-if="paperHidden" class="quiet">{{ paperHidden }} paper {{ paperHidden === 1 ? 'send is' : 'sends are' }} listed on the Paper trades page, not here.</p>
    <p v-if="!ledger.length" class="quiet empty-ledger">No verified trade records for this account yet. An empty ledger means nothing has been recorded, not that every trade arrived.</p>
    <div v-else class="table-wrap"><table>
      <thead><tr>
        <th>Trade</th><th>Quantower ID</th><th>AquaFunded ID</th>
        <th>Sent<span class="clock">local clock</span></th>
        <th>Confirmed<span class="clock">local clock</span></th>
        <th>Aqua open time<span class="clock broker">broker clock</span></th>
        <th>PAMM<span class="clock">local clock</span></th>
        <th>State</th><th>Reason · origin</th><th>Activity</th>
      </tr></thead>
      <tbody>
        <template v-for="row in ledger" :key="row.trade_id">
          <tr class="ledger-row" :class="[`state-${row.state}`, { verified: VERIFIED.has(row.state) }]" :data-trade="row.trade_id">
            <td>{{ row.symbol || '—' }} · {{ row.side || '—' }} · {{ row.lots ?? '—' }} lots
              <span class="subtext">{{ row.trade_id }} · {{ row.source?.code || 'source not recorded' }}</span></td>
            <td>orders {{ join(row.source?.order_ids) }}<span class="subtext">positions {{ join(row.source?.position_ids) }}</span></td>
            <td>orders {{ join(row.destination?.order_ids) }}<span class="subtext">positions {{ join(row.destination?.position_ids) }}</span></td>
            <td class="time">{{ localTime(row.timestamps?.sent_at) }}</td>
            <td class="time">{{ localTime(row.timestamps?.confirmed_at) }}</td>
            <td class="time broker-time">{{ localTime(row.timestamps?.broker_open, row.timestamps?.broker_open_millis) }}</td>
            <td class="pamm">{{ pammText(row.pamm) }}</td>
            <td class="state-cell"><span class="badge state" :class="VERIFIED.has(row.state) ? 'verified' : `plain ${row.state}`">{{ stateLabel(row.state) }}</span>
              <span v-if="row.state === 'read_back_no_time'" class="subtext no-time">{{ NO_TIME }}</span>
              <span v-if="row.unwind" class="subtext unwind" :class="`unwind-${row.unwind.outcome || 'unrecorded'}`">{{ unwindText(row.unwind) }} · {{ localTime(row.unwind.at) }}</span></td>
            <td class="reason">
              <template v-if="row.cancellation">{{ reasonText(row.cancellation) }}
                <span class="badge origin" :class="`origin-${row.cancellation.origin || 'unrecorded'}`">{{ row.cancellation.origin || 'origin not recorded' }}</span></template>
              <template v-else>—</template></td>
            <td><span v-if="row.state === 'candidate'">{{ row.reasons?.[0] || 'Awaiting a matching bridge request' }}</span></td>
          </tr>
          <tr class="evidence-row"><td colspan="10"><details>
            <summary>Evidence for {{ row.trade_id }}</summary>
            <p>Destination {{ row.destination?.broker || 'broker not recorded' }} / {{ row.destination?.account_id || 'account not recorded' }}
              · Source {{ row.source?.code || '—' }} · {{ scope(row.source?.scope) }} · Mapping {{ row.mapping_status || '—' }}</p>
            <p v-for="reason in row.reasons || []" :key="reason">{{ reason }}</p>
            <p v-if="row.read_back">Broker read-back by {{ row.read_back.reader || 'reader not recorded' }}: volume {{ row.read_back.volume ?? '—' }}, open price {{ row.read_back.open_price ?? '—' }}.</p>
            <p v-else>No broker read-back recorded. A send response alone does not prove this trade arrived.</p>
            <template v-if="row.cancellation">
              <p>{{ row.cancellation.origin || 'origin not recorded' }} · {{ row.cancellation.outcome || 'outcome not recorded' }} · code {{ row.cancellation.code ?? '—' }} · {{ localTime(row.cancellation.at) }}</p>
              <pre v-if="row.cancellation.evidence != null">{{ JSON.stringify(row.cancellation.evidence, null, 2) }}</pre>
            </template>
            <template v-if="row.unwind">
              <p class="unwind-detail">{{ unwindText(row.unwind) }} · signal {{ row.unwind.request_id || '—' }} · {{ row.unwind.origin || 'origin not recorded' }} · {{ localTime(row.unwind.at) }}</p>
              <p v-if="row.unwind.summary">{{ row.unwind.summary }}</p>
              <pre v-if="row.unwind.request">{{ JSON.stringify(row.unwind.request, null, 2) }}</pre>
            </template>
          </details></td></tr>
        </template>
      </tbody>
    </table></div>
    <p class="quiet footnote">Verified means the broker returned this position on a read and reported its own open time. A send response alone is not verification. TradingBox is a third viewpoint and is never used to confirm or invalidate a trade.</p>
  </section>
</template>

<style scoped>
.clock{display:block;font-size:9px;letter-spacing:.6px;text-transform:uppercase;color:#8a96a7;margin-top:3px}
.clock.broker{color:#8d6a2b}
.broker-time{background:#fffaf0}
.badge.state.verified{background:#e3f5ec;color:#1f6a4c;border:1px solid #b7dfc9}
.badge.state.plain{background:#eef2f6;color:#586e88;text-transform:none}
.badge.state.cancelled,.badge.state.rejected{background:#fdecea;color:#9b2226}
.badge.state.uncertain,.badge.state.guarded,.badge.state.unattributed,.badge.state.sent_unconfirmed,.badge.state.read_back_no_time{background:#fff3de;color:#936b29}
.badge.origin{margin-left:8px;text-transform:none;background:#e8edf4;color:#3d5068}
.badge.origin.origin-broker{background:#fdecea;color:#9b2226}
.badge.origin.origin-transport{background:#fff3de;color:#936b29}
.badge.mode-live{background:#9b2226;color:#fff;text-transform:none;font-weight:700}
.badge.mode-paper{text-transform:none}
.reason,.pamm,.state-cell{white-space:normal;max-width:280px}
.no-time{white-space:normal;max-width:220px}
.unwind{display:block;white-space:normal;max-width:220px;margin-top:4px;font-weight:600}
.unwind-accepted{color:#1f6a4c}
.unwind-uncertain,.unwind-dispatching{color:#936b29}
.unwind-held{color:#9b2226}
.evidence-row td{padding:0 17px 12px;white-space:normal;border-bottom:1px solid #edf1f6}
.evidence-row details{font-size:12px;color:#5b6b82}
.evidence-row summary{cursor:pointer;font-size:11px;color:#6a7e94}
.evidence-row pre{font-size:11px;overflow:auto;background:#f8fafc;padding:10px;border-radius:6px}
.footnote{padding-top:16px;line-height:1.6}
</style>
