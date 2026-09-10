import React, { useMemo, useState } from 'react'
import { localTime } from '../time.js'
import './incoming.css'

const accountKey = e => JSON.stringify([e.machine ?? '', e.connection_id ?? '', e.account_id ?? ''])
const number = v => v === null || v === undefined || v === '' ? '—' : String(v)
const bracket = v => !v || Number(v) === 0 ? '—' : number(v)
const sourceCode = e => e.meaning?.source?.code ?? 'UNKNOWN'
const sources = ['ALL', 'R01', 'X17', 'P01', 'MANUAL', 'UNKNOWN']

export default function IncomingTrades({ events = [], legacyEvents = [], state = {}, busy, onToggle, streamStatus }) {
  const [accounts, setAccounts] = useState([])
  const [source, setSource] = useState('ALL')
  const [kind, setKind] = useState('ALL')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(null)
  const rows = useMemo(() => [...events, ...legacyEvents].sort((a, b) =>
    (Date.parse(b.received_at || b.emitted_at) || 0) - (Date.parse(a.received_at || a.emitted_at) || 0)), [events, legacyEvents])
  const availableAccounts = [...new Map(rows.map(e => [accountKey(e), e])).entries()]
  const visible = rows.filter(e => (!accounts.length || accounts.includes(accountKey(e))) &&
    (source === 'ALL' || sourceCode(e) === source) && (kind === 'ALL' || e.kind === kind) &&
    [e.symbol, e.side, e.account_id, e.trade_id, e.order_id, e.position_id, e.reason, e.decision, e.status]
      .join(' ').toLowerCase().includes(query.toLowerCase()))
  function selectAccount(key) { setAccounts(current => current.includes(key) ? current.filter(k => k !== key) : [...current, key]) }
  const socket = state.capture_websocket || {}
  const timing = socket.metrics || {}
  const ms = value => typeof value === 'number' ? `${value.toFixed(2)} ms` : 'Not measured'
  const ready = state.route_configured && state.running && state.connection === 'connected'
  return <section className="card incoming-workspace" aria-label="Incoming trade activity">
    <div className="incoming-heading"><div><div className="incoming-eyebrow">INCOMING EVENT STREAM <span role="status" className="stream-status">{streamStatus === 'live' ? '● Live push' : streamStatus === 'reconnecting' ? 'Reconnecting · polling fallback' : 'Connecting…'}</span></div>
      <h2>Incoming trades</h2><p>Follow the account, strategy and lifecycle of every source event.</p></div>
      <button className={state.copying ? 'secondary' : 'primary'} disabled={busy || (!state.copying && !ready)} onClick={onToggle}>
        {state.copying ? 'Stop API trading' : 'Allow API trading'}</button></div>
    <div className="capture-connection" aria-label="Quantower receiver status">
      <div><span>Quantower WebSocket</span><strong>{socket.connected_senders ? `${socket.connected_senders} sender connected` : socket.listening ? 'Listening · waiting for sender' : 'Receiver disabled'}</strong>
        <small>{socket.machines?.join(', ') || socket.endpoint || 'Configure the receiver and bridge token'}</small></div>
      <div><span>Receiver queue</span><strong>{socket.queued ?? 0}</strong><small>{socket.in_progress ?? 0} processing · {socket.acknowledged ?? 0} acknowledged</small></div>
      <div><span>Receive → API write · p95</span><strong>{ms(timing.p95_ms)}</strong><small>{timing.writes_measured ?? 0} measured writes · target &lt;10 ms</small></div>
      <div><span>Latest dispatch</span><strong>{ms(timing.latest?.dispatch_ms)}</strong><small>{timing.latest?.status || 'No event processed'} · {timing.under_10ms_pct == null ? 'No timing samples' : `${timing.under_10ms_pct}% under 10 ms`}</small></div>
      {socket.last_event_at && <p>Last received: {localTime(socket.last_event_at)}</p>}
      {socket.last_error && <p role="alert">Receiver: {socket.last_error}</p>}
    </div>
    <div className="incoming-metrics">
      <div><span>Visible events</span><strong>{visible.length}</strong><small>Latest activity</small></div>
      <div><span>Source accounts</span><strong>{new Set(visible.filter(e => e.account_id).map(accountKey)).size}</strong><small>Separate from destination</small></div>
      <div><span>Opening fill events</span><strong>{visible.filter(e => e.meaning?.opened?.state === 'confirmed').length}</strong><small>Includes partial opening fills</small></div>
      <div><span>Needs attention</span><strong>{visible.filter(e => ['held', 'uncertain'].includes(e.decision || e.status)).length}</strong><small>Held or uncertain</small></div>
    </div>
    <div className="incoming-toolbar">
      <nav aria-label="Source strategy" className="incoming-tabs">{sources.map(code => <button key={code} aria-pressed={source === code}
        onClick={() => setSource(code)}>{code === 'ALL' ? 'All sources' : code === 'UNKNOWN' ? 'Unknown' : code === 'MANUAL' ? 'Manual' : code}</button>)}</nav>
      <div className="incoming-filters">
        <details className="incoming-account-menu"><summary>Source accounts · {accounts.length || 'All'}</summary><div>
          <button onClick={() => setAccounts([])}>Show all accounts</button>
          {availableAccounts.map(([key, e]) => <label key={key}><input type="checkbox" checked={accounts.includes(key)} onChange={() => selectAccount(key)} />
            <span>{e.account_id || 'Unspecified account'}<small>{e.machine || 'Unknown machine'} · {e.connection_id || 'Unknown connection'}</small></span></label>)}
          <p>Display filter only. Copy routing stays in Copy settings.</p>
        </div></details>
        <select aria-label="Event type" value={kind} onChange={e => setKind(e.target.value)}><option value="ALL">All event types</option>
          {[...new Set(rows.map(e => e.kind).filter(Boolean))].sort().map(k => <option key={k} value={k}>{rows.find(e => e.kind === k)?.meaning?.event?.label || k}</option>)}</select>
        <input aria-label="Filter events" placeholder="Search symbol, account or ID…" value={query} onChange={e => setQuery(e.target.value)} />
      </div>
    </div>
    <div className="incoming-table-wrap" role="region" aria-label="Trade event table" tabIndex={0}>
      <table className="incoming-table"><thead><tr>
        <th>Time<small>Local time</small></th><th>Instrument</th><th>Account</th><th>Source</th><th>Event</th><th>Action</th>
        <th>Opened?<small>Source evidence</small></th><th>Quantity</th><th>Entry / fill</th><th>Stop loss</th><th>Take profit</th><th>Result<small>Capture / broker</small></th><th>Trade ID</th>
      </tr></thead><tbody>
        {visible.map(e => { const m = e.meaning || {}; return <React.Fragment key={e.id}>
          <tr>
            <td className="incoming-time">{localTime(e.emitted_at || e.received_at)}</td>
            <td><strong className="incoming-symbol">{e.symbol || '—'}</strong><span className={`incoming-side ${String(e.side).toLowerCase()}`}>{e.side || '—'}</span></td>
            <td><strong>{e.account_id || 'Unspecified'}</strong><small>{e.connection_id || '—'}</small><small>{e.machine || '—'}</small></td>
            <td><span className={`incoming-source source-${sourceCode(e)}`}>{m.source?.label || 'Unknown source'}</span><small>{m.source?.basis || 'No attribution'}</small></td>
            <td title={m.event?.description}>{m.event?.label || e.kind || 'Unknown'}</td>
            <td title={m.action?.description}>{m.action?.label || e.action || 'Unknown'}</td>
            <td><span className={`incoming-evidence evidence-${m.opened?.state || 'unconfirmed'}`} title={m.opened?.description}>{m.opened?.label || 'Not confirmed'}</span></td>
            <td className="incoming-number">{number(e.quantity)}<small>{e.quantity_unit || (e.kind === 'LEGACY' ? 'lots' : 'unit unspecified')}</small></td>
            <td className="incoming-number">{number(e.price)}</td><td className="incoming-number">{bracket(e.sl)}</td><td className="incoming-number">{bracket(e.tp)}</td>
            <td><span className={`incoming-result result-${e.decision || e.status}`}>{m.result || e.decision || e.status || 'Not evaluated'}</span><small className="incoming-reason" title={e.reason}>{e.reason}</small></td>
            <td className="incoming-id"><span>{e.trade_id || 'Unlinked'}</span><button aria-expanded={expanded === e.id} aria-label={`Details for ${e.trade_id || e.id}`} onClick={() => setExpanded(expanded === e.id ? null : e.id)}>Details {expanded === e.id ? '−' : '+'}</button></td>
          </tr>
          {expanded === e.id && <tr className="incoming-details"><td colSpan={13}><div>
            <section><strong>Event meaning</strong><p>{m.event?.description || 'No mapping available.'}</p><p>{m.action?.description}</p><p>{m.opened?.description}</p></section>
            <section><strong>Source identifiers</strong><dl>{['order_id', 'position_id', 'execution_id', 'request_id'].map(k => <React.Fragment key={k}><dt>{k.replaceAll('_', ' ')}</dt><dd>{e[k] || '—'}</dd></React.Fragment>)}</dl></section>
            <section><strong>Attribution & receipt</strong><p>Trade origin: {m.source?.label || 'Unknown'}</p><p>Action source: {m.action_source || 'UNKNOWN'}</p><p>Sending source: {e.sending_source || 'Not supplied'}</p><p>Received: {localTime(e.received_at)}</p><p>{e.reason}</p></section>
          </div></td></tr>}
        </React.Fragment> })}
        {!visible.length && <tr><td colSpan={13}><div className="incoming-empty"><span>◎</span><h3>{rows.length ? 'No matching events' : 'Waiting for new events'}</h3><p>{rows.length ? 'Adjust your account, source or search filters.' : 'Start capture to see incoming Quantower activity here.'}</p></div></td></tr>}
      </tbody></table>
    </div>
    <div className="incoming-footer"><span>{visible.length} of {rows.length} events · latest 200 native + 200 legacy events</span><span>Position observations and accepted requests do not confirm a new fill.</span></div>
    <div className="incoming-routing"><strong>API trading {state.copying ? 'enabled' : 'off'}</strong>
      <p>{state.copying ? 'Eligible trades forward to the configured demo account. Stopping also stops edits, cancellations and closes; existing broker orders remain open.' : ready ? 'Use Allow API trading to forward eligible trades to the verified demo destination.' : 'Connect the demo destination, start capture, and configure the source account, symbol mapping and quantity conversion in Copy settings.'}</p>
      {state.csv_export_error && <p role="alert">CSV update failed. Close the CSV in Excel; the persistent trade journal is intact.</p>}
      {state.reconciliation_message && <p role="alert">{state.reconciliation_message}</p>}
    </div>
  </section>
}
