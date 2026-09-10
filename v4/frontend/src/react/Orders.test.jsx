import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, test, vi } from 'vitest'
import Orders from './Orders.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root, host
const mapping = { trade_id: '99c88b5c-70ea-4329-9572-29b5625ab466', symbol: 'EURUSD', side: 'BUY', source: 'MANUAL', state: 'observed',
  account_id: '', source_scope: ['qt', 'connection', 'source'], mapping_status: 'unconfirmed', links: [], quantities: [], fills: [], actions: [] }
afterEach(() => { if (root) act(() => root.unmount()); host?.remove(); vi.unstubAllGlobals() })
function render(props) { host = document.createElement('div'); document.body.append(host); root = createRoot(host); act(() => root.render(<Orders {...props} />)) }
const click = element => act(() => element.click())
const tab = name => click([...host.querySelectorAll('.orders-navigation button')].find(b => b.textContent === name))

test('copy activity leads with human labels and keeps the complete reference in collapsed details', () => {
  render({ mappings: [mapping] }); tab('Copy activity')
  expect(host.querySelector('.order-identity h4').textContent).toBe('EURUSD')
  expect(host.querySelector('.order-card-heading').textContent).toContain('Source captured')
  expect(host.querySelector('.order-card-heading').textContent).not.toContain(mapping.trade_id)
  expect(host.querySelector('.order-details').open).toBe(false)
  expect(host.querySelector('.order-details').textContent).toContain(mapping.trade_id)
  expect(host.querySelector('.order-route').textContent).toContain('Not assigned')
})

test('position P/L preserves net zero and precision, pending has no fabricated profit', () => {
  render({ state: { account_id: 'a', positions_at: '2026-09-10T00:00:00Z', orders_at: '2026-09-10T00:00:00Z',
    positions: [{ id: 'p1', symbol: 'EURUSD', volume: '.0700', openPrice: '1.123456789', netProfit: '0', profit: '15' }],
    orders: [{ id: 'o1', symbol: 'XAUUSD', volume: '.02', activationPrice: '2400' }] } })
  expect(host.querySelector('.order-profit strong').textContent).toBe('0')
  expect(host.textContent).toContain('1.123456789')
  expect(host.textContent).toContain('.0700')
  tab('Pending orders')
  expect(host.querySelector('.order-profit')).toBeNull()
  expect(host.textContent).toContain('P/L starts after a fill')
})

test('unloaded snapshots differ from empty snapshots, and refresh respects connection state', () => {
  const onRefresh = vi.fn()
  render({ state: {}, onRefresh })
  expect(host.textContent).toContain('Broker data not loaded')
  expect(host.querySelector('.orders-intro button').disabled).toBe(true)
  act(() => root.render(<Orders state={{ connection: 'connected', positions_at: '2026-09-10T00:00:00Z', positions: [] }} onRefresh={onRefresh} />))
  expect(host.textContent).toContain('No open positions')
  click(host.querySelector('.orders-intro button')); expect(onRefresh).toHaveBeenCalledOnce()
})

test('multiple exact source links do not invent a single strategy', () => {
  const links = [{ side: 'destination', kind: 'position', native_id: 'p1' }]
  render({ state: { account_id: 'a', positions_at: '2026-09-10T00:00:00Z', positions: [{ id: 'p1', symbol: 'EURUSD' }] },
    mappings: [{ ...mapping, account_id: 'a', source: 'R01', links }, { ...mapping, trade_id: 'second', account_id: 'a', source: 'X17', links }] })
  expect(host.querySelector('.order-card-heading').textContent).toContain('Multiple source trades')
})

test('search, attention filter and pagination reduce the activity without losing reference access', async () => {
  const writeText = vi.fn().mockResolvedValue()
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  render({ mappings: Array.from({ length: 15 }, (_, i) => ({ ...mapping, trade_id: `trade-${i}`, symbol: `SYM${i}`, state: i === 14 ? 'uncertain' : 'observed' })) })
  tab('Copy activity')
  expect(host.querySelectorAll('.order-card')).toHaveLength(12)
  click([...host.querySelectorAll('.orders-pagination button')].find(b => b.textContent === 'Next'))
  expect(host.querySelectorAll('.order-card')).toHaveLength(3)
  click(host.querySelector('.orders-review input'))
  expect(host.querySelectorAll('.order-card')).toHaveLength(1)
  await act(async () => host.querySelector('[aria-label="Copy Internal Trade ID"]').click())
  expect(writeText).toHaveBeenCalledWith('trade-14')
  expect(host.textContent).toContain('Copied')
  const search = host.querySelector('[aria-label="Search orders"]')
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, 'missing'); search.dispatchEvent(new Event('input', { bubbles: true })) })
  expect(host.textContent).toContain('No matching trades')
})

test('broker positions can be searched by their exactly linked strategy', () => {
  render({ state: { account_id: 'a', positions_at: '2026-09-10T00:00:00Z', positions: [{ id: 'p1', symbol: 'EURUSD' }, { id: 'p2', symbol: 'XAUUSD' }] },
    mappings: [{ ...mapping, source: 'R01', account_id: 'a', links: [{ side: 'destination', kind: 'position', native_id: 'p1' }] }] })
  const search = host.querySelector('[aria-label="Search orders"]')
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, 'R01'); search.dispatchEvent(new Event('input', { bubbles: true })) })
  expect(host.querySelectorAll('.order-card')).toHaveLength(1)
  expect(host.querySelector('.order-identity h4').textContent).toBe('EURUSD')
})
