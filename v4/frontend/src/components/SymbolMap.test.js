import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import SymbolMap from './SymbolMap.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))
afterEach(() => vi.clearAllMocks())

const saved = {
  'US 500': { destination: 'SPX500', lots: '0.01', order_type: 'SOURCE' },
  BTCUSD: { destination: 'BTCUSD', lots: '1', order_type: 'SOURCE' },
}

test('loads the map from its own route and renders one row per Quantower symbol', async () => {
  request.mockResolvedValue(saved)
  const wrapper = mount(SymbolMap, { props: { state: {} } })
  await flushPromises()
  expect(request).toHaveBeenCalledWith('symbol-map')
  const rows = wrapper.findAll('tbody tr')
  expect(rows).toHaveLength(2)
  expect(rows[0].find('input[aria-label="Quantower symbol"]').element.value).toBe('US 500')
  expect(rows[0].find('input[aria-label="AquaFunded instrument"]').element.value).toBe('SPX500')
  expect(rows[1].find('input[aria-label="Lots"]').element.value).toBe('1')
  wrapper.unmount()
})

test('saving posts the whole table as a replacement and never touches the lane settings', async () => {
  request.mockImplementation(async (path, body) => body ?? saved)
  const wrapper = mount(SymbolMap, { props: { state: {} } })
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Add symbol').trigger('click')
  const added = wrapper.findAll('tbody tr')[2]
  await added.find('input[aria-label="Quantower symbol"]').setValue(' US TECH 100 ')
  await added.find('input[aria-label="AquaFunded instrument"]').setValue('NAS100')
  await added.find('input[aria-label="Lots"]').setValue('0.02')
  await added.find('select').setValue('LIMIT')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(request).toHaveBeenLastCalledWith('symbol-map', {
    'US 500': { destination: 'SPX500', lots: '0.01', order_type: 'SOURCE', min_box: '0' },
    BTCUSD: { destination: 'BTCUSD', lots: '1', order_type: 'SOURCE', min_box: '0' },
    'US TECH 100': { destination: 'NAS100', lots: '0.02', order_type: 'LIMIT', min_box: '0' } })
  expect(request).not.toHaveBeenCalledWith('signal-copy-settings', expect.anything())
  expect(wrapper.find('[role=status]').text()).toContain('3 symbols')
  wrapper.unmount()
})

test('a minimum box entered on a row is posted for that symbol', async () => {
  request.mockImplementation(async (path, body) => body ?? saved)
  const wrapper = mount(SymbolMap, { props: { state: {} } })
  await flushPromises()
  await wrapper.findAll('tbody tr')[0].find('input[aria-label="Min box"]').setValue('6')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(request.mock.calls.at(-1)[1]['US 500'].min_box).toBe('6')
  wrapper.unmount()
})

test('duplicate or blank Quantower symbols are refused before anything is posted', async () => {
  request.mockResolvedValue(saved)
  const wrapper = mount(SymbolMap, { props: { state: {} } })
  await flushPromises()
  await wrapper.findAll('tbody tr')[1].find('input[aria-label="Quantower symbol"]').setValue('US 500')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toContain('unique')
  expect(request).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

test('the server reason is shown on a failed save and editing is locked while live', async () => {
  request.mockResolvedValueOnce(saved).mockRejectedValueOnce(new Error('Turn live signal copying off before editing settings'))
  const wrapper = mount(SymbolMap, { props: { state: { signal_copying: false } } })
  await flushPromises()
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toBe('Turn live signal copying off before editing settings')
  await wrapper.setProps({ state: { signal_copying: true } })
  expect(wrapper.find('fieldset').element.disabled).toBe(true)
  wrapper.unmount()
})
