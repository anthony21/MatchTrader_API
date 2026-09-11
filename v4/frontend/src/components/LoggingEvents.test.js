import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import LoggingEvents from './LoggingEvents.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
vi.mock('../stream.js', () => ({ followNativeEvents: vi.fn(() => () => {}) }))
test('shows logged intent and pages archived messages without trading controls', async () => {
  request.mockResolvedValue({ records: [{ seq: 4, source: 'X17', preview: 'unfamiliar payload', received_at: '2026-09-11T06:34:00Z' }], next_before: 4, count: 1 })
  const w = mount(LoggingEvents); await flushPromises()
  expect(w.text()).toContain('X17'); expect(w.text()).toContain('Logging only')
  await w.findAll('button')[1].trigger('click'); await flushPromises()
  expect(request).toHaveBeenLastCalledWith('logging/events?before=4')
  w.unmount()
})
