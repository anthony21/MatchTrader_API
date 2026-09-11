import React, { useState } from 'react'
import { localTime } from '../time.js'
import './orders.css'
import ClosedOrders from './ClosedOrders.jsx'

const value = v => v === null || v === undefined || v === '' ? '—' : String(v)
const price = v => v == null || Number(v) === 0 ? '—' : value(v)
const source = code => ({ R01: 'R01 strategy', X17: 'X17 strategy', P01: 'P01 manual', MANUAL: 'Manual', UNKNOWN: 'Unknown source' }[code] || 'Unknown source')
const status = code => ({ observed: 'Source captured', pending: 'Pending at broker', open: 'Position recorded', resolved: 'Lifecycle resolved',
  uncertain: 'Needs review', dispatching: 'Sending request', confirmed: 'IDs linked', incomplete: 'Linking incomplete', unconfirmed: 'Not confirmed', ambiguous: 'Needs review',
  accepted: 'Broker accepted', held: 'Held', captured: 'Captured', CREATE: 'Create', EDIT: 'Modify', CANCEL: 'Cancel', CLOSE: 'Close' }[code] || value(code))
const searchText = object => object && typeof object === 'object' ? Object.values(object).map(searchText).join(' ') : String(object ?? '')
const needsReview = m => m.state === 'uncertain' || m.mapping_status === 'uncertain' || m.mapping_status === 'ambiguous' || m.reasons?.length > 0
const idList = (m, side, kind) => (m.links || []).filter(l => l.side === side && l.kind === kind).map(l => l.native_id).join(', ')
function Numbers({ fields }) { return <dl className="order-numbers">{fields.map(([label, number]) => <div key={label}><dt>{label}</dt><dd>{number}</dd></div>)}</dl> }
function Empty({ title, children }) { return <div className="orders-empty"><span aria-hidden="true">◇</span><h3>{title}</h3><p>{children}</p></div> }
function CopyId({ label, id }) {
  const [feedback, setFeedback] = useState('')
  async function copy() { try { await navigator.clipboard.writeText(id); setFeedback('Copied') } catch { setFeedback('Select the ID to copy') } }
  return <div className="order-id"><span>{label}</span><code>{id || 'Not linked'}</code>{id && <button onClick={copy} aria-label={`Copy ${label}`}>Copy</button>}<small role="status">{feedback}</small></div>
}
function MappingDetails({ trade }) {
  return <div className="order-detail-content">
    <div className="order-detail-grid"><section><h4>Source · Quantower</h4><p>{source(trade.source)} · {trade.source_scope?.[2] || 'Account unavailable'}</p>
      <p>{trade.source_scope?.slice(0, 2).join(' · ')}</p><CopyId label="Quantower order ID" id={idList(trade, 'source', 'order')} /><CopyId label="Quantower position ID" id={idList(trade, 'source', 'position')} /></section>
      <section><h4>Destination · Broker</h4><p>{trade.account_id || 'Not assigned'}</p><CopyId label="Broker order ID" id={idList(trade, 'destination', 'order')} /><CopyId label="Broker position ID" id={idList(trade, 'destination', 'position')} /></section></div>
    <CopyId label="Internal Trade ID" id={trade.trade_id} />
    <p className="order-explanation">This internal reference links the source and broker records. It is not proof of a broker fill.</p>
    {!!trade.reasons?.length && <div className="order-notice">{trade.reasons.map((r, i) => <p key={i}>{r}</p>)}</div>}
    {!!trade.quantities?.length && <section><h4>Quantity evidence</h4>{trade.quantities.map((q, i) => <div className="order-evidence" key={i}><strong>{q.side === 'source' ? 'Quantower' : 'Broker'} · {q.unit}</strong><Numbers fields={[
      ['Requested', value(q.requested)], ['Reported filled', value(q.cumulative)], ['Remaining', value(q.remaining)], ['Fill state', q.partial ? 'Partial fill' : 'Not marked partial'],
    ]} /></div>)}</section>}
    {(trade.links || []).filter(l => l.kind === 'position').map((link, i) => <div className="order-evidence" key={i}><h4>{link.contributors?.length > 1 ? 'Merged position' : 'Position relationship'} · {link.side === 'source' ? 'Quantower' : 'Broker'}</h4>
      <p>Allocation {link.allocation_confirmed ? 'confirmed' : 'unconfirmed'} · opening contribution {value(link.observed_open_contribution)} · closing contribution {value(link.observed_close_contribution)}</p>
      {link.position_snapshot && <p>Whole-position volume: {value(link.position_snapshot.volume)} · {localTime(link.position_snapshot.updated_at)}</p>}
      <CopyId label="Contributing trade IDs" id={link.contributors?.join(', ')} /></div>)}
    <section><h4>Recorded executions</h4>{trade.fills?.length ? trade.fills.map((fill, i) => <div className="order-evidence" key={i}><strong>{fill.side === 'source' ? 'Quantower' : 'Broker'} · {fill.effect === 'OPEN' ? 'Opening fill' : fill.effect === 'CLOSE' ? 'Closing fill' : 'Fill effect unknown'}</strong>
      <p>{value(fill.quantity)} at {value(fill.price)} · {localTime(fill.emitted_at)}</p><CopyId label="Execution ID" id={fill.execution_id} /><CopyId label="Fill order ID" id={fill.order_id} /><CopyId label="Fill position ID" id={fill.position_id} /></div>) : <p>No executions with stable fill IDs recorded.</p>}</section>
    <section><h4>Action history</h4>{trade.actions?.length ? <ol className="order-timeline">{trade.actions.map((a, i) => <li key={a.action_key || i}><strong>{status(a.action)}</strong><span>{status(a.outcome)}</span><small>{localTime(a.updated_at)}</small>
      <details><summary>Request details</summary><CopyId label="Request ID" id={a.request_id} /><pre>{JSON.stringify(a.request, null, 2)}</pre></details></li>)}</ol> : <p>No broker actions recorded.</p>}</section>
  </div>
}

