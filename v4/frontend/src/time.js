// Convert known instants in the browser; never invent a timezone for broker text.
export function localTime(value, milliseconds = null, timeZone = undefined) {
  let date
  if (typeof milliseconds === 'number' && Number.isFinite(milliseconds)) {
    date = new Date(milliseconds)
  } else {
    if (!value) return '—'
    if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) return `${value} (timezone unavailable)`
    date = new Date(value)
  }
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    second: '2-digit', timeZoneName: 'short', ...(timeZone ? { timeZone } : {}),
  }).format(date)
}
