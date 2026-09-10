import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import OrdersWorkspace from './OrdersWorkspace.vue'

test('React Orders host propagates refreshed snapshots and refresh actions', async () => {
  const wrapper = mount(OrdersWorkspace, { props: { state: { connection: 'connected' }, mappings: [] } })
  expect(wrapper.text()).toContain('Broker data not loaded')
  await wrapper.find('.orders-intro button').trigger('click')
  expect(wrapper.emitted('refresh')).toHaveLength(1)
  await wrapper.setProps({ state: { connection: 'connected', positions_at: '2026-09-10T00:00:00Z', positions: [{ id: 'p1', symbol: 'EURUSD', profit: '-3.50' }] } })
  expect(wrapper.text()).toContain('EURUSD')
  expect(wrapper.text()).toContain('-3.50')
  wrapper.unmount()
})
