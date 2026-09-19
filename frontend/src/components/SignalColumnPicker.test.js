import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { expect, test } from 'vitest'
import SignalColumnPicker from './SignalColumnPicker.vue'
import { DEFAULT_COLUMNS, SIGNAL_COLUMNS } from './signalColumns.js'

test('two levels expose all fields, close outside and restore keyboard focus on Escape', async () => {
  const wrapper = mount(SignalColumnPicker, { props: { modelValue: DEFAULT_COLUMNS }, attachTo: document.body })
  try {
    const trigger = wrapper.get('[aria-label="Filter columns"]')
    await trigger.trigger('click')
    const panel = document.querySelector('[role="dialog"]')
    expect(panel.querySelectorAll('input[type="checkbox"]')).toHaveLength(0)
    const names = [...panel.querySelectorAll('.group-button')].map(b => b.getAttribute('aria-label'))
    const seen = []
    for (const name of names) {
      panel.querySelector(`[aria-label="${name}"]`).click()
      await nextTick()
      seen.push(...[...panel.querySelectorAll('input[type="checkbox"]')].map(input => input.value))
      panel.querySelector('.group-back').click()
      await nextTick()
    }
    expect(seen.sort()).toEqual(SIGNAL_COLUMNS.map(column => column.key).sort())
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
    await trigger.trigger('click')
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  } finally { wrapper.unmount() }
})

test('last visible field stays selected', async () => {
  const wrapper = mount(SignalColumnPicker, { props: { modelValue: ['lane'] }, global: { stubs: { teleport: true } } })
  await wrapper.get('.columns-button').trigger('click')
  await wrapper.get('[aria-label="Sender columns"]').trigger('click')
  expect(wrapper.get('[aria-label="Show lane column"]').element.disabled).toBe(true)
  await wrapper.get('[aria-label="Show machineId column"]').setValue(true)
  expect(wrapper.emitted('update:modelValue')[0][0]).toEqual(['lane', 'machineId'])
  wrapper.unmount()
})
