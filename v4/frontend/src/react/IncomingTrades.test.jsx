import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, test, vi } from 'vitest'
import IncomingTrades from './IncomingTrades.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root, host
afterEach(() => { if (root) act(() => root.unmount()); host?.remove() })
function render(props = {}) {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  act(() => root.render(<IncomingTrades {...props} />))
  return host
}
const event = (id, account, source, opened = 'unconfirmed') => ({ id, trade_id: `trade-${id}`, account_id: account,
  machine: 'qt', connection_id: 'c1', symbol: 'EURUSD', side: 'BUY', kind: 'POSITION', action: 'OBSERVE',
  quantity: '0.0700', price: '1.123456789', sl: '1.12000', tp: '1.13000', order_id: `order-${id}`,
  emitted_at: '2026-09-09T12:00:00Z', decision: 'captured',
  meaning: { source: { code: source, label: `${source} strategy` }, event: { label: 'Position' },
    action: { label: 'Observe' }, opened: { state: opened, label: opened === 'confirmed' ? 'Opening fill' : 'Not confirmed' } } })
const click = el => act(() => el.click())

test('separates lifecycle columns, keeps precision and puts trade ID last with expandable IDs', () => {
  render({ events: [event('1', 'account-a', 'R01')] })
  const headers = [...host.querySelectorAll('th')].map(e => e.textContent)
  expect(headers.slice(2, 6)).toEqual(['Account', 'Source', 'Event', 'Action'])
  expect(headers.at(-1)).toBe('Trade ID')
  expect(host.textContent).toContain('1.123456789')
  expect(host.textContent).toContain('0.0700')
  expect(host.querySelector('tbody').textContent).toContain('Not confirmed')
  click(host.querySelector('[aria-expanded]'))
  expect(host.textContent).toContain('order-1')
})

test('multi-account selection and strategy filter compose and stay scoped by connection', () => {
  render({ events: [event('1', 'a', 'R01'), event('2', 'b', 'X17'), { ...event('3', 'a', 'R01'), connection_id: 'c2' }] })
  const count = () => host.querySelectorAll('tbody > tr').length
  const boxes = host.querySelectorAll('input[type=checkbox]')
  click(boxes[0]); expect(count()).toBe(1)
  click(boxes[1]); expect(count()).toBe(2)
  click([...host.querySelectorAll('nav button')].find(b => b.textContent === 'X17'))
  expect(count()).toBe(1)
  expect(host.querySelector('tbody').textContent).toContain('trade-2')
  click([...host.querySelectorAll('nav button')].find(b => b.textContent === 'R01'))
  expect(host.querySelector('tbody').textContent).not.toContain('trade-3')
})

test('unknown attribution is retained and kind/search filters work', () => {
  render({ events: [{ ...event('1', 'a', 'R01'), meaning: undefined }, { ...event('2', 'b', 'X17'), kind: 'FILL' }] })
  expect(host.querySelector('tbody').textContent).toContain('Unknown source')
  const select = host.querySelector('select')
  act(() => { select.value = 'FILL'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(host.querySelector('tbody').textContent).not.toContain('trade-1')
  const input = host.querySelector('[aria-label="Filter events"]')
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'nothing')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(host.textContent).toContain('No matching events')
})

test('only explicit opening evidence contributes to the metric and no control can enable automatic dispatch', () => {
  const onToggle = vi.fn()
  render({ events: [event('1', 'a', 'R01', 'confirmed'), event('2', 'b', 'X17')], onToggle })
  expect(host.querySelectorAll('.incoming-metrics strong')[2].textContent).toBe('1')
  // The legacy Allow/Stop API trading button is gone: the page offers no way to arm dispatch,
  // even when the state claims the most permissive conditions it ever required.
  const armingButton = () => [...host.querySelectorAll('button')].find(b => /API trading/i.test(b.textContent))
  expect(armingButton()).toBeUndefined()
  act(() => root.render(<IncomingTrades state={{ copying: true, route_configured: true, running: true, connection: 'connected' }} onToggle={onToggle} />))
  expect(armingButton()).toBeUndefined()
  host.querySelectorAll('button').forEach(click)
  expect(onToggle).not.toHaveBeenCalled()
  expect(host.textContent).toContain('Automatic dispatch off')
  expect(host.textContent).toContain('Verified trades page')
  expect(host.textContent).toContain('Waiting for new events')
})

test('shows Quantower connection separately from UI push and does not invent write latency', () => {
  render({ streamStatus: 'live', state: { capture_websocket: { listening: true, connected_senders: 1,
    machines: ['QT source'], queued: 2, in_progress: 1, metrics: { writes_measured: 0, latest: { status: 'held' } } } } })
  const panel = host.querySelector('[aria-label="Quantower receiver status"]')
  expect(panel.textContent).toContain('1 sender connected')
  expect(panel.textContent).toContain('QT source')
  expect(panel.textContent).toContain('Not measured')
  expect(panel.textContent).toContain('0 measured writes')
  expect(host.textContent).toContain('Live push')
  act(() => root.render(<IncomingTrades state={{ capture_websocket: { listening: true,
    metrics: { p95_ms: 15, writes_measured: 2, under_10ms_pct: 50, latest: { dispatch_ms: 15, status: 'accepted' } } } }} />))
  expect(panel.textContent).toContain('Listening · waiting for sender')
  expect(panel.textContent).toContain('15.00 ms')
  expect(panel.textContent).toContain('50% under 10 ms')
})
