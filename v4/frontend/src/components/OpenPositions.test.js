import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import OpenPositions from './OpenPositions.vue'

test('shows actual position identity and pnl, distinguishes empty and unavailable', async () => {
  const wrapper = mount(OpenPositions, { props: { positions: [], connected: true, busy: false } })
  expect(wrapper.text()).toContain('No open-position snapshot loaded')
  await wrapper.setProps({ updatedAt: '2026-09-09T12:00:00Z' })
  expect(wrapper.text()).toContain('No open positions')
  await wrapper.setProps({ positions: [{ id: 'p1', symbol: 'EURUSD', side: 'BUY', volume: '.01', openPrice: '1.15', netProfit: '-2.50' }] })
  expect(wrapper.text()).toContain('p1')
  expect(wrapper.text()).toContain('-2.50')
  await wrapper.find('button').trigger('click')
  expect(wrapper.emitted('refresh')).toHaveLength(1)
})
