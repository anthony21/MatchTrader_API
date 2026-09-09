import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import EventTable from './EventTable.vue'

test('shows missing lots and broker identity without inventing execution', () => {
  const wrapper = mount(EventTable, { props: { events: [{ id: '1', symbol: '<script>alert(1)</script>',
    side: 'SELL', action: 'touched', status: 'observation', volume: null, broker_order_id: null }] } })
  expect(wrapper.text()).toContain('observation')
  expect(wrapper.text()).toContain('—')
  expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('accepted')
})
test('empty feed explains fresh-event capture', () => {
  const wrapper = mount(EventTable, { props: { events: [] } })
  expect(wrapper.text()).toContain('Historical ledger rows are not replayed')
})
