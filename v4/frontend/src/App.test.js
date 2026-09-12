import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.vue'
import { request } from './api.js'
import { followDashboard } from './stream.js'

vi.mock('./stream.js', () => ({ followDashboard: vi.fn(() => () => {}), followNativeEvents: vi.fn(() => () => {}) }))
vi.mock('./api.js', () => ({ request: vi.fn() }))
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })

// The shell is push-only: every test hands it stream snapshots instead of fetches.
// `deliver` merges later frames the way followDashboard does, so a frame may carry one section.
function push(sections, { live = true, stop = vi.fn() } = {}) {
  const feed = { stop, deliver: () => {} }
  followDashboard.mockImplementationOnce((onSnapshot, onState) => {
    let merged = {}
    feed.deliver = more => { merged = { ...merged, ...more }; onSnapshot(merged) }
    if (live) onState('live')
    feed.deliver(sections)
    return stop
  })
  return feed
}
const forwarding = { enabled: false, live: false, url: '', key_configured: false, generation: 0 }
const idle = { accounts: [{ id: '123' }], account_id: '123', connection: 'connected', running: true,
  orders: [], positions: [], tradingbox_forwarding: forwarding }
const full = {
  status: idle,
  events: { account_id: '123', events: [] },
  capture_events: { events: [] },
  mappings: { account_id: '123', mappings: [] },
  broker_profiles: { profiles: [{ profile: 'MTR', label: 'Aqua Funded', login_status: 'connected', accounts: [{ id: '123' }], revision: 0 }], limit: 5, active_profile: 'MTR' },
}

test('a freshly mounted shell issues no request at all while nothing is pending or open', async () => {
  vi.useFakeTimers()
  push(full)
  const wrapper = mount(App)
  await flushPromises()
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).not.toHaveBeenCalled()
  expect(followDashboard).toHaveBeenCalledOnce()
  expect(wrapper.find('select').element.value).toBe('123')
  wrapper.unmount()
})

test('broker orders and positions refresh only while something is pending or open, then stop by themselves', async () => {
  vi.useFakeTimers()
  const feed = push({ status: { ...idle, orders: [{ id: 'o1' }] } })
  request.mockResolvedValue(idle)
  const wrapper = mount(App)
  await flushPromises()
  expect(request).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(5000)
  expect(request).toHaveBeenCalledWith('orders/refresh', { account_id: '123' })
  expect(request).toHaveBeenCalledWith('positions/refresh', { account_id: '123' })
  expect(request).toHaveBeenCalledTimes(2)
  // The broker answered that nothing is pending or open, so the refresh stops on its own.
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).toHaveBeenCalledTimes(2)
  // A pushed status showing an open position arms it again.
  request.mockResolvedValue({ ...idle, positions: [{ id: 'p1' }] })
  feed.deliver({ status: { ...idle, positions: [{ id: 'p1' }] } })
  await vi.advanceTimersByTimeAsync(5000)
  expect(request).toHaveBeenCalledTimes(4)
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).toHaveBeenCalledTimes(4)
})

test('status, events, mappings and broker profiles are never fetched, even with an account connected', async () => {
  push(full)
  request.mockResolvedValue(idle)
  const wrapper = mount(App)
  await flushPromises()
  for (const label of ['Orders', 'Broker accounts', 'Trading bridge']) {
    await wrapper.findAll('button').find(b => b.text() === label).trigger('click')
    await flushPromises()
  }
  const fetched = request.mock.calls.map(([path]) => path)
  for (const path of ['status', 'events', 'capture/events', 'trade-mappings', 'broker-profiles']) expect(fetched).not.toContain(path)
  wrapper.unmount()
})

test('Orders keeps the v4 workspace and reads the broker once on opening while connected', async () => {
  push(full)
  request.mockResolvedValue(idle)
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Orders').trigger('click')
  await flushPromises()
  expect(wrapper.find('h1').text()).toBe('Orders & positions')
  expect(request).toHaveBeenCalledWith('orders/refresh', { account_id: '123' })
  expect(request).toHaveBeenCalledWith('positions/refresh', { account_id: '123' })
  expect(request).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain('Open positions')
  expect(wrapper.text()).toContain('Copy activity')
  expect(wrapper.text()).toContain('Closed trades')
  wrapper.unmount()
})

