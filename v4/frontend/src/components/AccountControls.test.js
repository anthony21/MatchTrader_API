import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import AccountControls from './AccountControls.vue'

test('Start capture emits start and is disabled without a running service or a selected account', async () => {
  const wrapper = mount(AccountControls, { props: { selected: '123', busy: false,
    state: { running: false, connection: 'disconnected' } } })
  await wrapper.find('button.primary').trigger('click')
  expect(wrapper.emitted('start')).toHaveLength(1)
  expect(wrapper.find('button.primary').element.disabled).toBe(false)
  await wrapper.setProps({ state: { running: true, connection: 'connected' } })
  expect(wrapper.find('button.primary').element.disabled).toBe(true)
  await wrapper.setProps({ state: { running: false, connection: 'disconnected' }, selected: '' })
  expect(wrapper.find('button.primary').element.disabled).toBe(true)
})

test('Stop & disconnect emits stop and follows its own disabled rule', async () => {
  const wrapper = mount(AccountControls, { props: { selected: '123', busy: false,
    state: { running: false, connection: 'disconnected' } } })
  expect(wrapper.find('button.secondary').element.disabled).toBe(true)
  await wrapper.setProps({ state: { running: true, connection: 'connected' } })
  expect(wrapper.find('button.secondary').element.disabled).toBe(false)
  await wrapper.find('button.secondary').trigger('click')
  expect(wrapper.emitted('stop')).toHaveLength(1)
})

test('login controls are gone from the component', () => {
  const wrapper = mount(AccountControls, { props: { selected: '123', busy: false,
    state: { running: false, connection: 'disconnected' } } })
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.find('#account').exists()).toBe(false)
  expect(wrapper.findAll('button').map(b => b.text())).not.toContain('Choose broker login')
  expect(wrapper.findAll('button').map(b => b.text())).not.toContain('Log in')
  expect(wrapper.find('.control-divider').exists()).toBe(false)
})
