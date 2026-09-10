let sessionToken = ''

async function ensureSession() {
  if (!sessionToken) {
    const session = await fetch('/api/session', { cache: 'no-store' })
    if (!session.ok) throw new Error('Unable to open a local dashboard session.')
    sessionToken = (await session.json()).token
  }
}

export async function openEventStream(signal) {
  await ensureSession()
  const response = await fetch('/api/capture/stream', {
    headers: { 'X-Session-Token': sessionToken, Accept: 'text/event-stream' },
    cache: 'no-store', signal,
  })
  if (!response.ok || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) {
    if (response.status === 401) sessionToken = ''
    throw new Error('Live event connection unavailable')
  }
  return response
}

export async function request(path, body) {
  await ensureSession()
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Session-Token': sessionToken, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  })
  const result = await response.json()
  if (!response.ok) {
    if (response.status === 401) sessionToken = ''
    throw new Error(result.error || 'The local API could not complete this request.')
  }
  return result
}
