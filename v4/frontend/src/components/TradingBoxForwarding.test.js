import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import TradingBoxForwarding from './TradingBoxForwarding.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

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

test('a standalone mount reads forwarding status once and never on a timer', async () => {
  vi.useFakeTimers()
  request.mockResolvedValue({ url: '', enabled: false, live: false, key_configured: false, generation: 0 })
  const w = mount(TradingBoxForwarding); await flushPromises()
  expect(request).toHaveBeenCalledTimes(1)
  expect(request).toHaveBeenCalledWith('tradingbox-forwarding')
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).toHaveBeenCalledTimes(1)
  w.unmount()
})

test('a pushed status is applied without any fetch and follows later pushes', async () => {
  vi.useFakeTimers()
  const pushed = { url: 'https://tb.example/api', enabled: true, live: false, key_configured: true, generation: 3 }
  const w = mount(TradingBoxForwarding, { props: { pushed } }); await flushPromises()
  expect(request).not.toHaveBeenCalled()
  expect(w.text()).toContain('Preview · no signals sent')
  expect(w.find('input').element.value).toBe('https://tb.example/api')
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).not.toHaveBeenCalled()
  await w.setProps({ pushed: { ...pushed, live: true, generation: 4 } })
  expect(w.text()).toContain('LIVE · sending new signals to TradingBox')
  // An older generation never overwrites a newer one.
  await w.setProps({ pushed: { ...pushed, live: false, generation: 2 } })
  expect(w.text()).toContain('LIVE · sending new signals to TradingBox')
  w.unmount()
})
