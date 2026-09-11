import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import BrokerProfiles from './BrokerProfiles.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
test('keeps same account IDs separated by broker profile and routes controls explicitly', async () => {
  const profiles = [
    { profile: 'MTR', broker: 'https://one.example', account_id: '123', connection: 'disconnected', revision: 0 },
    { profile: 'GTR', broker: 'https://two.example', account_id: '123', connection: 'disconnected', revision: 0 },
  ]
  request.mockResolvedValue({ profiles })
  const w = mount(BrokerProfiles); await flushPromises()
  expect(w.findAll('.broker-card')).toHaveLength(2)
  const gtr = w.findAll('.broker-card')[1]
  await gtr.find('button').trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'GTR', action: 'connect' })
  expect(w.findAll('.broker-card')[0].text()).not.toContain('two.example')
  w.unmount()
})
