export const COLUMN_STORAGE_KEY = 'hcamm.tradingBridge.columns.v1'
export const DEFAULT_COLUMNS = ['lane', 'machineId', 'side', 'entry', 'stopLoss', 'takeProfit', 'ladderGrade', 'timestampUtc']

const column = (key, label, group) => ({ key, label, group })
export const SIGNAL_COLUMNS = [
  column('lane', 'Lane', 'Sender'),
  column('machineId', 'Machine ID', 'Sender'),
  column('side', 'Side', 'Trade'),
  column('entry', 'Entry', 'Trade'),
  column('stopLoss', 'Stop loss', 'Trade'),
  column('takeProfit', 'Take profit', 'Trade'),
  column('ladderGrade', 'Ladder grade', 'Grade and context'),
  column('timestampUtc', 'Timestamp · UTC', 'Event'),
  column('source', 'Source', 'Sender'),
  column('robotName', 'Robot name', 'Sender'),
  column('accountId', 'Account ID', 'Sender'),
  column('connectionName', 'Connection name', 'Sender'),
  column('kind', 'Event type', 'Event'),
  column('mode', 'Mode', 'Event'),
  column('clientEventId', 'Client event ID', 'Event'),
  column('refClientEventId', 'Reference event ID', 'Event'),
  column('sequence', 'Sequence', 'Event'),
  column('detail', 'Detail', 'Event'),
  column('label', 'Label', 'Lifecycle and range'),
  column('brokerOrderId', 'Broker order ID', 'Lifecycle and range'),
  column('brokerPositionId', 'Broker position ID', 'Lifecycle and range'),
  column('rangeKind', 'Range kind', 'Lifecycle and range'),
  column('wasBeyond', 'Was beyond', 'Lifecycle and range'),
  column('wallId', 'Wall ID', 'Lifecycle and range'),
  column('boxInstanceId', 'Box instance ID', 'Lifecycle and range'),
  column('symbol', 'Symbol', 'Trade'),
  column('orderType', 'Order type', 'Trade'),
  column('volume', 'Volume', 'Trade'),
  column('instrument', 'Instrument metadata', 'Trade'),
  column('grade', 'Grade', 'Grade and context'),
  column('ladderArm', 'Ladder arm', 'Grade and context'),
  column('stamp', 'Stamp', 'Grade and context'),
  column('tapHash', 'Tap hash', 'Grade and context'),
  column('tier', 'Tier', 'Grade and context'),
  column('cell', 'Cell', 'Grade and context'),
  column('rfx', 'RFX', 'Grade and context'),
  column('inverted', 'Inverted', 'Grade and context'),
  column('dryRun', 'Dry run', 'Grade and context'),
  column('l2Class', 'L2 class', 'L2'),
  column('l2Word', 'L2 word', 'L2'),
  column('l2DbandDigit', 'L2 D-band digit', 'L2'),
  column('l2BirthRank', 'L2 birth rank', 'L2'),
  column('l2ChurnBand', 'L2 churn band', 'L2'),
  column('l2PosInWin', 'L2 position in win', 'L2'),
]

export function loadColumns() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMN_STORAGE_KEY))
    if (Array.isArray(saved)) {
      const known = SIGNAL_COLUMNS.filter(column => saved.includes(column.key)).map(column => column.key)
      if (known.length) return known
    }
  } catch { /* Browser storage may be unavailable. */ }
  return [...DEFAULT_COLUMNS]
}

export function saveColumns(keys) {
  try { localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(keys)) } catch { /* Keep the in-memory selection. */ }
}

export function columnValue(row, key) {
  if (key === 'timestampUtc') return row.timestamp
  if (['lane', 'machineId', 'side', 'entry', 'stopLoss', 'takeProfit', 'ladderGrade'].includes(key)) return row[key]
  return row.signal?.[key]
}

export function displayValue(value) {
  if (value === undefined || value === '') return '—'
  if (value === null) return 'null'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
