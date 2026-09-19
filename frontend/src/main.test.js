import { flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'
vi.mock('./components/LiveSignals.vue', () => ({ default: { template: '<section>Live signal stream</section>' } }))

vi.mock('./api.js', () => ({ request: vi.fn(async path => path === 'events' ? { account_id: 'test', events: [] }
  : { account_id: 'test', accounts: [{ id: 'test' }], running: false, connection: 'disconnected', orders: [] }) }))

test('application entry mounts live signals and broker sessions navigation', async () => {
  document.body.innerHTML = '<div id="app"></div>'
  await import('./main.js')
  await flushPromises()
  const root = document.querySelector('#app')
  expect(root.querySelector('select')).toBeNull()
  expect(root.textContent).toContain('Broker sessions')
  expect(root.textContent).toContain('Live signal stream')
  root.__vue_app__.unmount()
})
