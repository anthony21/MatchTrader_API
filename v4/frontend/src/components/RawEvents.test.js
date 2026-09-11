import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import RawEvents from './RawEvents.vue'
import { followNativeEvents } from '../stream.js'
vi.mock('../stream.js', () => ({ followNativeEvents: vi.fn() }))
afterEach(() => vi.clearAllMocks())

test('streams raw messages, filters, pauses display and releases the connection', async () => {
  let deliver
  const stop = vi.fn()
  followNativeEvents.mockImplementation((events, status, path) => {
    expect(path).toBe('raw/stream'); deliver = events; status('live'); return stop
  })
  const wrapper = mount(RawEvents, { props: { state: { capture_websocket: { connected_senders: 1 } } } })
  const row = { id: 1, direction: 'in', transport: 'websocket', received_at: '2026-09-10T12:00:00Z', raw: '{"type":"event","event":{"source":"X17"}}' }
  deliver([row]); await wrapper.vm.$nextTick()
  expect(wrapper.text()).toContain('X17')
  expect(wrapper.text()).toContain('Memory only')
  await wrapper.find('input').setValue('R01'); expect(wrapper.findAll('details')).toHaveLength(0)
  await wrapper.find('input').setValue(''); await wrapper.find('button').trigger('click')
  deliver([{ ...row, id: 2, raw: '{"type":"nack","code":"invalid_event"}' }]); await wrapper.vm.$nextTick()
  expect(wrapper.text()).toContain('X17')
  await wrapper.find('button').trigger('click'); expect(wrapper.text()).toContain('invalid_event')
  await wrapper.find('select').setValue('out'); expect(wrapper.findAll('details')).toHaveLength(0)
  wrapper.unmount(); expect(stop).toHaveBeenCalledOnce()
})