test('Trading bridge keeps account controls, status grid and token panel, and start posts the selected account', async () => {
  const status = { accounts: [{ id: '123', verified: false }], account_id: '123', connection: 'disconnected',
    running: false, orders: [], orders_at: null, broker_orders_sent: 0, tradingbox_forwarding: { enabled: true, live: false } }
  push({ status, events: { account_id: '123', events: [] } })
  request.mockResolvedValue(status)
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('select').element.value).toBe('123')
  expect(wrapper.text()).toContain('API trading off')
  expect(wrapper.text()).toContain('TradingBox preview')
  expect(wrapper.find('[aria-label="Service status"]').exists()).toBe(true)
  for (const label of ['BRIDGE', 'BROKER CONNECTION', 'ACCOUNT IN VIEW']) expect(wrapper.text()).toContain(label)
  expect(wrapper.findAll('button').some(b => b.text() === 'Refresh token')).toBe(true)
  expect(request).not.toHaveBeenCalled()
  await wrapper.find('button.primary').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledWith('start', { account_id: '123' })
  wrapper.unmount()
})

test('refresh token button calls the login refresh route for the selected account', async () => {
  const status = { ...idle, accounts: [{ id: '123', verified: true }], token_refresh_available: true, token_expires_at: '2030-01-01T00:00:00Z' }
  push({ status })
  request.mockResolvedValue(status)
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Refresh token').trigger('click')
  await flushPromises()
  expect(request).toHaveBeenCalledWith('token/refresh', { account_id: '123' })
  expect(wrapper.find('select').element.value).toBe('123')
  wrapper.unmount()
})

test('live snapshots update native rows without polling and unsubscribe on unmount', async () => {
  const { stop } = push({
    status: { ...idle, connection: 'disconnected' },
    capture_events: { events: [{ id: 'push', symbol: 'PUSHED', kind: 'POSITION' }] },
    events: { account_id: '123', events: [] },
  })
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.text()).toContain('PUSHED')
  expect(wrapper.text()).toContain('Live push')
  expect(request).not.toHaveBeenCalled()
  wrapper.unmount()
  expect(stop).toHaveBeenCalledOnce()
})

test('a frame carrying one section leaves the others in place and unchanged sections are not re-applied', async () => {
  const status = { ...idle, connection: 'disconnected', accounts: [{ id: '123' }, { id: '456' }] }
  const feed = push({ status, capture_events: { events: [{ id: 'one', symbol: 'FIRST', kind: 'POSITION' }] } })
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.find('select').setValue('456')
  // Only capture_events changed; the merged snapshot still carries the same status object.
  feed.deliver({ capture_events: { events: [{ id: 'two', symbol: 'SECOND', kind: 'POSITION' }] } })
  await flushPromises()
  expect(wrapper.text()).toContain('SECOND')
  expect(wrapper.text()).toContain('API trading off')
  expect(wrapper.find('select').element.value).toBe('456')
  // A new status object is applied and moves the selection with the account in view.
  feed.deliver({ status: { ...status, account_id: '789', accounts: [{ id: '123' }, { id: '456' }, { id: '789' }] } })
  await flushPromises()
  expect(wrapper.find('select').element.value).toBe('789')
  expect(wrapper.text()).toContain('SECOND')
  wrapper.unmount()
})

test('every v4 page still renders its workspace from pushed sections', async () => {
  push(full)
  request.mockImplementation(async path => {
    if (path.startsWith('logging/events')) return { records: [], next_before: 0 }
    if (path === 'copy-settings') return { inventory: [], csv_limit: 1000, route: null }
    if (path === 'signal-copy-settings') return { config: null, live: false }
    return idle
  })
  const wrapper = mount(App)
  await flushPromises()
  const open = async label => { await wrapper.findAll('button').find(b => b.text() === label).trigger('click'); await flushPromises() }
  await open('Broker accounts')
  expect(wrapper.find('h1').text()).toBe('Broker accounts')
  expect(wrapper.text()).toContain('Aqua Funded')
  expect(wrapper.find('.login-picker button').text()).toBe('Logged in')
  await open('Event logging')
  expect(wrapper.find('h1').text()).toBe('Event logging')
  expect(wrapper.find('.logging-page').exists()).toBe(true)
  await open('Raw events')
  expect(wrapper.find('h1').text()).toBe('Raw events')
  expect(wrapper.find('[aria-label="Raw event monitor"]').exists()).toBe(true)
  expect(wrapper.find('details summary').text()).toBe('Recent signal activity')
  await open('Copy settings')
  expect(wrapper.find('h1').text()).toBe('Copy settings')
  expect(wrapper.find('.copy-settings').exists()).toBe(true)
  expect(wrapper.find('[aria-label="TradingBox forwarding"]').exists()).toBe(true)
  expect(wrapper.find('[aria-label="Signal copy settings"]').exists()).toBe(true)
  expect(wrapper.find('[aria-label="Service status"]').exists()).toBe(true)
  await open('Orders')
  expect(wrapper.text()).toContain('Open positions')
  await open('Trading bridge')
  expect(wrapper.find('h1').text()).toBe('Trading bridge')
  expect(wrapper.text()).toContain('Live push')
  const fetched = request.mock.calls.map(([path]) => path)
  expect(fetched).not.toContain('tradingbox-forwarding')
  expect(fetched).not.toContain('broker-profiles')
  wrapper.unmount()
})

