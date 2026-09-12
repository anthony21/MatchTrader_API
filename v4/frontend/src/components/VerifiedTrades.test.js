import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import VerifiedTrades from './VerifiedTrades.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => vi.clearAllMocks())

const base = {
  symbol: 'EURUSD', side: 'BUY', lots: '0.10', source_enabled: true, mapping_status: 'mapped', reasons: [],
  source: { code: 'X17', scope: ['machine', 'connection', 'source'], order_ids: ['qt-1'], position_ids: ['qt-p1'] },
  destination: { broker: 'AquaFunded', account_id: '123', order_ids: ['aq-1'], position_ids: ['aq-p1'] },
  timestamps: { sent_at: '2026-09-11T10:00:00Z', confirmed_at: '2026-09-11T10:00:01Z', broker_open: null, broker_open_millis: null },
  read_back: null, pamm: null, cancellation: null,
}
const row = (overrides) => ({ ...base, ...overrides, timestamps: { ...base.timestamps, ...(overrides.timestamps || {}) } })
const rowOf = (wrapper, id) => wrapper.find(`tr.ledger-row[data-trade="${id}"]`)

test('local-clock and broker-clock columns are separate and each is labelled with its clock', () => {
  const wrapper = mount(VerifiedTrades, { props: { rows: [row({ trade_id: 't1', state: 'candidate' })] } })
  const headers = wrapper.findAll('th').map(th => th.text())
  expect(headers.slice(0, 9)).toEqual(['Trade', 'Quantower ID', 'AquaFunded ID', 'Sentlocal clock', 'Confirmedlocal clock',
    'Aqua open timebroker clock', 'PAMMlocal clock', 'State', 'Reason · origin'])
  expect(wrapper.text()).toContain('A send response alone is not verification')
  expect(wrapper.text()).toContain('TradingBox is a third viewpoint')
  wrapper.unmount()
})

test('only verified_open and verified_closed are styled verified; read_back_no_time renders in full with the plain sentence', () => {
  const wrapper = mount(VerifiedTrades, { props: { rows: [
    row({ trade_id: 'open', state: 'verified_open', verified: true, read_back: { reader: 'positions', volume: '0.10', open_price: '1.1000' },
      timestamps: { broker_open: '2026-09-11T10:00:02Z', broker_open_millis: 1789034402000 } }),
    row({ trade_id: 'closed', state: 'verified_closed', verified: true }),
    row({ trade_id: 'notime', state: 'read_back_no_time', verified: false, read_back: { reader: 'positions', volume: '0.10', open_price: '1.1000' } }),
    row({ trade_id: 'sent', state: 'sent_unconfirmed', verified: false }),
  ] } })
  expect(rowOf(wrapper, 'open').classes()).toContain('verified')
  expect(rowOf(wrapper, 'closed').classes()).toContain('verified')
  expect(rowOf(wrapper, 'open').find('.badge.state').classes()).toContain('verified')
  const noTime = rowOf(wrapper, 'notime')
  expect(noTime.classes()).not.toContain('verified')
  expect(noTime.find('.badge.state').classes()).not.toContain('verified')
  expect(noTime.text()).toContain('The broker confirmed this position but did not report its open time.')
  expect(noTime.text()).toContain('EURUSD · BUY · 0.10 lots')
  expect(noTime.text()).toContain('aq-p1')
  expect(noTime.find('.broker-time').text()).toBe('—')
  expect(rowOf(wrapper, 'sent').find('.badge.state').classes()).not.toContain('verified')
  expect(wrapper.text()).toContain('Broker read-back by positions: volume 0.10, open price 1.1000.')
  wrapper.unmount()
})

test('a cancelled row shows its reason and origin badge, and an empty summary still renders something investigable', () => {
  const wrapper = mount(VerifiedTrades, { props: { rows: [
    row({ trade_id: 'c1', state: 'cancelled', cancellation: { origin: 'broker', outcome: 'rejected', code: 400,
      summary: 'Volume exceeds account limit', evidence: { body: { error: 'VOLUME_LIMIT' } }, at: '2026-09-11T10:00:03Z' } }),
    row({ trade_id: 'c2', state: 'rejected', cancellation: { origin: 'broker', outcome: 'rejected', code: 400, summary: '', evidence: null, at: null } }),
    row({ trade_id: 'c3', state: 'cancelled', cancellation: { origin: 'transport', outcome: 'timeout', code: null, summary: null, evidence: null, at: null } }),
  ] } })
  const withSummary = rowOf(wrapper, 'c1')
  expect(withSummary.find('.reason').text()).toContain('Volume exceeds account limit')
  expect(withSummary.find('.badge.origin').text()).toBe('broker')
  expect(wrapper.text()).toContain('VOLUME_LIMIT')
  const blankSummary = rowOf(wrapper, 'c2')
  expect(blankSummary.find('.reason').text()).toContain('HTTP 400 · broker · no message supplied')
  expect(blankSummary.find('.badge.origin').text()).toBe('broker')
  const noCode = rowOf(wrapper, 'c3')
  expect(noCode.find('.reason').text()).toContain('timeout · transport · no message supplied')
  expect(noCode.find('.badge.origin').text()).toBe('transport')
  wrapper.unmount()
})

