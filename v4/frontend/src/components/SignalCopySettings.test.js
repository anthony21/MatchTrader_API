import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import SignalCopySettings from './SignalCopySettings.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))

test('P01 opt-in selects local source and preserves source pending order type without arming', async () => {
  request.mockReset()
  request.mockImplementation(async path => path === 'signal-copy-events' ? { events: [] } : { config: null, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { p01_log: { machine: 'local-qt' } } } })
  await flushPromises()
  await wrapper.findAll('label').find(label => label.text().includes('Copy P01 chart intents from the local log')).find('input').setValue(true)
  const inputs = wrapper.findAll('input')
  expect(inputs.some(input => input.element.value === 'P01_LOG')).toBe(true)
  expect(inputs.some(input => input.element.value === 'local-qt')).toBe(true)
  expect(wrapper.findAll('select').some(select => select.element.value === 'SOURCE')).toBe(true)
  expect(request).not.toHaveBeenCalledWith('signal-copying', { enabled: true })
  wrapper.unmount()
})
test('saves fixed volume separately from the live switch and disables editing while live', async () => {
  const config = { machine_id: 'qt', source: 'chain', connection_name: '', destination_account: 'demo', exclusive_destination: true,
    symbols: { 'US TECH 100': { destination: 'NAS100', fixed_lots: '0.2', order_type: 'LIMIT', same_price_scale: true } } }
  request.mockImplementation(async path => path === 'signal-copy-events' ? { events: [] } : { config, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { account_id: 'demo', accounts: [{ id: 'demo' }], signal_copying: false } } })
  await flushPromises()
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(request).toHaveBeenCalledWith('signal-copy-settings', config)
  expect(request).not.toHaveBeenCalledWith('signal-copying', { enabled: true })
  expect(wrapper.text()).not.toContain('Enable live mode')
  await wrapper.setProps({ state: { accounts: [{ id: 'demo' }], signal_copying: true } })
  expect(wrapper.find('fieldset').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('Turn Live off')
  wrapper.unmount()
})


test('X17 and manual P01 preset selects pending entry without arming; unwinding is not a switch', async () => {
  request.mockReset()
  request.mockResolvedValue({ config: null, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { p01_log: { machine: 'qt' } } } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Use X17 + manual P01 at logged entry').trigger('click')
  expect(wrapper.findAll('select').some(select => select.element.value === 'ENTRY')).toBe(true)
  // The retired cancel_pending switch is gone: a cancel or closed signal always acts on a sent trade.
  expect(wrapper.findAll('label').some(label => label.text().includes('Forward cancellation'))).toBe(false)
  expect(wrapper.text()).toContain('A cancel or closed signal always acts on a trade you already sent')
  expect(wrapper.text()).toContain('Nothing is ever opened automatically')
  expect(wrapper.vm.config ?? {}).not.toHaveProperty('cancel_pending')
  expect(wrapper.findAll('label').find(label => label.text().includes('Also accept structured')).find('input').element.checked).toBe(true)
  expect(wrapper.findAll('label').find(label => label.text().includes('Copy P01 chart intents from the local log')).find('input').element.checked).toBe(false)
  expect(request).not.toHaveBeenCalledWith('signal-copying', { enabled: true })
  wrapper.unmount()
})
