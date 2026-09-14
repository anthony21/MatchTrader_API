import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import BrokerProfiles from './BrokerProfiles.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

// Profiles arrive as a pushed dashboard section; the component never fetches them.
test('a discovered login can finish connecting and retains its balance after page remount', async () => {
  const row = { profile: 'AQF', label: 'Aqua', login_status: 'connected', connection: 'disconnected', accounts: [{ id: '123' }], revision: 1 }
  const connected = { ...row, connection: 'connected', balance: { balance: '100', currency: 'USD' }, revision: 2 }
  request.mockResolvedValue({ profiles: [connected] })
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [row] } } })
  await flushPromises()
  const button = w.find('.login-picker button')
  expect(button.text()).toBe('Connect account')
  expect(button.element.disabled).toBe(false)
  await button.trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'AQF', action: 'login' })
  expect(w.text()).toContain('100 USD')
  w.unmount()
  request.mockClear()
  const remounted = mount(BrokerProfiles, { props: { pushed: { profiles: [connected] } } })
  await flushPromises()
  expect(remounted.text()).toContain('100 USD')
  expect(request).not.toHaveBeenCalled()
  remounted.unmount()
})

test('shows platform names only and changes login state with platform', async () => {
  const profiles = [
    { profile: 'AQF', label: 'Aqua Funded', login_status: 'connected', connection: 'connected', accounts: [{ id: '1' }], revision: 0 },
    { profile: 'GTR', label: 'Gooey Trade', login_status: 'expired', accounts: [], revision: 0 },
  ]
  request.mockResolvedValue({ profiles })
  const w = mount(BrokerProfiles, { props: { pushed: { profiles, limit: 5, active_profile: 'AQF' } } }); await flushPromises()
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
    { profile: 'AQF', broker: 'https://one.example', account_id: '123', connection: 'disconnected', revision: 0 },
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
    { profile: 'AQF', broker: 'https://one.example', accounts: [], revision: 0 },
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
  await picker.find('select').setValue('AQF')
  expect(picker.findAll('select')).toHaveLength(1)
  expect(picker.text()).not.toContain('646133')
  w.unmount()
})

test('follows the pushed active profile and later pushes without fetching', async () => {
  const first = { profiles: [{ profile: 'AQF', label: 'Aqua', revision: 0 }, { profile: 'GTR', label: 'Gooey', revision: 0 }], active_profile: 'GTR' }
  const w = mount(BrokerProfiles, { props: { pushed: first } }); await flushPromises()
  expect(w.find('.login-picker select').element.value).toBe('GTR')
  await w.setProps({ pushed: { profiles: [{ profile: 'GTR', label: 'Gooey', balance: { balance: '10', equity: '10', currency: 'USD' }, revision: 1 }] } })
  expect(w.find('.login-picker select').findAll('option').map(o => o.text())).toEqual(['Gooey'])
  expect(w.text()).toContain('10 USD')
  expect(request).not.toHaveBeenCalled()
  w.unmount()
})

test('a background refresh never locks or relabels the buttons; only an operator action does', async () => {
  vi.useFakeTimers()
  const working = { profile: 'AQF', label: 'Aqua', login_status: 'connected', connection: 'connected', account_id: '1',
    accounts: [{ id: '1' }], orders: [{ id: 'o1' }], positions: [], revision: 0 }
  let release
  request.mockImplementation(() => new Promise(resolve => { release = () => resolve({ profiles: [{ ...working, revision: 1 }] }) }))
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [working] } } })
  await flushPromises()
  await vi.advanceTimersByTimeAsync(5000)          // the background read is now in flight
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'AQF', action: 'refresh' })
  const refresh = w.findAll('.broker-actions button')[0]
  expect(refresh.element.disabled).toBe(false)
  expect(w.find('.login-picker button').text()).not.toBe('Working…')
  expect(w.find('.refreshing').text()).toContain('Refreshing')
  release(); await flushPromises()
  expect(w.find('.refreshing').exists()).toBe(false)
  // An operator click locks the buttons while it runs.
  request.mockImplementation(() => new Promise(resolve => { release = () => resolve({ profiles: [{ ...working, revision: 2 }] }) }))
  await refresh.trigger('click'); await flushPromises()
  expect(w.findAll('.broker-actions button')[0].element.disabled).toBe(true)
  release(); await flushPromises()
  expect(w.findAll('.broker-actions button')[0].element.disabled).toBe(false)
  w.unmount()
})

test('refreshes broker data only while a connected profile has something pending or open, then stops', async () => {
  vi.useFakeTimers()
  const working = { profile: 'AQF', connection: 'connected', orders: [{ id: 'o1' }], positions: [], revision: 0 }
  request.mockResolvedValue({ profiles: [{ ...working, orders: [] }] })
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [working] } } })
  await flushPromises()
  expect(request).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(5000)
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'AQF', action: 'refresh' })
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
