import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.vue'
import { request } from './api.js'
import { followNativeEvents } from './stream.js'

vi.mock('./stream.js', () => ({ followNativeEvents: vi.fn(() => () => {}) }))
vi.mock('./api.js', () => ({ request: vi.fn() }))
afterEach(() => vi.clearAllMocks())
test('Orders sidebar opens pending orders and open positions with broker reads', async () => {
  const state = { accounts: [{ id: '123' }], account_id: '123', connection: 'connected', orders: [], positions: [] }
  request.mockImplementation(async path => path.endsWith('events') ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Orders').trigger('click')
  await flushPromises()
  expect(wrapper.find('h1').text()).toBe('Orders & positions')
  expect(request).toHaveBeenCalledWith('orders/refresh', { account_id: '123' })
  expect(request).toHaveBeenCalledWith('positions/refresh', { account_id: '123' })
  expect(wrapper.text()).toContain('Open positions')
  expect(wrapper.text()).toContain('Copy activity')
  expect(request).toHaveBeenCalledWith('trade-mappings')
  wrapper.unmount()
})
test('loads selected account and incoming events, then starts the shadow bridge', async () => {
  const state = { accounts: [{ id: '123', verified: false }], account_id: '123', connection: 'disconnected',
    running: false, orders: [], orders_at: null, broker_orders_sent: 0 }
  request.mockImplementation(async path => path === 'events' ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('select').element.value).toBe('123')
  expect(wrapper.text()).toContain('API trading off')
  await wrapper.find('button.primary').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledWith('start', { account_id: '123' })
  wrapper.unmount()
})

test('refresh token button calls the login refresh route for the selected account', async () => {
  const state = { accounts: [{ id: '123', verified: true }], account_id: '123', connection: 'connected',
    running: true, orders: [], token_refresh_available: true, token_expires_at: '2030-01-01T00:00:00Z' }
  request.mockImplementation(async path => path === 'events' ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Refresh token').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledWith('token/refresh', { account_id: '123' })
  expect(wrapper.find('select').element.value).toBe('123')
  wrapper.unmount()
})

test('live snapshots update native rows without polling and unsubscribe on unmount', async () => {
  const stop = vi.fn()
  followNativeEvents.mockImplementationOnce((events, state) => {
    state('live')
    events([{ id: 'push', symbol: 'PUSHED', kind: 'POSITION' }])
    return stop
  })
  const state = { accounts: [{ id: '123' }], account_id: '123', connection: 'disconnected' }
  request.mockImplementation(async path => path === 'events' ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.text()).toContain('PUSHED')
  expect(wrapper.text()).toContain('Live push')
  expect(request).not.toHaveBeenCalledWith('capture/events')
  wrapper.unmount()
  expect(stop).toHaveBeenCalledOnce()
})