test('a missing PAMM ack neither greys the row nor changes the State column', () => {
  const rows = [
    row({ trade_id: 'acked', state: 'verified_open', pamm: { published: true, published_at: '2026-09-11T10:00:05Z', upstream_status: 200 } }),
    row({ trade_id: 'noack', state: 'verified_open', pamm: { published: true, published_at: '2026-09-11T10:00:05Z', upstream_status: null } }),
    row({ trade_id: 'unpublished', state: 'verified_open', pamm: null }),
  ]
  const wrapper = mount(VerifiedTrades, { props: { rows } })
  expect(rowOf(wrapper, 'acked').find('.pamm').text()).toMatch(/^Published .* · TradingBox 200$/)
  expect(rowOf(wrapper, 'noack').find('.pamm').text()).toMatch(/^Published .* · ack not received$/)
  expect(rowOf(wrapper, 'unpublished').find('.pamm').text()).toBe('Not published')
  for (const id of ['acked', 'noack', 'unpublished']) {
    const r = rowOf(wrapper, id)
    expect(r.classes()).toEqual(rowOf(wrapper, 'acked').classes())
    expect(r.find('.badge.state').text()).toBe('Verified open')
    expect(r.find('.badge.state').classes()).toContain('verified')
  }
  wrapper.unmount()
})

test('paper rows never appear in the verified ledger and the empty state is honest', () => {
  const wrapper = mount(VerifiedTrades, { props: { rows: [
    row({ trade_id: 'paper1', state: 'paper_sent', symbol: 'PAPERONLY' }),
    row({ trade_id: 'real1', state: 'candidate' }),
  ] } })
  expect(wrapper.text()).not.toContain('PAPERONLY')
  expect(wrapper.find('tr[data-trade="paper1"]').exists()).toBe(false)
  expect(wrapper.find('tr[data-trade="real1"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('1 paper send is listed on the Paper trades page, not here.')
  wrapper.unmount()
  const empty = mount(VerifiedTrades)
  expect(empty.text()).toContain('No verified trade records for this account yet')
  expect(empty.text()).toContain('not that every trade arrived')
  expect(request).not.toHaveBeenCalled()
  empty.unmount()
})

test('trade records have no per-trade Send requirement', () => {
  const wrapper = mount(VerifiedTrades, { props: { rows: [
    row({ trade_id: 'on', state: 'candidate', source_enabled: true }),
    row({ trade_id: 'off', state: 'candidate', source_enabled: false }),
    row({ trade_id: 'done', state: 'verified_open', source_enabled: true }),
  ] } })
  expect(rowOf(wrapper, 'on').find('button').exists()).toBe(false)
  expect(rowOf(wrapper, 'off').find('button').exists()).toBe(false)
  expect(rowOf(wrapper, 'done').find('button').exists()).toBe(false)
  expect(request).not.toHaveBeenCalled()
  wrapper.unmount()
})

test('a signal-driven cancel or close shows its outcome on the row and its evidence below; a cancelled row offers no send', () => {
  const wrapper = mount(VerifiedTrades, { props: { rows: [
    row({ trade_id: 'u1', state: 'cancelled', source_enabled: true, unwind: { action: 'CANCEL', outcome: 'accepted', at: '2026-09-11T10:05:00Z',
      request_id: 'cancel-1', request: { id: 'aq-1', type: 'LIMIT' }, origin: 'broker', summary: 'Broker accepted the cancel of pending order aq-1' } }),
    row({ trade_id: 'u2', state: 'verified_open', unwind: { action: 'CLOSE', outcome: 'uncertain', at: '2026-09-11T10:06:00Z',
      request_id: 'closed-1', request: { positionId: 'aq-p1' }, origin: 'transport', summary: 'Outcome unconfirmed after TimeoutError' } }),
    row({ trade_id: 'u3', state: 'verified_open', unwind: { action: 'CLOSE', outcome: 'held', at: '2026-09-11T10:07:00Z',
      request_id: 'closed-2', request: null, origin: 'local', summary: 'Split destination positions require an explicit action allocation' } }),
    row({ trade_id: 'plain', state: 'candidate', unwind: null }),
  ] } })
  const cancelled = rowOf(wrapper, 'u1')
  expect(cancelled.find('.unwind').text()).toContain('Cancel on signal · broker accepted')
  expect(cancelled.find('.unwind').classes()).toContain('unwind-accepted')
  expect(cancelled.find('.badge.state').text()).toBe('Cancelled')
  expect(cancelled.find('button').exists()).toBe(false)
  expect(rowOf(wrapper, 'u2').find('.unwind').text()).toContain('Close on signal · outcome unconfirmed')
  expect(rowOf(wrapper, 'u3').find('.unwind').text()).toContain('Close on signal · not sent')
  expect(rowOf(wrapper, 'u3').find('.unwind').classes()).toContain('unwind-held')
  expect(rowOf(wrapper, 'plain').find('.unwind').exists()).toBe(false)
  expect(wrapper.text()).toContain('signal cancel-1 · broker')
  expect(wrapper.text()).toContain('Broker accepted the cancel of pending order aq-1')
  expect(wrapper.text()).toContain('Split destination positions require an explicit action allocation')
  expect(wrapper.text()).toContain('"positionId": "aq-p1"')
  expect(request).not.toHaveBeenCalled()
  wrapper.unmount()
})
