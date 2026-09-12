import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import CopyControls from './CopyControls.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })

const pushed = { mode: 'paper', sources: { P01: true, X17: false, MANUAL: false } }
const master = wrapper => wrapper.find('button.master')

test('an absent section renders the safe reading, disabled, and fetches nothing', async () => {
  vi.useFakeTimers()
  const wrapper = mount(CopyControls)
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).not.toHaveBeenCalled()
  expect(wrapper.findAll('input')).toHaveLength(0)
  expect(master(wrapper).element.disabled).toBe(true)
  expect(wrapper.classes()).not.toContain('live')
  wrapper.unmount()
})

test('pushed mode updates the one switch without fetching or extra source switches', async () => {
  const wrapper = mount(CopyControls, { props: { pushed } })
  expect(request).not.toHaveBeenCalled()
  expect(wrapper.findAll('input')).toHaveLength(0)
  await wrapper.setProps({ pushed: { ...pushed, mode: 'live' } })
  expect(master(wrapper).text()).toBe('Live')
  wrapper.unmount()
})

test('the Live or Paper switch posts the real broker copy control in one click', async () => {
  request.mockImplementation(async (_, body) => body)
  const wrapper = mount(CopyControls, { props: { pushed } })
  expect(master(wrapper).text()).toBe('Paper')
  await master(wrapper).trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('copy-controls', { mode: 'live', sources: pushed.sources })
  expect(master(wrapper).text()).toBe('Live')
  expect(master(wrapper).attributes('aria-checked')).toBe('true')
  await master(wrapper).trigger('click'); await flushPromises()
  expect(request).toHaveBeenLastCalledWith('copy-controls', { mode: 'paper', sources: pushed.sources })
  expect(master(wrapper).text()).toBe('Paper')
  wrapper.unmount()
})

test('a failed save shows the server text and keeps the last known state', async () => {
  request.mockRejectedValue(new Error('Live mode needs a connected broker account'))
  const wrapper = mount(CopyControls, { props: { pushed } })
  await master(wrapper).trigger('click')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toBe('Live mode needs a connected broker account')
  expect(wrapper.classes()).not.toContain('live')
  expect(master(wrapper).text()).toBe('Paper')
  wrapper.unmount()
})
