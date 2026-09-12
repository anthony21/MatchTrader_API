import { openEventStream } from './api.js'

// One authenticated connection per path; reconnects obtain a fresh snapshot.
// Shared plumbing: reader loop, "\n\n" framing, 25s idle abort, exponential
// reconnect capped at 10s and requestAnimationFrame coalescing of deliveries.
function follow(path, validate, onValue, onState) {
  let stopped = false, retry, frame, latest, controller, failures = 0
  const deliver = value => {
    latest = value
    if (frame === undefined) frame = requestAnimationFrame(() => {
      frame = undefined
      if (!stopped) onValue(latest)
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
          // Comment lines such as ": heartbeat" carry no data and are ignored.
          const data = packet.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
          if (!data) continue
          const payload = validate(JSON.parse(data))
          failures = 0
          onState('live')
          deliver(payload)
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

export function followNativeEvents(onEvents, onState, path = 'capture/stream') {
  return follow(path, snapshot => {
    if (!Array.isArray(snapshot.events)) throw new Error('Invalid event snapshot')
    return snapshot.events
  }, onEvents, onState)
}

// The shell's whole local view. The server pushes only the sections that changed,
// so this merges them into one accumulated snapshot rather than refetching anything.
// A packet without a revision is malformed; throwing here takes the reconnect path.
export function followDashboard(onSnapshot, onState) {
  let merged = {}
  return follow('stream', packet => {
    if (!packet || typeof packet !== 'object' || !('revision' in packet)) {
      throw new Error('Invalid dashboard snapshot')
    }
    const { revision, ...sections } = packet
    merged = { ...merged, ...sections }
    return merged
  }, onSnapshot, onState)
}
