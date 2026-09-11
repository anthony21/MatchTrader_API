import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, test, vi } from 'vitest'
import ClosedOrders from './ClosedOrders.jsx'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root, host
afterEach(() => { if (root) act(() => root.unmount()); host?.remove(); vi.resetAllMocks() })
async function render(account = 'a') {
  if (!root) { host = document.createElement('div'); document.body.append(host); root = createRoot(host) }
  await act(async () => root.render(<ClosedOrders state={{ account_id: account, connection: 'connected' }} />))
}
const submit = () => act(async () => host.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
const response = { account_id: 'a', currency: 'USD', updated_at: '2026-09-11T07:00:00Z', summary: { closed: 1, wins: 0, losses: 0, breakevens: 1, net_profit: '0' },
  operations: [{ id: 'p1', uid: 'u1', symbol: 'XAUUSD', side: 'BUY', volume: '.1', openPrice: '2000', stopLoss: '1990', takeProfit: '2010', closePrice: '2010.1', netProfit: '0', closeReason: 'CLOSE_REASON_TAKE_PROFIT', time: '2026-09-10T12:00:00Z' }] }

test('manual history load shows stored levels, zero net profit and exit details', async () => {
  root = null
  request.mockImplementation(path => Promise.resolve(path === 'broker-profiles' ? { profiles: [] } : response))
  await render()
  expect(request).toHaveBeenCalledTimes(1)
  await submit()
  expect(host.textContent).toContain('Take profit')
  expect(host.textContent).toContain('2010.1')
  expect(host.textContent).toContain('0 USD')
  expect(host.querySelector('details').textContent).toContain('p1')
  expect(request.mock.calls[1][1]).toMatchObject({ account_id: 'a', profile: 'primary' })
})

test('switching account discards an in-flight response from the previous account', async () => {
  root = null
  let resolve
  request.mockImplementation(path => path === 'broker-profiles' ? Promise.resolve({ profiles: [] }) : new Promise(r => { resolve = r }))
  await render()
  await submit()
  await render('b')
  await act(async () => resolve(response))
  expect(host.textContent).not.toContain('XAUUSD')
  expect(host.textContent).toContain('No history loaded')
})
