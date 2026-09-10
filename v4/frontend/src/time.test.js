import { expect, test } from 'vitest'
import { localTime } from './time.js'

test('converts instants across dates and daylight saving time', () => {
  const summer = localTime('2026-09-10T01:37:03.439Z', null, 'America/Los_Angeles')
  expect(summer).toContain('Sep 9, 2026')
  expect(summer).toContain('06:37:03 PM')
  expect(summer).toContain('PDT')
  expect(localTime('2026-01-10T01:37:03Z', null, 'America/Los_Angeles')).toContain('PST')
  expect(localTime('2026-09-09T18:37:03.439-07:00', null, 'America/Los_Angeles')).toBe(summer)
})

test('prefers broker epoch milliseconds and does not guess unknown timezones', () => {
  expect(localTime('unknown', 0, 'UTC')).toContain('1970')
  expect(localTime('2026-09-10T01:37:03')).toContain('timezone unavailable')
  expect(localTime(null)).toBe('—')
  expect(localTime('invalidZ')).toBe('—')
})
