import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import BrokerProfiles from './BrokerProfiles.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

// Profiles arrive as a pushed dashboard section; the component never fetches them.
test('shows platform names only and changes login state with platform', async () => {
  const profiles = [
    { profile: 'MTR', label: 'Aqua Funded', login_status: 'connected', accounts: [{ id: '1' }], revision: 0 },
    { profile: 'GTR', label: 'Gooey Trade', login_status: 'expired', accounts: [], revision: 0 },
  ]
  request.mockResolvedValue({ profiles })
  const w = mount(BrokerProfiles, { props: { pushed: { profiles, limit: 5, active_profile: 'MTR' } } }); await flushPromises()
  expect(request).not.toHaveBeenCalled()
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
  const w = mount(BrokerProfiles, { props: { pushed: { profiles } } }); await flushPromises()
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
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [...profiles] } } }); await flushPromises()
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

test('follows the pushed active profile and later pushes without fetching', async () => {
  const first = { profiles: [{ profile: 'MTR', label: 'Aqua', revision: 0 }, { profile: 'GTR', label: 'Gooey', revision: 0 }], active_profile: 'GTR' }
  const w = mount(BrokerProfiles, { props: { pushed: first } }); await flushPromises()
  expect(w.find('.login-picker select').element.value).toBe('GTR')
  await w.setProps({ pushed: { profiles: [{ profile: 'GTR', label: 'Gooey', balance: { balance: '10', equity: '10', currency: 'USD' }, revision: 1 }] } })
  expect(w.find('.login-picker select').findAll('option').map(o => o.text())).toEqual(['Gooey'])
  expect(w.text()).toContain('10 USD')
  expect(request).not.toHaveBeenCalled()
  w.unmount()
})

test('refreshes broker data only while a connected profile has something pending or open, then stops', async () => {
  vi.useFakeTimers()
  const working = { profile: 'MTR', connection: 'connected', orders: [{ id: 'o1' }], positions: [], revision: 0 }
  request.mockResolvedValue({ profiles: [{ ...working, orders: [] }] })
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [working] } } })
  await flushPromises()
  expect(request).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(5000)
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'MTR', action: 'refresh' })
  expect(request).toHaveBeenCalledTimes(1)
  // The broker reported nothing pending or open, so the timer does not re-arm.
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).toHaveBeenCalledTimes(1)
  // A pushed profile with an open position arms it again; a disconnected one does not.
  await w.setProps({ pushed: { profiles: [{ ...working, orders: [], positions: [{ id: 'p1' }], revision: 2 }] } })
  request.mockResolvedValue({ profiles: [{ ...working, connection: 'disconnected', orders: [], positions: [], revision: 3 }] })
  await vi.advanceTimersByTimeAsync(5000)
  expect(request).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).toHaveBeenCalledTimes(2)
  w.unmount()
})
