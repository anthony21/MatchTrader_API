import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import LiveSignals from './LiveSignals.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear() })

function setup() {
  const sockets = []
  class Socket {
    constructor(url) { this.url = url; sockets.push(this) }
    close() { this.closed = true }
  }
  vi.stubGlobal('WebSocket', Socket)
  return { wrapper: mount(LiveSignals, { global: { stubs: { teleport: true } } }), sockets }
}

const signal = (source, machineId, kind = 'intent') => ({
  source, machineId, kind, side: 'short', entry: 81194.12000000002,
  stopLoss: 81209.35562500003, takeProfit: 81163.64875000001,
  ladderGrade: 'PRIME', grade: 'IGNORED', symbol: 'BTCUSD', timestampUtc: '2026-09-18T22:35:27.7684986Z',
})
const message = (id, payload) => ({ id, payload, raw: JSON.stringify(payload), received_at: '2026-09-18T22:36:00Z' })

test('shows individual batch events in requested columns and filters by lane, machine and event', async () => {
  const { wrapper, sockets } = setup()
  sockets[0].onopen()
  sockets[0].onmessage({ data: JSON.stringify({ type: 'snapshot', events: [message(1, [
    signal('r01Auto', 'nasdaq_30s'), signal('r01Local', 'second-machine', 'refused'),
    signal('p01', 'p01-machine'), signal('x17', 'x17-machine'),
  ])] }) })
  await wrapper.vm.$nextTick()
  expect(wrapper.findAll('th').map(th => th.text())).toEqual([
    'Lane', 'Machine ID', 'Side', 'Entry', 'Stop loss', 'Take profit', 'Ladder grade', 'Timestamp · UTC',
  ])
  expect(wrapper.findAll('.signal-row')).toHaveLength(4)
  await wrapper.findAll('.lane-filter').find(b => b.text().startsWith('R01')).trigger('click')
  expect(wrapper.findAll('.signal-row')).toHaveLength(2)
  await wrapper.get('[aria-label="Machine ID"]').setValue('nasdaq_30s')
  const cells = wrapper.findAll('.signal-row td').map(td => td.text())
  expect(cells).toEqual(['R01+intent', 'nasdaq_30sBTCUSD', 'SELL', '81,194.12', '81,209.355625', '81,163.64875', 'PRIME', '2026-09-18 22:35:27.768'])
  await wrapper.get('[aria-label="Event type"]').setValue('refused')
  expect(wrapper.text()).toContain('No signals match')
  await wrapper.findAll('.lane-filter').find(b => b.text().startsWith('P01')).trigger('click')
  expect(wrapper.findAll('.signal-row')).toHaveLength(1)
  expect(wrapper.get('.signal-row').text()).toContain('p01-machine')
  expect(wrapper.get('[aria-label="Machine ID"]').element.value).toBe('')
  wrapper.unmount()
})

test('live push preserves filters, distinguishes batches, escapes payloads and reconnects', async () => {
  vi.useFakeTimers()
  const { wrapper, sockets } = setup()
  expect(sockets[0].url).toMatch(/:8766\/events$/)
  sockets[0].onopen()
  sockets[0].onmessage({ data: JSON.stringify({ type: 'snapshot', events: [message(1, [signal('r01Auto', 'one')])] }) })
  await wrapper.vm.$nextTick()
  expect(wrapper.get('[role="status"]').text()).toContain('Live')
  await wrapper.findAll('.lane-filter').find(b => b.text().startsWith('R01')).trigger('click')
  const incoming = message(2, [{ ...signal('r01Auto', 'two'), detail: '<script>alert(1)</script>' }, signal('p02', 'panel')])
  sockets[0].onmessage({ data: JSON.stringify({ type: 'signal', event: incoming }) })
  sockets[0].onmessage({ data: JSON.stringify({ type: 'signal', event: incoming }) })
  await wrapper.vm.$nextTick()
  expect(wrapper.findAll('.signal-row')).toHaveLength(2)
  await wrapper.get('[aria-label="Search signals"]').setValue('alert(1)')
  expect(wrapper.findAll('.signal-row')).toHaveLength(1)
  await wrapper.get('.payload-toggle').trigger('click')
  expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.get('pre').text()).toContain('<script>alert(1)</script>')
  sockets[0].onclose()
  await vi.advanceTimersByTimeAsync(1000)
  expect(sockets).toHaveLength(2)
  wrapper.unmount()
  expect(sockets[1].closed).toBe(true)
  await vi.advanceTimersByTimeAsync(3000)
  expect(sockets).toHaveLength(2)
})

test('header picker navigates groups, updates columns and remembers changes', async () => {
  let { wrapper, sockets } = setup()
  sockets[0].onmessage({ data: JSON.stringify({ type: 'snapshot', events: [message(1, [{
    ...signal('r01Auto', 'machine'), ladderArm: 'r5:b8|PRIME|', dryRun: false, volume: 0, instrument: { tickSize: 0.01 },
  }])] }) })
  await wrapper.vm.$nextTick()
  expect(wrapper.get('thead .columns-button').exists()).toBe(true)
  await wrapper.get('.columns-button').trigger('click')
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0)
  expect(wrapper.findAll('.group-button')).toHaveLength(6)
  await wrapper.get('[aria-label="Grade and context columns"]').trigger('click')
  expect(wrapper.get('[aria-label="Show ladderGrade column"]').element.checked).toBe(true)
  await wrapper.get('[aria-label="Find group or field"]').setValue('ladderArm')
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
  await wrapper.get('[aria-label="Show ladderArm column"]').setValue(true)
  expect(wrapper.findAll('th').map(th => th.text())).toContain('Ladder arm')
  expect(wrapper.get('.signal-row').text()).toContain('r5:b8|PRIME|')
  await wrapper.get('.group-back').trigger('click')
  await wrapper.get('[aria-label="Trade columns"]').trigger('click')
  await wrapper.get('[aria-label="Show entry column"]').setValue(false)
  expect(wrapper.findAll('th').map(th => th.text())).not.toContain('Entry')
  await wrapper.get('.group-back').trigger('click')
  await wrapper.get('[aria-label="Sender columns"]').trigger('click')
  await wrapper.get('[aria-label="Show lane column"]').setValue(false)
  expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
  await wrapper.get('[aria-label="Show lane column"]').setValue(true)
  wrapper.unmount()
  ;({ wrapper, sockets } = setup())
  expect(wrapper.findAll('th').map(th => th.text())).toContain('Ladder arm')
  expect(wrapper.findAll('th').map(th => th.text())).not.toContain('Entry')
  await wrapper.get('.columns-button').trigger('click')
  await wrapper.findAll('.column-actions button').find(b => b.text() === 'Select all').trigger('click')
  expect(wrapper.findAll('th')).toHaveLength(44)
  await wrapper.findAll('.column-actions button').find(b => b.text() === 'Restore defaults').trigger('click')
  expect(wrapper.findAll('th')).toHaveLength(8)
  wrapper.unmount()
})
