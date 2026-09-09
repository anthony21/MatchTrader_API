import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import AccountControls from './AccountControls.vue'

test('account changes and start controls emit explicit actions', async () => {
  const wrapper = mount(AccountControls, { props: { selected: '123', busy: false,
    state: { running: false, connection: 'disconnected', accounts: [{ id: '123' }, { id: '456' }] } } })
  await wrapper.find('select').setValue('456')
  expect(wrapper.emitted('update:selected')[0]).toEqual(['456'])
  await wrapper.find('button.primary').trigger('click')
  expect(wrapper.emitted('start')).toHaveLength(1)
  await wrapper.setProps({ state: { running: true, accounts: [{ id: '123' }] } })
  expect(wrapper.find('select').element.disabled).toBe(true)
  expect(wrapper.find('button.primary').element.disabled).toBe(true)
})
