import React, { useEffect, useRef, useState } from 'react'
import { request } from '../api.js'
import { localTime } from '../time.js'
import './closed-orders.css'

const dateText = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const display = value => value == null || value === '' ? '—' : String(value)
const reason = value => ({ CLOSE_REASON_STOP_LOSS: 'Stop loss', CLOSE_REASON_TAKE_PROFIT: 'Take profit' }[value] || value?.replace('CLOSE_REASON_', '').replaceAll('_', ' ') || 'Not provided')

export default function ClosedOrders({ state = {} }) {
  const today = new Date()
  const [from, setFrom] = useState(() => dateText(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 7)))
  const [to, setTo] = useState(() => dateText(today))
  const [profiles, setProfiles] = useState([]), [profile, setProfile] = useState('primary')
  const [result, setResult] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [search, setSearch] = useState(''), [page, setPage] = useState(1)
  const revision = useRef(0)
  const selected = profiles.find(p => p.profile === profile)
  const accountId = profile === 'primary' ? state.account_id : selected?.account_id
  const connected = profile === 'primary' ? state.connection === 'connected' : selected?.connection === 'connected'
  useEffect(() => {
    let active = true
    request('broker-profiles').then(data => { if (active) setProfiles(data.profiles || []) }).catch(() => {})
    return () => { active = false; revision.current++ }
  }, [])
  useEffect(() => { revision.current++; setResult(null); setError(''); setBusy(false); setPage(1) }, [profile, accountId, from, to])
  async function load(event) {
    event?.preventDefault()
    const current = ++revision.current
    setBusy(true); setError(''); setResult(null); setPage(1)
    try {
      const start = new Date(`${from}T00:00:00`), end = new Date(`${to}T00:00:00`)
      end.setDate(end.getDate() + 1)
      if (!from || !to || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) throw Error('Choose a valid start and end date.')
      const data = await request('orders/closed', { profile, account_id: accountId, from: start.toISOString(), to: end.toISOString() })
      if (current === revision.current) {
        if (data.account_id !== accountId) throw Error('Account changed. Load history again.')
        setResult(data)
      }
    } catch (err) { if (current === revision.current) setError(err.message) }
    finally { if (current === revision.current) setBusy(false) }
  }
  const rows = (result?.operations || []).filter(row => [row.symbol, row.side, row.id, reason(row.closeReason)].join(' ').toLowerCase().includes(search.toLowerCase()))
  const pages = Math.max(1, Math.ceil(rows.length / 25)), currentPage = Math.min(page, pages)
  const stats = result?.summary
  return <section className="closed-orders" aria-label="Closed trades">
    <h3>Closed trades</h3><p>Realized broker results, selected by close date. Dates use {Intl.DateTimeFormat().resolvedOptions().timeZone}. Each partial close remains a separate operation.</p>
    <form onSubmit={load} className="closed-filters">
      <label>History account<select value={profile} onChange={e => setProfile(e.target.value)}><option value="primary">Selected account · {state.account_id || 'none'}</option>{profiles.filter(p => p.profile !== 'MTR').map(p => <option value={p.profile} key={p.profile}>{p.profile} · {p.account_id || 'not configured'}</option>)}</select></label>
      <label>From date<input type="date" required value={from} onChange={e => setFrom(e.target.value)} /></label>
      <label>Through date<input type="date" required value={to} min={from} onChange={e => setTo(e.target.value)} /></label>
      <button className="primary" disabled={busy || !connected || !accountId}>{busy ? 'Loading history…' : 'Load closed trades'}</button>
    </form>
    {!connected && <p className="order-notice">Connect this account first. Additional accounts connect from Broker accounts.</p>}
    {error && <p role="alert" className="order-notice">{error}</p>}
    {!result && !busy && !error && <p>No history loaded. Choose dates, then load closed trades (up to 93 days).</p>}
    {result && <>
      <p>Account {result.account_id} · {result.currency} · Loaded {localTime(result.updated_at)}{!connected ? ' · disconnected; saved snapshot' : ''}</p>
      <div className="closed-summary"><span><b>{stats.closed}</b> closed</span><span><b>{stats.wins}</b> wins</span><span><b>{stats.losses}</b> losses</span><span><b>{stats.breakevens}</b> breakeven</span><span><b>{stats.closed ? (100 * stats.wins / stats.closed).toFixed(1) + '%' : '—'}</b> win rate</span><span><b>{stats.net_profit} {result.currency}</b> net P/L</span></div>
      <p className="quiet">Summary covers the full loaded interval. Wins use net profit after costs; breakevens count in the denominator.</p>
      <label>Search closed trades<input value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} placeholder="Symbol, order ID, side or exit reason" /></label>
      <div className="table-wrap"><table><thead><tr>{['Closed · local', 'Symbol', 'Side', 'Lots', 'Entry', 'SL', 'TP', 'Exit', 'Exit reason', 'Net P/L', 'Details'].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>
        {rows.slice((currentPage - 1) * 25, currentPage * 25).map(row => <tr key={row.uid || `${row.id}:${row.closingOrderID}:${row.time}`}><td>{localTime(row.time)}</td><td>{row.symbol}</td><td>{row.side}</td><td>{row.volume}</td><td>{row.openPrice}</td><td>{display(row.stopLoss)}</td><td>{display(row.takeProfit)}</td><td>{row.closePrice}</td><td>{reason(row.closeReason)}</td><td>{row.netProfit}</td><td><details><summary>View trade</summary><dl>{[['Order / position ID', row.id], ['Close ID', row.closingOrderID], ['Operation ID', row.uid], ['Opened · local', localTime(row.openTime)], ['Gross profit', row.profit], ['Commission', row.commission], ['Swap', row.swap]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{display(value)}</dd></div>)}</dl></details></td></tr>)}
        {!rows.length && <tr><td colSpan="11">{search ? 'No matching closed trades.' : 'No closed trades in this date range.'}</td></tr>}
      </tbody></table></div>
      <div className="orders-pagination"><button disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage} of {pages} · {rows.length} results</span><button disabled={currentPage >= pages} onClick={() => setPage(currentPage + 1)}>Next</button></div>
    </>}
  </section>
}
