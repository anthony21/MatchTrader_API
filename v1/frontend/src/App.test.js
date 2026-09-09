import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.vue'
import { request } from './api.js'

vi.mock('./api.js', () => ({ request: vi.fn() }))
afterEach(() => vi.clearAllMocks())
test('loads selected account and incoming events, then starts the shadow bridge', async () => {
  const state = { accounts: [{ id: '123', verified: false }], account_id: '123', connection: 'disconnected',
    running: false, orders: [], orders_at: null, broker_orders_sent: 0 }
  request.mockImplementation(async path => path === 'events' ? { account_id: '123', events: [] } : state)
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('select').element.value).toBe('123')
  expect(wrapper.text()).toContain('Shadow mode')
  await wrapper.find('button.primary').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledWith('start', { account_id: '123' })
  wrapper.unmount()
})
