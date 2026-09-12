import { afterEach, expect, test, vi } from 'vitest'
import { followDashboard, followNativeEvents } from './stream.js'
import { openEventStream } from './api.js'

vi.mock('./api.js', () => ({ openEventStream: vi.fn() }))
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks() })
function setup() {
  vi.useFakeTimers()
  vi.stubGlobal('requestAnimationFrame', callback => setTimeout(callback, 16))
  vi.stubGlobal('cancelAnimationFrame', clearTimeout)
  let stream
  openEventStream.mockImplementation(async signal => {
    const body = new ReadableStream({ start(controller) {
      stream = controller
      signal.addEventListener('abort', () => controller.error(new Error('aborted')))
    } })
    return { body }
  })
  return text => stream.enqueue(new TextEncoder().encode(text))
}

test('handles fragmented packets, heartbeat and frame-coalesced snapshots', async () => {
  const send = setup(), events = vi.fn(), state = vi.fn()
  const stop = followNativeEvents(events, state)
  await vi.advanceTimersByTimeAsync(0)
  send('data: {"events":[')
  send('{"id":"one"}]}\n\n: heartbeat\n\n')
  send('data: {"events":[{"id":"one"},{"id":"two"}]}\n\n')
  await vi.advanceTimersByTimeAsync(16)
  expect(events).toHaveBeenCalledOnce()
  expect(events).toHaveBeenLastCalledWith([{ id: 'one' }, { id: 'two' }])
  expect(state).toHaveBeenLastCalledWith('live')
  expect(openEventStream).toHaveBeenCalledWith(expect.any(AbortSignal), 'capture/stream')
  stop()
  await vi.advanceTimersByTimeAsync(20000)
  expect(openEventStream).toHaveBeenCalledOnce()
})

test('reconnects after a broken stream and cancels queued rendering on disposal', async () => {
  const send = setup(), events = vi.fn(), state = vi.fn()
  const stop = followNativeEvents(events, state)
  await vi.advanceTimersByTimeAsync(0)
  send('data: invalid-json\n\n')
  await vi.advanceTimersByTimeAsync(1000)
  expect(openEventStream).toHaveBeenCalledTimes(2)
  expect(state).toHaveBeenCalledWith('reconnecting')
  send('data: {"events":[]}\n\n')
  await vi.advanceTimersByTimeAsync(0)
  stop()
  await vi.advanceTimersByTimeAsync(20)
  expect(events).not.toHaveBeenCalled()
})

test('missing heartbeats abort the connection and enable reconnect fallback', async () => {
  setup()
  const state = vi.fn()
  const stop = followNativeEvents(vi.fn(), state)
  await vi.advanceTimersByTimeAsync(25000)
  expect(state).toHaveBeenLastCalledWith('reconnecting')
  await vi.advanceTimersByTimeAsync(1000)
  expect(openEventStream).toHaveBeenCalledTimes(2)
  stop()
})

test('followDashboard merges changed sections into one accumulated snapshot and ignores heartbeats', async () => {
  const send = setup(), snapshots = vi.fn(), state = vi.fn()
  const stop = followDashboard(snapshots, state)
  await vi.advanceTimersByTimeAsync(0)
  expect(openEventStream).toHaveBeenCalledWith(expect.any(AbortSignal), 'stream')
  send('data: {"revision":1,"status":{"connection":"connected"},"events":{"account_id":"1","events":[]}}\n\n')
  await vi.advanceTimersByTimeAsync(16)
  expect(snapshots).toHaveBeenCalledOnce()
  const first = snapshots.mock.calls[0][0]
  expect(first).toEqual({ status: { connection: 'connected' }, events: { account_id: '1', events: [] } })
  expect(state).toHaveBeenLastCalledWith('live')
  // A heartbeat carries nothing; a frame with one changed section is merged over what was held.
  send(': heartbeat\n\n')
  send('data: {"revision":2,"mappings":{"account_id":"1","mappings":[{"id":"m"}]}}\n\n')
  await vi.advanceTimersByTimeAsync(16)
  expect(snapshots).toHaveBeenCalledTimes(2)
  const second = snapshots.mock.calls[1][0]
  expect(second.mappings).toEqual({ account_id: '1', mappings: [{ id: 'm' }] })
  expect(second.status).toBe(first.status)
  expect(second.events).toBe(first.events)
  expect('revision' in second).toBe(false)
  // Two frames inside one animation frame coalesce into a single delivery of the latest merge.
  send('data: {"revision":3,"status":{"connection":"disconnected"}}\n\n')
  send('data: {"revision":4,"capture_events":{"events":[{"id":"n"}]}}\n\n')
  await vi.advanceTimersByTimeAsync(16)
  expect(snapshots).toHaveBeenCalledTimes(3)
  const third = snapshots.mock.calls[2][0]
  expect(third.status).toEqual({ connection: 'disconnected' })
  expect(third.capture_events).toEqual({ events: [{ id: 'n' }] })
  expect(third.mappings).toBe(second.mappings)
  stop()
})

test('followDashboard rejects a packet without a revision and reconnects', async () => {
  const send = setup(), snapshots = vi.fn(), state = vi.fn()
  const stop = followDashboard(snapshots, state)
  await vi.advanceTimersByTimeAsync(0)
  send('data: {"status":{"connection":"connected"}}\n\n')
  await vi.advanceTimersByTimeAsync(1000)
  expect(openEventStream).toHaveBeenCalledTimes(2)
  expect(state).toHaveBeenCalledWith('reconnecting')
  await vi.advanceTimersByTimeAsync(16)
  expect(snapshots).not.toHaveBeenCalled()
  stop()
})
