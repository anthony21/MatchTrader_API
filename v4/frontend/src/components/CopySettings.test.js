import { flushPromises, mount } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
import CopySettings from './CopySettings.vue'
import { request } from '../api.js'
vi.mock('../api.js', () => ({ request: vi.fn() }))

test('loads persisted route and saves P01 settings without enabling copying', async () => {
  const saved = { csv_limit: 1000, inventory: [{ machine: 'qt', connection_id: 'ctrader', account_id: 'source', status: 'Source account' }], route: {
    machine: 'qt', connection_id: 'ctrader', account_id: 'source', destination_account: 'demo', sources: ['P01'],
    exclusive_destination: true, legacy_route_disabled: true,
    symbols: { 'EUR/USD': { destination: 'EURUSD', quantity_multiplier: '1', max_lots: '1', same_price_scale: true } },
  } }
  request.mockResolvedValue(saved)
  const wrapper = mount(CopySettings, { props: { state: { account_id: 'demo', accounts: [{ id: 'demo' }] } } })
  await flushPromises()
  expect(wrapper.find('select[aria-label="Detected Quantower account"]').element.value).toBe('0')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(request).toHaveBeenLastCalledWith('copy-settings', { route: saved.route, csv_limit: 1000 })
  expect(wrapper.text()).toContain('Settings saved')
  expect(wrapper.text()).toContain('Nothing is sent automatically')
  expect(wrapper.emitted('saved')).toHaveLength(1)
  // Saving a route is not enabling copying, and the page no longer points at a legacy toggle.
  expect(request).not.toHaveBeenCalledWith('copying', expect.anything())
  expect(wrapper.text()).not.toContain('Allow API trading')
  await wrapper.setProps({ state: { copying: true, accounts: [] } })
  expect(wrapper.find('fieldset').element.disabled).toBe(false)
})
