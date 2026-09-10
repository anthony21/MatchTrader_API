import { afterEach, expect, test, vi } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })
test('loads a local session and sends account selection only to the local API', async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'local-session' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ running: true }) })
  vi.stubGlobal('fetch', fetch)
  const { request } = await import('./api.js')
  expect(await request('start', { account_id: '123' })).toEqual({ running: true })
  expect(fetch.mock.calls[1][0]).toBe('/api/start')
  expect(fetch.mock.calls[1][1].headers['X-Session-Token']).toBe('local-session')
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ account_id: '123' })
})
test('reports API errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'local' }) })
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ error: 'Reload dashboard' }) }))
  const { request } = await import('./api.js')
  await expect(request('status')).rejects.toThrow('Reload dashboard')
})

test('stream uses session header and clears expired authentication for reconnection', async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'old' }) })
    .mockResolvedValueOnce({ ok: false, status: 401 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'new' }) })
    .mockResolvedValueOnce({ ok: true, headers: new Headers({ 'Content-Type': 'text/event-stream' }) })
  vi.stubGlobal('fetch', fetch)
  const { openEventStream } = await import('./api.js')
  await expect(openEventStream()).rejects.toThrow('Live event connection unavailable')
  await openEventStream()
  expect(fetch.mock.calls[3][0]).toBe('/api/capture/stream')
  expect(fetch.mock.calls[3][1].headers['X-Session-Token']).toBe('new')
})
