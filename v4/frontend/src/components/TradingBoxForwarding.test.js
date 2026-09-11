import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import TradingBoxForwarding from './TradingBoxForwarding.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
test('forwarding starts off and requires a separate explicit Live action', async () => {
  let state = { url: 'https://tradingbox.pro/api/hcamm/events', enabled: false, live: false, key_configured: true, generation: 0 }
  request.mockImplementation(async (_, body) => {
    if (body) state = { ...state, ...body, generation: state.generation + 1 }
    return state
  })
  const w = mount(TradingBoxForwarding); await flushPromises()
  expect(w.text()).toContain('Off · logging only')
  await w.findAll('button')[1].trigger('click'); await flushPromises()
  expect(w.text()).toContain('Preview · no signals sent')
  expect(state.live).toBe(false)
  await w.findAll('button')[2].trigger('click'); await flushPromises()
  expect(state.live).toBe(true)
  await w.findAll('button')[1].trigger('click'); await flushPromises()
  expect(state.enabled).toBe(false); expect(state.live).toBe(false)
  w.unmount()
})
