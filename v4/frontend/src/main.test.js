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
  expect(root.querySelector('#account').value).toBe('test')
  expect(root.textContent).toContain('Start capture')
  root.__vue_app__.unmount()
})
