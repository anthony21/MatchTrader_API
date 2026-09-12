import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import PaperTrades from './PaperTrades.vue'

test('paper sends show the exact request, verdict and reason, and say they were never sent to a broker', () => {
  const wrapper = mount(PaperTrades, { props: { rows: [{ trade_id: 'p1', source: 'X17', symbol: 'NAS100', side: 'SELL', lots: '0.20',
    request: { symbol: 'NAS100', side: 'SELL', volume: '0.20', orderType: 'MARKET' }, verdict: 'would_send', reason: 'Mapping resolved',
    decided_at: '2026-09-11T10:00:00Z' }] } })
  expect(wrapper.text()).toContain('never sent to a broker and can never be verified')
  const row = wrapper.find('tr[data-trade="p1"]')
  for (const text of ['X17', 'NAS100', 'SELL', '0.20', 'would_send', 'Mapping resolved', '"orderType": "MARKET"']) expect(row.text()).toContain(text)
  expect(wrapper.find('th:last-child').text()).toBe('Decided atlocal clock')
  wrapper.unmount()
})

test('an empty paper page renders an honest empty state and never claims verification', () => {
  const wrapper = mount(PaperTrades)
  expect(wrapper.text()).toContain('No paper sends recorded for this account.')
  expect(wrapper.text()).toContain('can never be verified')
  expect(wrapper.text()).toContain('Copy mode now: paper')
  wrapper.unmount()
})
