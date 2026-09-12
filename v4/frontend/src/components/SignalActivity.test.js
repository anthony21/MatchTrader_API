import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import SignalActivity from './SignalActivity.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
test('Orders signal activity shows decision and full request response on demand', async () => {
  request.mockResolvedValue({ events: [{ machineId: 'qt', clientEventId: 'one', kind: 'intent', status: 'accepted', reason: 'Broker accepted', copy_request: { volume: '0.2' } }] })
  const wrapper = mount(SignalActivity)
  await flushPromises()
  expect(wrapper.text()).toContain('Broker accepted')
  expect(wrapper.find('pre').text()).toContain('0.2')
  expect(request).toHaveBeenCalledWith('signal-copy-events')
  wrapper.unmount()
})
