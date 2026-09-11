import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import BrokerProfiles from './BrokerProfiles.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))

test('shows platform names only and changes login state with platform', async () => {
  const profiles = [
    { profile: 'MTR', label: 'Aqua Funded', login_status: 'connected', accounts: [{ id: '1' }], revision: 0 },
    { profile: 'GTR', label: 'Gooey Trade', login_status: 'expired', accounts: [], revision: 0 },
  ]
  request.mockResolvedValue({ profiles })
  const w = mount(BrokerProfiles); await flushPromises()
  const picker = w.find('.login-picker')
  expect(picker.find('select').findAll('option').map(o => o.text())).toEqual(['Aqua Funded', 'Gooey Trade'])
  expect(picker.find('button').text()).toBe('Logged in')
  expect(picker.find('button').attributes('disabled')).toBeDefined()
  await picker.find('select').setValue('GTR')
  expect(picker.findAll('select')).toHaveLength(1)
  expect(picker.text()).toContain('Session expired')
  await picker.find('button').trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'GTR', action: 'refresh_login' })
  w.unmount()
})
test('keeps same account IDs separated by broker profile and routes controls explicitly', async () => {
  const profiles = [
    { profile: 'MTR', broker: 'https://one.example', account_id: '123', connection: 'disconnected', revision: 0 },
    { profile: 'GTR', broker: 'https://two.example', account_id: '123', connection: 'connected', revision: 0 },
  ]
  request.mockResolvedValue({ profiles })
  const w = mount(BrokerProfiles); await flushPromises()
  expect(w.findAll('.broker-card')).toHaveLength(1)
  await w.find('.login-picker select').setValue('GTR')
  const gtr = w.find('.broker-card')
  await gtr.find('button').trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'GTR', action: 'refresh' })
  expect(w.find('.broker-card').text()).not.toContain('one.example')
  w.unmount()
})

test('profile login reveals only its returned accounts and selection sends both identities', async () => {
  const profiles = [
    { profile: 'MTR', broker: 'https://one.example', accounts: [], revision: 0 },
    { profile: 'GTR', broker: 'https://two.example', accounts: [], revision: 0 },
  ]
  request.mockImplementation(async (path, payload) => {
    if (payload?.action === 'login') {
      profiles[1] = { ...profiles[1], accounts: [{ id: '646133', demo: true }, { id: '222' }], revision: 1 }
    }
    return { profiles }
  })
  const w = mount(BrokerProfiles); await flushPromises()
  const picker = w.find('.login-picker')
  await picker.find('select').setValue('GTR')
  await picker.find('button').trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'GTR', action: 'login' })
  expect(picker.findAll('select')[1].text()).toContain('646133')
  await picker.findAll('select')[1].setValue('222')
  await picker.findAll('button')[1].trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'GTR', action: 'select', account_id: '222' })
  await picker.find('select').setValue('MTR')
  expect(picker.findAll('select')).toHaveLength(1)
  expect(picker.text()).not.toContain('646133')
  w.unmount()
})
