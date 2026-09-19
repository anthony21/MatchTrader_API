import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import AccountControls from './AccountControls.vue'

test('account choices and buttons follow broker connection state without capture controls', async () => {
  const broker = { id: 'AQUA', label: 'AquaFunded', state: 'connected', selected_account: '123', accounts: ['123', '456'] }
  const wrapper = mount(AccountControls, { props: { broker, busy: false } })
  expect(wrapper.get('button.primary').element.disabled).toBe(true)
  expect(wrapper.get('button.secondary').element.disabled).toBe(false)
  await wrapper.get('select').setValue('456')
  expect(wrapper.emitted('account')).toEqual([['456']])
  await wrapper.get('button.secondary').trigger('click')
  expect(wrapper.emitted('disconnect')).toHaveLength(1)
  await wrapper.setProps({ broker: { ...broker, state: 'disconnected' } })
  expect(wrapper.get('button.primary').element.disabled).toBe(false)
  expect(wrapper.get('button.secondary').element.disabled).toBe(true)
  await wrapper.get('button.primary').trigger('click')
  expect(wrapper.emitted('connect')).toHaveLength(1)
  expect(wrapper.text()).not.toContain('Start capture')
  expect(wrapper.text()).not.toContain('Stop capture')
  await wrapper.setProps({ broker: { ...broker, capture_running: true } })
  expect(wrapper.get('select').element.disabled).toBe(true)
})
