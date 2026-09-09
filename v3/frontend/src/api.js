let sessionToken = ''

export async function request(path, body) {
  if (!sessionToken) {
    const session = await fetch('/api/session', { cache: 'no-store' })
    if (!session.ok) throw new Error('Unable to open a local dashboard session.')
    sessionToken = (await session.json()).token
  }
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
