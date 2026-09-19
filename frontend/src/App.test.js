import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.vue'
import { request } from './api.js'

vi.mock('./api.js', () => ({ request: vi.fn() }))
vi.mock('./components/LiveSignals.vue', () => ({ default: { template: '<section aria-label="Live strategy signals">Live signal stream</section>' } }))
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
  wrapper.unmount()
})
test('shows the always-on signal stream without requiring start capture or a broker', async () => {
  const state = { accounts: [{ id: '123', verified: false }], account_id: '123', connection: 'disconnected',
    running: false, orders: [], orders_at: null, broker_orders_sent: 0 }
  request.mockImplementation(async path => path === 'events' ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.text()).toContain('Live signal stream')
  expect(wrapper.text()).not.toContain('Start capture')
  expect(request.mock.calls.some(([path]) => path === 'start' || path === 'connect')).toBe(false)
  wrapper.unmount()
})

test('refresh token button calls the login refresh route for the selected account', async () => {
  const state = { accounts: [{ id: '123', verified: true }], account_id: '123', connection: 'connected',
    running: true, orders: [], token_refresh_available: true, token_expires_at: '2030-01-01T00:00:00Z' }
  request.mockImplementation(async path => path === 'events' ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Broker sessions').trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Refresh token').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledWith('token/refresh', { account_id: '123' })
  wrapper.unmount()
})

test('navigation, background focus and remount preserve broker sessions without authentication calls', async () => {
  const brokers = ['AQUA', 'GTR'].map(id => ({ id, label: id, state: 'connected', accounts: ['123'],
    expires_at: '2030-01-01T00:00:00Z', refresh_at: '2029-12-31T23:57:00Z' }))
  let broker = 'AQUA'
  const state = () => ({ broker_id: broker, brokers, accounts: [{ id: '123', verified: true }],
    account_id: '123', connection: 'connected', orders: [], positions: [], running: false })
  request.mockImplementation(async (path, payload) => {
    if (path === 'brokers/select') broker = payload.broker_id
    return path.endsWith('events') ? { account_id: '123', events: [] } : state()
  })
  let wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Orders').trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Broker sessions').trigger('click')
  await flushPromises()
  expect(wrapper.find('[aria-label="Capture controls"]').exists()).toBe(false)
  await wrapper.findAll('button').find(b => b.text() === 'Use broker').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('article').find(card => card.attributes('aria-label') === 'GTR').text()).toContain('In view')
  window.dispatchEvent(new Event('blur'))
  document.dispatchEvent(new Event('visibilitychange'))
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  wrapper.unmount()
  wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Broker sessions').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('article').find(card => card.attributes('aria-label') === 'GTR').text()).toContain('In view')
  expect(wrapper.text()).toContain('AQUA')
  const paths = request.mock.calls.map(([path]) => path)
  expect(paths).not.toContain('connect')
  expect(paths).not.toContain('stop')
  expect(paths).not.toContain('brokers/disconnect')
  expect(paths).not.toContain('token/refresh')
  wrapper.unmount()
})