export default function Orders({ state = {}, mappings = [], busy, onRefresh }) {
  const [page, setPage] = useState(1)
  const [tab, setTab] = useState('positions'), [search, setSearch] = useState(''), [reviewOnly, setReviewOnly] = useState(false)
  const connected = state.connection === 'connected'
  const positions = state.positions || [], pending = state.orders || []
  const query = search.toLowerCase().trim()
  const brokerMappings = row => mappings.filter(m => m.account_id === state.account_id && (m.links || []).some(l => l.side === 'destination' && l.kind === (tab === 'positions' ? 'position' : 'order') && l.native_id === row.id))
  const matches = row => searchText([row, tab === 'activity' ? [] : brokerMappings(row)]).toLowerCase().includes(query)
  const filtered = (tab === 'positions' ? positions : tab === 'pending' ? pending : mappings).filter(matches).filter(m => tab !== 'activity' || !reviewOnly || needsReview(m))
  const snapshot = tab === 'positions' ? state.positions_at : state.orders_at
  const totalPages = Math.max(1, Math.ceil(filtered.length / 12))
  const currentPage = Math.min(page, totalPages)
  const changeTab = next => { setPage(1); setTab(next); setSearch(''); setReviewOnly(false) }
  const names = { positions: 'Open positions', pending: 'Pending orders', activity: 'Copy activity', closed: 'Closed trades' }
  return <section className="orders-workspace" aria-label="Orders workspace">
    <div className="orders-overview"><div className="orders-intro"><div><span className="orders-kicker">YOUR TRADING DESK</span><h2>Every trade, clearly.</h2><p>Account {state.account_id || 'not selected'} <span className={`orders-dot ${connected ? 'online' : ''}`} /> {connected ? 'Connected' : 'Disconnected'}</p></div>
      <button className="primary" disabled={busy || !connected} onClick={onRefresh}>{busy ? 'Refreshing…' : 'Refresh broker data'}</button></div>
      <div className="orders-summary">{[['positions', state.positions_at ? positions.length : '—', 'Trades held at the broker'], ['pending', state.orders_at ? pending.length : '—', 'Orders waiting to fill'], ['activity', mappings.length, 'Captured trade relationships']].map(([key, count, description]) => <button key={key} onClick={() => changeTab(key)} aria-pressed={tab === key}>
        <span>{names[key]}</span><strong>{count}</strong><small>{description}</small></button>)}</div>
    </div>
    <div className="orders-board"><div className="orders-navigation"><nav aria-label="Order views">{Object.entries(names).map(([key, name]) => <button key={key} aria-pressed={tab === key} onClick={() => changeTab(key)}>{name}</button>)}</nav>
      {tab !== 'closed' && <input aria-label="Search orders" placeholder="Search instrument, strategy or ID…" value={search} onChange={e => { setPage(1); setSearch(e.target.value) }} />}</div>
      {tab === 'closed' ? <ClosedOrders state={state} /> : <>
      <div className="orders-section-title"><div><h3>{names[tab]}</h3><p>{tab === 'activity' ? 'Quantower → broker · linked IDs and execution evidence' : snapshot ? `Snapshot ${localTime(snapshot)}${connected ? ' · refreshes every 5 seconds' : ' · disconnected, saved snapshot'}` : 'Connect your account to load a broker snapshot.'}</p></div>
        {tab === 'activity' && <label className="orders-review"><input type="checkbox" checked={reviewOnly} onChange={e => { setPage(1); setReviewOnly(e.target.checked) }} /> Needs review ({mappings.filter(needsReview).length})</label>}</div>
      {tab !== 'activity' && !snapshot ? <Empty title="Broker data not loaded">Log in above, then refresh broker data to see {names[tab].toLowerCase()}.</Empty> : !filtered.length ? <Empty title={query || reviewOnly ? 'No matching trades' : tab === 'activity' ? 'No copy activity yet' : tab === 'positions' ? 'No open positions' : 'No pending orders'}>{query || reviewOnly ? 'Try another search or clear your filters.' : tab === 'activity' ? 'Captured Quantower trades will appear here with their broker relationships.' : 'This broker snapshot contains no trades in this view.'}</Empty> :
        <div className="orders-cards">{filtered.slice((currentPage - 1) * 12, currentPage * 12).map((row, index) => {
          const journal = tab === 'activity', position = tab === 'positions'
          const profit = row.netProfit ?? row.profit
          const linked = journal ? row : mappings.find(m => (m.links || []).some(l => l.side === 'destination' && l.kind === (position ? 'position' : 'order') && l.native_id === row.id && m.account_id === state.account_id))
          const countLinks = !journal ? mappings.filter(m => (m.links || []).some(l => l.side === 'destination' && l.kind === (position ? 'position' : 'order') && l.native_id === row.id && m.account_id === state.account_id)).length : 1
          const attribution = linked && countLinks === 1 ? source(linked.source) : countLinks > 1 ? 'Multiple source trades' : 'Source not linked'
          return <article className="order-card" key={row.trade_id || row.id || index}>
            <div className="order-card-heading"><div className="order-identity"><span className={`order-direction ${String(row.side).toLowerCase()}`}>{row.side || '—'}</span><div><h4>{row.symbol || 'Instrument unavailable'}</h4><p>{journal ? source(row.source) : attribution} · {journal ? row.account_id ? `Destination ${row.account_id}` : 'No destination assigned' : position ? 'Open position' : `${row.type || 'Pending'} order`}</p></div></div>
              {position ? <div className={`order-profit ${Number(profit) > 0 ? 'positive' : Number(profit) < 0 ? 'negative' : ''}`}><span>{row.netProfit != null ? 'Net P/L' : 'Profit / loss'}</span><strong>{profit == null ? 'Unavailable' : `${Number(profit) > 0 ? '+' : ''}${profit}`}</strong></div> : <span className={`order-state ${journal && needsReview(row) ? 'attention' : ''}`}>{journal ? status(row.state) : 'Waiting to fill'}</span>}</div>
            {journal ? <div className="order-route"><div><small>FROM QUANTOWER</small><strong>{row.source_scope?.[2] || 'Account unavailable'}</strong><span>{source(row.source)}</span></div><span aria-hidden="true">→</span><div><small>TO BROKER</small><strong>{row.account_id || 'Not assigned'}</strong><span>{status(row.mapping_status)}</span></div><div><small>EXECUTION EVIDENCE</small><strong>{row.fills?.length || 0} recorded fills</strong><span>{row.quantities?.some(q => q.partial) ? 'Partial fill reported' : 'See details for confirmation'}</span></div></div> : <Numbers fields={[
              ['Size · lots', value(row.volume)], ['Entry price', value(position ? row.openPrice : row.activationPrice)], ['Stop loss', price(row.stopLoss)], ['Take profit', price(row.takeProfit)],
            ]} />}
            <div className="order-card-footer"><span>{journal ? `Updated ${localTime(row.updated_at)}` : `${position ? 'Opened' : 'Created'} ${localTime(position ? row.openTime : row.creationTimeIso || row.creationTime, position ? row.openTimeMillis : null)}`}</span>
              {!journal && !position && <span>P/L starts after a fill</span>}</div>
            <details className="order-details"><summary>{journal ? 'View trade details & IDs' : 'View broker reference & source links'}</summary>
              {journal ? <MappingDetails trade={row} /> : <div className="order-detail-content"><CopyId label={position ? 'Broker position ID' : 'Broker order ID'} id={row.id} />
                {linked && countLinks === 1 ? <MappingDetails trade={linked} /> : <p>{countLinks > 1 ? 'Multiple trade records contribute to this broker ID. Review Copy activity before making allocation assumptions.' : 'No exact source mapping is recorded for this broker ID.'}</p>}</div>}
            </details>
          </article>
        })}</div>}
      {filtered.length > 12 && <nav className="orders-pagination" aria-label="Trade pages"><span>Page {currentPage} of {totalPages} · {filtered.length} trades</span><button disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</button><button disabled={currentPage === totalPages} onClick={() => setPage(currentPage + 1)}>Next</button></nav>}
      <div className="orders-footnote">{tab === 'activity' ? 'Source capture and linked IDs do not prove a broker fill. Internal IDs are available inside each trade.' : 'Broker snapshots are account-specific. Missing P/L is shown as unavailable; pending orders do not have P/L.'}</div>
      </>}
    </div>
  </section>
}
