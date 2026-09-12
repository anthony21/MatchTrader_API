import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import NativeEvents from './NativeEvents.vue'

test('the bridge page offers no copying toggle and native identities stay visible', async () => {
  const wrapper = mount(NativeEvents, { props: { state: {}, events: [{ id: 'e1', trade_id: 'trade1', order_id: 'qt1', source: 'UNKNOWN', account_id: 'source', decision: 'held', reason: 'Unmapped' }] } })
  const armingButton = () => wrapper.findAll('button').find(b => /API trading/i.test(b.text()))
  expect(armingButton()).toBeUndefined()
  expect(wrapper.text()).toContain('trade1')
  expect(wrapper.text()).toContain('Unknown source')
  expect(wrapper.text()).toContain('source')
  // Even a state that used to light the button up produces neither a button nor a toggle event.
  await wrapper.setProps({ state: { route_configured: true, running: true, connection: 'connected', copying: true } })
  expect(armingButton()).toBeUndefined()
  for (const button of wrapper.findAll('button')) await button.trigger('click')
  expect(wrapper.emitted('toggle')).toBeUndefined()
  expect(wrapper.text()).toContain('Automatic dispatch off')
  wrapper.unmount()
})
