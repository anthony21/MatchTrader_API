import { mount, flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import SignalCopySettings from './SignalCopySettings.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))

test('P01 opt-in selects the local source and machine without arming; symbols are not on this form', async () => {
  request.mockReset()
  request.mockImplementation(async path => path === 'signal-copy-events' ? { events: [] } : { config: null, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { p01_log: { machine: 'local-qt' } } } })
  await flushPromises()
  await wrapper.findAll('label').find(label => label.text().includes('Copy P01 chart intents from the local log')).find('input').setValue(true)
  const inputs = wrapper.findAll('input')
  expect(inputs.some(input => input.element.value === 'P01_LOG')).toBe(true)
  expect(inputs.some(input => input.element.value === 'local-qt')).toBe(true)
  expect(wrapper.text()).not.toContain('Copy volume')
  expect(wrapper.findAll('input').some(input => input.attributes('placeholder') === 'US TECH 100')).toBe(false)
  expect(request).not.toHaveBeenCalledWith('signal-copying', { enabled: true })
  wrapper.unmount()
})

test('saves the lane alone, without symbols, and disables editing while live', async () => {
  const config = { machine_id: 'qt', source: 'chain', connection_name: '', destination_account: 'demo', exclusive_destination: true,
    symbols: { 'US TECH 100': { destination: 'NAS100', fixed_lots: '0.2', order_type: 'LIMIT', same_price_scale: true } } }
  request.mockImplementation(async path => path === 'signal-copy-events' ? { events: [] } : { config, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { account_id: 'demo', accounts: [{ id: 'demo' }], signal_copying: false } } })
  await flushPromises()
  await wrapper.find('form').trigger('submit'); await flushPromises()
  const { symbols, ...lane } = config
  expect(request).toHaveBeenCalledWith('signal-copy-settings', expect.objectContaining(lane))
  expect(request.mock.calls.at(-1)[1]).not.toHaveProperty('symbols')
  expect(request.mock.calls.at(-1)[1]).not.toHaveProperty('risk_usd')
  expect(request).not.toHaveBeenCalledWith('signal-copying', { enabled: true })
  expect(request).not.toHaveBeenCalledWith('symbol-map', expect.anything())
  expect(wrapper.text()).not.toContain('Enable live mode')
  await wrapper.setProps({ state: { accounts: [{ id: 'demo' }], signal_copying: true } })
  expect(wrapper.find('fieldset').element.disabled).toBe(true)
  wrapper.unmount()
})

test('the R01 lane posts to its own route with source fixed, grades and dollar risk, and no P01 controls', async () => {
  request.mockReset()
  request.mockImplementation(async (path, body) => body ?? { config: null, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { account_id: 'demo', accounts: [{ id: 'demo' }], p01_log: { machine: 'HCAMM-MIKE' } },
    endpoint: 'r01-lane', title: 'R01 lane', r01: true } })
  await flushPromises()
  expect(request).toHaveBeenCalledWith('r01-lane')
  expect(wrapper.text()).not.toContain('Copy P01 chart intents')
  expect(wrapper.findAll('input').some(input => input.element.value === 'R01' && input.element.readOnly)).toBe(true)
  expect(wrapper.findAll('input').some(input => input.element.value === 'HCAMM-MIKE')).toBe(true)
  await wrapper.findAll('label').find(label => label.text() === 'PRIME').find('input').setValue(true)
  await wrapper.findAll('label').find(label => label.text() === 'STRONG').find('input').setValue(true)
  await wrapper.findAll('input[type=number]')[0].setValue('5')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(request).toHaveBeenLastCalledWith('r01-lane', expect.objectContaining({
    source: 'R01', machine_id: 'HCAMM-MIKE', destination_account: 'demo', accepted_grades: ['PRIME', 'STRONG'],
    retract_on_downgrade: true, risk_usd: '5', exclusive_destination: true }))
  expect(request).not.toHaveBeenCalledWith('signal-copy-settings', expect.anything())
  wrapper.unmount()
})

test('the destination dropdown lists connected accounts as broker · account and saves the chosen id', async () => {
  request.mockReset()
  request.mockImplementation(async (path, body) => body ?? { config: null, live: false })
  const destinations = [{ id: '275018', profile: 'AQF', broker: 'AquaFunded' }, { id: '647436', profile: 'GTR', broker: 'GooeyTrade' }]
  const wrapper = mount(SignalCopySettings, { props: { state: { p01_log: { machine: 'qt' } }, endpoint: 'r01-lane', title: 'R01 lane', r01: true, destinations } })
  await flushPromises()
  const select = wrapper.findAll('select').find(s => s.findAll('option').some(o => o.text().includes('·')))
  const labels = select.findAll('option').map(o => o.text())
  expect(labels).toContain('AquaFunded · 275018')
  expect(labels).toContain('GooeyTrade · 647436')
  await select.setValue('647436')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(request).toHaveBeenLastCalledWith('r01-lane', expect.objectContaining({ destination_account: '647436' }))
  wrapper.unmount()
})

test('X17 and manual P01 preset selects chain plus panel without arming; unwinding is not a switch', async () => {
  request.mockReset()
  request.mockResolvedValue({ config: null, live: false })
  const wrapper = mount(SignalCopySettings, { props: { state: { p01_log: { machine: 'qt' } } } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Use X17 + manual P01 at logged entry').trigger('click')
  expect(wrapper.findAll('input').some(input => input.element.value === 'chain')).toBe(true)
  // The retired cancel_pending switch is gone: a cancel or closed signal always acts on a sent trade.
  expect(wrapper.findAll('label').some(label => label.text().includes('Forward cancellation'))).toBe(false)
  expect(wrapper.vm.config ?? {}).not.toHaveProperty('cancel_pending')
  expect(wrapper.findAll('label').find(label => label.text().includes('Also accept structured')).find('input').element.checked).toBe(true)
  expect(wrapper.findAll('label').find(label => label.text().includes('Copy P01 chart intents from the local log')).find('input').element.checked).toBe(false)
  expect(wrapper.findAll('label').find(label => label.text().includes('Require X17')).find('input').element.checked).toBe(true)
  expect(request).not.toHaveBeenCalledWith('signal-copying', { enabled: true })
  wrapper.unmount()
})
