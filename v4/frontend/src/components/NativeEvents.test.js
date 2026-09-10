import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import NativeEvents from './NativeEvents.vue'

test('copying requires a configured route and native identities stay visible', async () => {
  const wrapper = mount(NativeEvents, { props: { state: {}, events: [{ id: 'e1', trade_id: 'trade1', order_id: 'qt1', source: 'UNKNOWN', account_id: 'source', decision: 'held', reason: 'Unmapped' }] } })
  expect(wrapper.find('button').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('trade1')
  expect(wrapper.text()).toContain('Unknown source')
  expect(wrapper.text()).toContain('source')
  await wrapper.setProps({ state: { route_configured: true, running: true, connection: 'connected', copying: true } })
  expect(wrapper.find('button').text()).toBe('Stop API trading')
  await wrapper.find('button').trigger('click')
  expect(wrapper.emitted('toggle')).toHaveLength(1)
  wrapper.unmount()
})