test('Raw events mounts recent signal activity only when its own section is expanded', async () => {
  push({ status: { ...idle, connection: 'disconnected' } })
  request.mockImplementation(async path => path === 'signal-copy-events' ? { events: [] } : idle)
  const wrapper = mount(App, { global: { stubs: { RawEvents: true } } })
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Raw events').trigger('click')
  await flushPromises()
  const section = wrapper.find('details')
  expect(section.find('summary').text()).toBe('Recent signal activity')
  expect(request).not.toHaveBeenCalledWith('signal-copy-events')
  section.element.open = true
  await section.trigger('toggle'); await flushPromises()
  expect(request).toHaveBeenCalledWith('signal-copy-events')
  expect(wrapper.find('[aria-label="Recent signal activity"]').exists()).toBe(true)
  section.element.open = false
  await section.trigger('toggle')
  expect(wrapper.find('[aria-label="Recent signal activity"]').exists()).toBe(false)
  wrapper.unmount()
})

const ledgerRow = { trade_id: 'v1', state: 'verified_open', verified: true, symbol: 'VERIFIEDSYM', side: 'BUY', lots: '0.10', source_enabled: true,
  source: { code: 'X17', scope: ['m', 'c', 's'], order_ids: ['qt-1'], position_ids: [] },
  destination: { broker: 'AquaFunded', account_id: '123', order_ids: ['aq-1'], position_ids: ['aq-p1'] },
  timestamps: { sent_at: '2026-09-11T10:00:00Z', confirmed_at: '2026-09-11T10:00:01Z', broker_open: '2026-09-11T10:00:02Z', broker_open_millis: null },
  read_back: { reader: 'positions', volume: '0.10', open_price: '1.1' }, pamm: null, cancellation: null, mapping_status: 'mapped', reasons: [] }
const paperRow = { trade_id: 'p1', source: 'P01', symbol: 'PAPERSYM', side: 'SELL', lots: '0.20', request: { symbol: 'PAPERSYM' },
  verdict: 'would_send', reason: 'Mapping resolved', decided_at: '2026-09-11T10:00:00Z' }

test('Verified trades and Paper trades render from pushed sections, stay separate, and open without any request', async () => {
  vi.useFakeTimers()
  push({ ...full, copy_controls: { mode: 'live', sources: { P01: true, X17: true, MANUAL: false } },
    verified_trades: { account_id: '123', rows: [ledgerRow] }, paper_sends: { account_id: '123', rows: [paperRow] } })
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('.mode-pill').text()).toContain('Copy LIVE')
  const open = async label => { await wrapper.findAll('button').find(b => b.text() === label).trigger('click'); await flushPromises() }
  await open('Verified trades')
  expect(wrapper.find('h1').text()).toBe('Verified trades')
  expect(wrapper.find('[aria-label="Copy controls"]').classes()).toContain('live')
  expect(wrapper.find('[aria-label="Verified trades"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('VERIFIEDSYM')
  expect(wrapper.text()).not.toContain('PAPERSYM')
  expect(wrapper.find('[aria-label="Service status"]').exists()).toBe(false)
  await open('Paper trades')
  expect(wrapper.find('h1').text()).toBe('Paper trades')
  expect(wrapper.find('[aria-label="Paper trades"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('PAPERSYM')
  expect(wrapper.text()).not.toContain('VERIFIEDSYM')
  await vi.advanceTimersByTimeAsync(30000)
  expect(request).not.toHaveBeenCalled()
  wrapper.unmount()
})

test('without the ledger sections the new pages render the safe, honest empty states', async () => {
  push(full)
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('.mode-pill').text()).toContain('Copy paper')
  await wrapper.findAll('button').find(b => b.text() === 'Verified trades').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('has not reported copy controls yet')
  expect(wrapper.find('[aria-label="Copy controls"] [role=status]').text()).toBe('PAPER · nothing is sent to a broker')
  expect(wrapper.text()).toContain('No verified trade records for this account yet')
  await wrapper.findAll('button').find(b => b.text() === 'Paper trades').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('No paper sends recorded for this account.')
  expect(request).not.toHaveBeenCalled()
  wrapper.unmount()
})

test('a page query opens that page directly', async () => {
  window.history.replaceState({}, '', '/?page=logging')
  push(full)
  request.mockResolvedValue({ records: [], next_before: 0 })
  const wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('h1').text()).toBe('Event logging')
  wrapper.unmount()
  window.history.replaceState({}, '', '/')
})
