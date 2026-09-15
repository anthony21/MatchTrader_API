import { flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'

// The entry point mounts the push-driven shell: status arrives on the dashboard stream.
vi.mock('./api.js', () => ({ request: vi.fn() }))
vi.mock('./stream.js', () => ({
  followNativeEvents: vi.fn(() => () => {}),
  followDashboard: vi.fn((onSnapshot, onState) => {
    onState('live')
    onSnapshot({ status: { account_id: 'test', accounts: [{ id: 'test' }], running: false, connection: 'disconnected', orders: [] },
      events: { account_id: 'test', events: [] } })
    return () => {}
  }),
}))

test('application entry mounts the functional account controls', async () => {
  document.body.innerHTML = '<div id="app"></div>'
  await import('./main.js')
  await flushPromises()
  const root = document.querySelector('#app')
  // Trading bridge is the default page and hides the login/account picker.
  expect(root.querySelector('#account')).toBeNull()
  const accountMetric = Array.from(root.querySelectorAll('.metric')).find(el => el.textContent.includes('SELECTED ACCOUNT'))
  expect(accountMetric.querySelector('strong').textContent).toBe('test')
  expect(root.textContent).toContain('Start capture')
  root.__vue_app__.unmount()
})
