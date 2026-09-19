import { afterEach, expect, test, vi } from 'vitest'
import schema from '../../../docs/SIGNAL_SCHEMA.json'
import { COLUMN_STORAGE_KEY, columnValue, DEFAULT_COLUMNS, displayValue, loadColumns, saveColumns, SIGNAL_COLUMNS } from './signalColumns.js'

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

test('catalog contains every schema field once plus lane', () => {
  const keys = SIGNAL_COLUMNS.map(column => column.key)
  expect(keys.filter(key => key !== 'lane').sort()).toEqual(Object.keys(schema.properties).sort())
  expect(new Set(keys).size).toBe(44)
})

test('preferences handle stale, corrupted and unavailable browser storage', () => {
  expect(loadColumns()).toEqual(DEFAULT_COLUMNS)
  saveColumns(['ladderArm', 'volume'])
  expect(loadColumns()).toEqual(['volume', 'ladderArm'])
  localStorage.setItem(COLUMN_STORAGE_KEY, '["missing", "machineId", "machineId"]')
  expect(loadColumns()).toEqual(['machineId'])
  localStorage.setItem(COLUMN_STORAGE_KEY, 'not json')
  expect(loadColumns()).toEqual(DEFAULT_COLUMNS)
  vi.stubGlobal('localStorage', { getItem() { throw Error('denied') }, setItem() { throw Error('denied') } })
  expect(loadColumns()).toEqual(DEFAULT_COLUMNS)
  expect(() => saveColumns(['lane'])).not.toThrow()
})

test('schema cells preserve false, zero, objects and null while retaining default display values', () => {
  const row = { side: 'SELL', timestamp: '2026-09-18T22:00:00Z', signal: { dryRun: false, volume: '0', instrument: { tickSize: 0.01 }, brokerOrderId: '' } }
  expect(columnValue(row, 'side')).toBe('SELL')
  expect(columnValue(row, 'timestampUtc')).toBe(row.timestamp)
  expect(displayValue(columnValue(row, 'dryRun'))).toBe('false')
  expect(displayValue(columnValue(row, 'volume'))).toBe('0')
  expect(displayValue(columnValue(row, 'instrument'))).toBe('{"tickSize":0.01}')
  expect(displayValue(columnValue(row, 'brokerOrderId'))).toBe('—')
  expect(displayValue(null)).toBe('null')
})
