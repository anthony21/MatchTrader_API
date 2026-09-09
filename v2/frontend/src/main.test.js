import { flushPromises } from '@vue/test-utils'
import { expect, test, vi } from 'vitest'

vi.mock('./api.js', () => ({ request: vi.fn(async path => path === 'events' ? { account_id: 'test', events: [] }
  : { account_id: 'test', accounts: [{ id: 'test' }], running: false, connection: 'disconnected', orders: [] }) }))

test('application entry mounts the functional account controls', async () => {
  document.body.innerHTML = '<div id="app"></div>'
  await import('./main.js')
  await flushPromises()
  const root = document.querySelector('#app')
  expect(root.querySelector('#account').value).toBe('test')
  expect(root.textContent).toContain('Start shadow bridge')
  root.__vue_app__.unmount()
})
