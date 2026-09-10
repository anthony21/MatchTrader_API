import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import BrokerOrders from './BrokerOrders.vue'
import { localTime } from '../time.js'

test('requires broker connection and labels snapshots separately', async () => {
  const wrapper = mount(BrokerOrders, { props: { orders: [], connected: false, busy: false } })
  expect(wrapper.find('button').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('No broker snapshot loaded')
  await wrapper.setProps({ connected: true, updatedAt: '2026-09-09T00:00:00Z' })
  await wrapper.find('button').trigger('click')
  expect(wrapper.emitted('refresh')).toHaveLength(1)
  expect(wrapper.text()).toContain('No active pending orders in this snapshot')
  await wrapper.setProps({ orders: [{ id: 'o1', creationTime: '2026-09-10T01:37:03', creationTimeIso: '2026-09-10T01:37:03.439Z' }] })
  expect(wrapper.text()).toContain('— (pending)')
  expect(wrapper.text()).toContain(localTime('2026-09-10T01:37:03.439Z'))
  expect(wrapper.text()).not.toContain('timezone unavailable')
})
