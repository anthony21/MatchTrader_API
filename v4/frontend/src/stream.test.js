import { afterEach, expect, test, vi } from 'vitest'
import { followNativeEvents } from './stream.js'
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
