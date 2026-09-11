import { openEventStream } from './api.js'

// One authenticated connection; reconnects obtain a fresh journal snapshot.
export function followNativeEvents(onEvents, onState, path = 'capture/stream') {
  let stopped = false, retry, frame, latest, controller, failures = 0
  const deliver = events => {
    latest = events
    if (frame === undefined) frame = requestAnimationFrame(() => {
      frame = undefined
      if (!stopped) onEvents(latest)
    })
  }
  async function connect() {
    controller = new AbortController()
    onState(failures ? 'reconnecting' : 'connecting')
    let reader, idleTimer
    try {
      const response = await openEventStream(controller.signal, path)
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (!stopped) {
        idleTimer = setTimeout(() => controller.abort(), 25000)
        const { value, done } = await reader.read()
        clearTimeout(idleTimer)
        if (done) throw new Error('Event stream ended')
        buffer += decoder.decode(value, { stream: true })
        let boundary
        while ((boundary = buffer.indexOf('\n\n')) !== -1) {
          const packet = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
          const data = packet.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
          if (!data) continue
          const snapshot = JSON.parse(data)
          if (!Array.isArray(snapshot.events)) throw new Error('Invalid event snapshot')
          failures = 0
          onState('live')
          deliver(snapshot.events)
        }
      }
    } catch {
      if (!stopped) {
        onState('reconnecting')
        retry = setTimeout(connect, Math.min(1000 * 2 ** failures++, 10000))
      }
    } finally {
      clearTimeout(idleTimer)
      await reader?.cancel().catch(() => {})
      reader?.releaseLock()
    }
  }
  connect()
  return () => {
    stopped = true; clearTimeout(retry); controller?.abort()
    if (frame !== undefined) cancelAnimationFrame(frame)
  }
}
