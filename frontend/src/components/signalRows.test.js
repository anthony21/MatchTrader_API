import { expect, test } from 'vitest'
import { price, signalLane, signalRows, timestamp } from './signalRows.js'

test('parsed source and order projection supply rows while retaining raw payload and diagnostics', () => {
  const rows = signalRows([{ id: 10, raw: '[{"source":"r01Auto"},42]', received_at: '2030-01-01T00:00:00Z',
    signals: [{ index: 0, signal: { source: 'r01Auto', machineId: 'machine', ladderGrade: 'STRONG', grade: 'OTHER' },
      shapes: { r01OrderShape: { orderSide: 'BUY', price: '123.456', slPrice: '120', tpPrice: '130' } }, issues: [] },
      { index: 1, signal: null, issues: [{ field: '', message: 'Expected object' }] }],
  }])
  const row = rows.find(r => r.id === '10:0')
  expect(row).toMatchObject({ lane: 'R01', machineId: 'machine', side: 'BUY', entry: '123.456', stopLoss: '120', takeProfit: '130', ladderGrade: 'STRONG' })
  expect(rows.find(r => r.id === '10:1').issues).toHaveLength(1)
  expect(row.payload).toEqual({ source: 'r01Auto' })
})

test('legacy batches and unknown senders remain visible with individual identity', () => {
  expect(signalRows([{ id: 1, payload: [{ source: 'r01Local' }, { source: 'CustomSender' }] }]).map(r => r.lane)).toEqual(['CUSTOMSENDER', 'R01'])
  expect(signalLane('r010')).toBe('R010')
  expect(signalLane('chain', { detail: 'x17-spine level' })).toBe('X17')
  expect(signalLane('chain')).toBe('CHAIN')
  expect(signalLane('panel', { label: 'P01RR_123_1' })).toBe('P01')
  expect(signalLane('panel')).toBe('PANEL')
  expect(signalRows([{ id: 2, source: 'StrategyManager', raw: 'plain text' }])[0].searchable).toContain('plain text')
})

test('display formatting handles missing values, float tails, UTC and precise original values', () => {
  expect(price(81194.12000000002)).toBe('81,194.12')
  expect(price('0.00000001')).toBe('0.00000001')
  for (const value of [0, '', null, undefined, 'bad', false]) expect(price(value)).toBe('—')
  expect(timestamp('2026-09-18T17:35:27-05:00')).toBe('2026-09-18 22:35:27.000')
  expect(timestamp('bad')).toBe('—')
})
