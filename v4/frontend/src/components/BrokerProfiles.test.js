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

test('balance is never polled; it refreshes only when the operator clicks', async () => {
  vi.useFakeTimers()
  const p = { profile: 'AQF', label: 'Aqua', login_status: 'connected', connection: 'connected', account_id: '1',
    accounts: [{ id: '1' }], orders: [], positions: [], balance: { balance: '100', equity: '100', currency: 'USD' }, revision: 0 }
  request.mockResolvedValue({ profiles: [{ ...p, revision: 1 }] })
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [p], active_profile: 'AQF' } } })
  await flushPromises()
  // nothing open, so no poll of any kind for a long while
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).not.toHaveBeenCalled()
  // the manual button reads balance only
  await w.find('.balance-refresh').trigger('click'); await flushPromises()
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'AQF', action: 'balance' })
  expect(request).toHaveBeenCalledTimes(1)
  w.unmount()
})

test('pending orders poll every 200ms and open positions every 5s, each only while it has any', async () => {
  vi.useFakeTimers()
  const base = { profile: 'AQF', label: 'Aqua', login_status: 'connected', connection: 'connected', account_id: '1',
    accounts: [{ id: '1' }], orders: [{ id: 'o1' }], positions: [{ id: 'p1' }], revision: 0 }
  request.mockImplementation(async (_p, body) => ({ profiles: [{ ...base, revision: 1 }] }))
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [base], active_profile: 'AQF' } } })
  await flushPromises()
  // one 200ms tick: exactly one orders poll, no positions poll yet, no balance
  await vi.advanceTimersByTimeAsync(200)
  const actions = () => request.mock.calls.map(c => c[1].action)
  expect(actions().filter(a => a === 'orders').length).toBe(1)
  expect(actions()).not.toContain('positions')
  expect(actions()).not.toContain('balance')
  // by 5s: orders polled many times (~25), positions once
  await vi.advanceTimersByTimeAsync(5000)
  const orders = actions().filter(a => a === 'orders').length
  const positions = actions().filter(a => a === 'positions').length
  expect(orders).toBeGreaterThan(15)
  expect(positions).toBe(1)
  // when nothing is open, both cadences stop
  request.mockResolvedValue({ profiles: [{ ...base, orders: [], positions: [], revision: 2 }] })
  await vi.advanceTimersByTimeAsync(5000)   // let the empties arrive
  const settled = request.mock.calls.length
  await vi.advanceTimersByTimeAsync(10000)
  expect(request.mock.calls.length).toBe(settled)
  w.unmount()
})

test('a poll never locks the operator buttons or relabels the login button', async () => {
  vi.useFakeTimers()
  const p = { profile: 'AQF', label: 'Aqua', login_status: 'connected', connection: 'connected', account_id: '1',
    accounts: [{ id: '1' }], orders: [{ id: 'o1' }], positions: [], revision: 0 }
  let release
  request.mockImplementation(() => new Promise(resolve => { release = () => resolve({ profiles: [{ ...p, revision: 1 }] }) }))
  const w = mount(BrokerProfiles, { props: { pushed: { profiles: [p], active_profile: 'AQF' } } })
  await flushPromises()
  await vi.advanceTimersByTimeAsync(200)          // an orders poll is now in flight
  expect(request).toHaveBeenCalledWith('broker-profiles/action', { profile: 'AQF', action: 'orders' })
  expect(w.findAll('.broker-actions button')[0].element.disabled).toBe(false)
  expect(w.find('.login-picker button').text()).not.toBe('Working…')
  release(); await flushPromises()
  w.unmount()
})
