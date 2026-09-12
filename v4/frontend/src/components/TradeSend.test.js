import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import TradeSend from './TradeSend.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })

const candidate = { trade_id: 't1', state: 'candidate', lots: '0.10', source_enabled: true, source: { code: 'P01' } }

test('send posts exactly once per click with the edited volume, and never on mount or on a timer', async () => {
  vi.useFakeTimers()
  request.mockResolvedValue({ state: 'paper_sent' })
  const wrapper = mount(TradeSend, { props: { row: candidate, mode: 'paper' } })
  await vi.advanceTimersByTimeAsync(60000)
  expect(request).not.toHaveBeenCalled()
  await wrapper.find('input').setValue('0.25')
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledTimes(1)
  expect(request).toHaveBeenCalledWith('trades/send', { trade_id: 't1', volume: '0.25' })
  expect(wrapper.text()).toContain('Paper send recorded · no broker order was placed')
  // A second explicit click is a second send; a stream replacing the row is not.
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledTimes(2)
  await wrapper.setProps({ row: { ...candidate, lots: '0.30' } })
  await vi.advanceTimersByTimeAsync(60000)
  expect(request).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

test('a click while a send is in flight does not post a second time', async () => {
  let release
  request.mockImplementation(() => new Promise(resolve => { release = resolve }))
  const wrapper = mount(TradeSend, { props: { row: candidate, mode: 'live' } })
  await wrapper.find('button').trigger('click')
  await wrapper.find('button').trigger('click')
  expect(wrapper.find('button').element.disabled).toBe(true)
  release({})
  await flushPromises()
  expect(request).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('Live order submitted · awaiting broker read-back')
  wrapper.unmount()
})

test('paper mode is stated on the button; live mode is stated too', async () => {
  const paper = mount(TradeSend, { props: { row: candidate, mode: 'paper' } })
  expect(paper.find('button').text()).toBe('Send as paper · no broker order')
  expect(paper.text()).toContain('sends nothing to a broker')
  paper.unmount()
  const live = mount(TradeSend, { props: { row: candidate, mode: 'live' } })
  expect(live.find('button').text()).toBe('Send LIVE order')
  expect(live.find('button').classes()).toContain('send-live')
  live.unmount()
})

test('send is disabled for a disabled source and for a non-candidate, and the reason is shown', () => {
  const off = mount(TradeSend, { props: { row: { ...candidate, source_enabled: false } } })
  expect(off.find('button').element.disabled).toBe(true)
  expect(off.find('input').element.disabled).toBe(true)
  expect(off.text()).toContain('Source P01 is off in copy controls.')
  off.unmount()
  const done = mount(TradeSend, { props: { row: { ...candidate, state: 'sent_unconfirmed' } } })
  expect(done.find('button').element.disabled).toBe(true)
  expect(done.text()).toContain('Only a candidate can be sent.')
  done.unmount()
  expect(request).not.toHaveBeenCalled()
})

test('the server error text is surfaced inline and a zero volume is refused before any request', async () => {
  request.mockRejectedValue(new Error('Source X17 is disabled by copy controls'))
  const wrapper = mount(TradeSend, { props: { row: candidate } })
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toBe('Source X17 is disabled by copy controls')
  expect(request).toHaveBeenCalledTimes(1)
  await wrapper.find('input').setValue('0')
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toBe('Enter a lot size greater than zero.')
  expect(request).toHaveBeenCalledTimes(1)
  // An error without a message still names the trade rather than saying "unknown".
  request.mockRejectedValue(new Error(''))
  await wrapper.find('input').setValue('0.5')
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toBe('Send of t1 failed and the local API returned no message.')
  wrapper.unmount()
})
