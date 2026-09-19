const object = value => value && typeof value === 'object' && !Array.isArray(value)
const text = value => typeof value === 'string' || typeof value === 'number' ? String(value) : ''

export function signalLane(source, signal = {}) {
  const name = text(source).trim()
  const known = name.match(/^(R01|P01|P02|X17)(?=$|[^0-9])/i)
  if (known) return known[1].toUpperCase()
  if (name.toLowerCase() === 'chain' && /^x17-spine\b/i.test(text(signal.detail))) return 'X17'
  if (name.toLowerCase() === 'panel' && /^P01RR_/i.test(text(signal.label))) return 'P01'
  return name.toUpperCase() || 'UNKNOWN'
}

export function signalRows(messages) {
  return messages.flatMap(message => {
    let payload = message.payload
    if (payload === undefined) {
      try { payload = JSON.parse(message.raw) } catch { payload = null }
    }
    const items = Array.isArray(payload) ? payload : [payload]
    const results = new Map((message.signals ?? []).map(result => [result.index, result]))
    return items.map((item, index) => {
      const result = results.get(index)
      const signal = object(result?.signal) ? result.signal : object(item) ? item : {}
      const order = result?.shapes?.r01OrderShape ?? {}
      const source = text(signal.source || signal.strategy || signal.sending_source || message.source)
      const side = text(order.orderSide || signal.side).toLowerCase()
      return {
        id: `${message.id}:${index}`, lane: signalLane(source, signal), source,
        machineId: text(signal.machineId),
        kind: text(signal.kind || signal.event_type || signal.eventType || signal.type || message.kind),
        side: { long: 'BUY', short: 'SELL', buy: 'BUY', sell: 'SELL' }[side] ?? '',
        entry: order.price ?? signal.entry, stopLoss: order.slPrice ?? signal.stopLoss,
        takeProfit: order.tpPrice ?? signal.takeProfit, ladderGrade: text(signal.ladderGrade),
        symbol: text(signal.symbol || message.symbol), timestamp: text(signal.timestampUtc || message.received_at),
        receivedAt: message.received_at, raw: message.raw, payload: item, signal,
        issues: result?.issues ?? [],
        searchable: `${source} ${text(signal.machineId)} ${JSON.stringify(signal)} ${typeof item === 'string' ? item : ''} ${items.length === 1 ? message.raw : ''}`.toLowerCase(),
      }
    }).reverse()
  })
}

export function price(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return '—'
  const number = Number(value)
  return Number.isFinite(number) && number !== 0
    ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 8 }).format(number) : '—'
}

export function timestamp(value) {
  const date = new Date(value)
  return value && !Number.isNaN(date.valueOf()) ? date.toISOString().replace('T', ' ').replace('Z', '') : '—'
}
