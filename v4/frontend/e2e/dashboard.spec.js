import { test, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { appendFileSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'

const root = resolve('..')
const directory = mkdtempSync(join(tmpdir(), 'matchtrader-ui-test-'))
const ledger = join(directory, 'ledger.csv')
const localEnv = join(directory, '.env')
const url = 'http://127.0.0.1:8766'
let child

test.beforeAll(async () => {
  writeFileSync(ledger, 'utc,kind,label,symbol,side,entry,sl,tp\n')
  writeFileSync(localEnv, `MTR_BRIDGE_TOKEN=stream-test-token-with-32-characters\nMTR_PLATFORM_URL=https://broker.example\nMTR_ACCOUNT_ID=test-account\nMTR_ACCOUNT_IDS=second-test-account\nMTR_R01_LEDGER=${ledger.replaceAll('\\', '/')}\n`)
  const python = process.env.E2E_PYTHON || (process.platform === 'win32'
    ? join(root, '.venv/Scripts/python.exe') : join(root, '.venv/bin/python'))
  const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('MTR_')))
  child = spawn(python, ['-m', 'matchtrader.dashboard.cli', '--port', '8766', '--ws-port', '0', '--env', localEnv,
    '--assets', join(root, 'frontend/dist'), '--data', join(directory, 'data')],
    { cwd: root, env: environment, windowsHide: true, stdio: 'pipe' })
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Test dashboard did not start')), 15000)
    child.on('error', reject)
    child.on('exit', code => reject(new Error(`Test dashboard exited: ${code}`)))
    child.stdout.on('data', data => {
      if (data.toString().includes('Dashboard ready')) { clearTimeout(timeout); resolve() }
    })
  })
})
test.afterAll(() => child?.kill())

test('copy settings save through the real local API without arming', async ({ page }) => {
  await page.goto(url)
  await page.getByRole('button', { name: 'Copy settings', exact: true }).click()
  await page.getByLabel('Machine', { exact: true }).fill('qt')
  await page.getByLabel('Connection ID', { exact: true }).fill('ctrader')
  await page.getByLabel('Quantower internal account ID').fill('source')
  await page.getByLabel('QT symbol', { exact: true }).fill('EUR/USD')
  await page.getByLabel('Aqua symbol', { exact: true }).fill('EURUSD')
  await page.getByLabel('Equivalent instrument and price scale').check()
  await page.getByLabel('This destination is dedicated').check()
  await page.getByLabel('Other copiers, including').check()
  await page.getByRole('button', { name: 'Save copy settings' }).click()
  await expect(page.getByRole('status')).toContainText('Settings saved')
  await page.reload()
  await page.getByRole('button', { name: 'Copy settings', exact: true }).click()
  await expect(page.getByLabel('QT symbol', { exact: true })).toHaveValue('EUR/USD')
  await expect(page.locator('.mode-pill')).toContainText('API trading off')
  await page.screenshot({ path: 'test-results/copy-settings.png', fullPage: true })
})

test('Orders sidebar is accessible on desktop and mobile', async ({ page }) => {
  await page.goto(url)
  await page.getByRole('button', { name: 'Orders', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Orders & positions' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pending orders', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: /Open positions/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/orders-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: 'Orders', exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/orders-mobile.png', fullPage: true })
})

test('account selection, fresh ledger feed, and stop work in the browser', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.request().url().startsWith(url) ? route.continue() : route.abort())
  await page.goto(url)
  await expect(page.getByLabel('Trading account')).toHaveValue('test-account')
  await page.getByRole('button', { name: 'Start capture' }).click()
  await expect(page.getByText('Observing', { exact: true })).toBeVisible()
  appendFileSync(ledger, `${new Date().toISOString()},intent,test-source-order,XAUUSD,short,2400,2410,2380\n`)
  await expect(page.locator('tbody tr').filter({ hasText: 'XAUUSD' })).toContainText('observation')
  await expect(page.getByLabel('Trading account')).toBeDisabled()
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true })
  await page.getByRole('button', { name: 'Stop & disconnect' }).click()
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible()
  await page.getByLabel('Trading account').selectOption('second-test-account')
  await page.getByRole('button', { name: 'Start capture' }).click()
  await expect(page.getByText('Waiting for new events')).toBeVisible()
  await page.getByRole('button', { name: 'Stop & disconnect' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true })
  expect(errors).toEqual([])
})

test('token expiration is visible and manual refresh replaces the countdown', async ({ page }) => {
  let expiry = Date.now() + 60000
  let refreshCalls = 0
  const status = () => ({ account_id: 'test-account', accounts: [{ id: 'test-account', verified: true }],
    running: true, connection: 'connected', orders: [], token_refresh_available: true,
    server_time: new Date().toISOString(), token_expires_at: new Date(expiry).toISOString() })
  await page.route('**/*', route => route.request().url().startsWith(url) ? route.continue() : route.abort())
  await page.route('**/api/status', route => route.fulfill({ json: status() }))
  await page.route('**/api/token/refresh', route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().postDataJSON().account_id).toBe('test-account')
    refreshCalls++
    expiry = Date.now() + 3600000
    return route.fulfill({ json: status() })
  })
  await page.goto(url)
  const token = page.getByRole('region', { name: 'Session token' })
  await expect(token.getByTestId('token-countdown')).toContainText('remaining')
  const before = await token.locator('time').getAttribute('datetime')
  await token.getByRole('button', { name: 'Refresh token', exact: true }).click()
  await expect(token.locator('time')).not.toHaveAttribute('datetime', before)
  await expect(page.getByLabel('Trading account')).toHaveValue('test-account')
  expect(refreshCalls).toBe(1)
  await page.screenshot({ path: 'test-results/token-session-desktop.png', fullPage: true })
})

test('React incoming trades show mapped lifecycle and filter accounts on desktop and mobile', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const sample = (id, account, source, kind, opened) => ({
    id, trade_id: `trade-${id}-sample`, account_id: account, machine: 'QT workstation', connection_id: 'Demo feed',
    symbol: id === '1' ? 'XAUUSD' : 'EURUSD', side: id === '1' ? 'SELL' : 'BUY', kind, action: 'OBSERVE',
    emitted_at: '2026-09-09T19:30:00Z', received_at: '2026-09-09T19:30:01Z', quantity: '0.0700', quantity_unit: 'lots',
    price: id === '1' ? '2443.49000' : '1.123456789', sl: id === '1' ? '2447.04000' : '1.12000',
    tp: id === '1' ? '2436.38000' : '1.13000', decision: 'captured', order_id: `QT-${id}`,
    reason: 'Source event recorded', meaning: { version: '1.0.0', source: { code: source, label: `${source} strategy`, basis: 'trade origin' },
      event: { label: kind === 'FILL' ? 'Fill' : 'Position', description: 'Source lifecycle evidence' },
      action: { label: 'Observe' }, opened: { state: opened, label: opened === 'confirmed' ? 'Opening fill' : 'Position observed' }, result: 'Captured' },
  })
  await page.route('**/api/capture/stream', route => route.abort())
  await page.route('**/api/capture/events', route => route.fulfill({ json: { events: [
    sample('1', 'Source A', 'R01', 'FILL', 'confirmed'), sample('2', 'Source B', 'X17', 'POSITION', 'observed'),
  ] } }))
  await page.route('**/api/events', route => route.fulfill({ json: { account_id: 'second-test-account', events: [] } }))
  await page.goto(url)
  const board = page.getByRole('region', { name: 'Incoming trade activity' })
  await expect(board.getByRole('heading', { name: 'Incoming trades' })).toBeVisible()
  await expect(board.locator('tbody tr')).toHaveCount(2)
  await expect(board.locator('th').last()).toHaveText('Trade ID')
  await expect(board.locator('tbody')).toContainText('1.123456789')
  await expect(board.locator('tbody')).toContainText('Opening fill')
  await page.screenshot({ path: 'test-results/incoming-desktop.png', fullPage: true })
  await board.locator('summary').click()
  await board.getByLabel('Source A', { exact: false }).check()
  await expect(board.locator('tbody tr')).toHaveCount(1)
  await board.getByLabel('Source B', { exact: false }).check()
  await expect(board.locator('tbody tr')).toHaveCount(2)
  await board.locator('summary').click()
  await board.getByRole('button', { name: 'X17', exact: true }).click()
  await expect(board.locator('tbody tr')).toHaveCount(1)
  await expect(board.locator('tbody')).toContainText('Position observed')
  await board.getByRole('button', { name: 'Details for trade-2-sample' }).click()
  await expect(board.locator('tbody')).toContainText('QT-2')
  await board.getByRole('button', { name: 'All sources' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await board.scrollIntoViewIfNeeded()
  await expect(board.locator('summary')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
  await board.getByRole('region', { name: 'Trade event table' }).evaluate(el => { el.scrollLeft = 0 })
  await page.screenshot({ path: 'test-results/incoming-mobile.png', fullPage: true })
  expect(errors).toEqual([])
})

test('native events arrive through push with polling blocked and recover on reload', async ({ page }) => {
  await page.route('**/api/capture/events', route => route.abort())
  await page.goto(url)
  await expect(page.getByText('● Live push', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Start capture' }).click()
  const latencies = []
  for (let i = 0; i < 3; i++) {
    const symbol = `PUSH${i}`
    const status = await page.evaluate(async ({ symbol, i }) => {
      window.pushStart = performance.now()
      window.pushLatency = null
      const observer = new MutationObserver(() => {
        if ([...document.querySelectorAll('.incoming-symbol')].some(el => el.textContent === symbol)) {
          window.pushLatency = performance.now() - window.pushStart
          observer.disconnect()
        }
      })
      observer.observe(document.querySelector('.incoming-workspace'), { subtree: true, childList: true })
      const response = await fetch('/capture/events', {
        method: 'POST', headers: { Authorization: 'Bearer stream-test-token-with-32-characters', 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: `push-${i}`, machine: 'test', connection_id: 'test', account_id: 'test-source',
          emitted_at: new Date().toISOString(), kind: 'FILL', action: 'OBSERVE', source: 'X17',
          execution_id: `execution-${i}`, order_id: `order-${i}`, fill_effect: 'OPEN', quantity: '0.01', symbol }),
      })
      return response.status
    }, { symbol, i })
    expect(status).toBe(202)
    await expect(page.locator('.incoming-symbol').filter({ hasText: symbol })).toBeVisible()
    const latency = await page.evaluate(() => window.pushLatency)
    expect(latency).toBeLessThan(1000)
    latencies.push(Math.round(latency))
  }
  console.log(`Local POST-to-render milliseconds (test data): ${latencies.join(', ')}`)
  await page.reload()
  await expect(page.getByText('● Live push', { exact: true })).toBeVisible()
  await expect(page.locator('.incoming-symbol').filter({ hasText: 'PUSH2' })).toBeVisible()
  await page.getByRole('button', { name: 'Stop & disconnect' }).click()
  await expect(page.locator('.mode-pill')).toContainText('API trading off')
})

test('Orders cards show readable trades and keep full IDs in expandable details on desktop and mobile', async ({ page }) => {
  const errorMessages = []
  page.on('pageerror', error => errorMessages.push(error.message))
  const time = '2026-09-10T19:30:00Z'
  const record = { trade_id: 'test-internal-reference-001', symbol: 'EURUSD', side: 'BUY', source: 'R01', state: 'observed',
    source_scope: ['QT machine', 'Demo connection', 'Source account'], account_id: '', mapping_status: 'incomplete', updated_at: time,
    reasons: ['No broker order linked yet'], quantities: [], links: [], actions: [], fills: [] }
  await page.route('**/api/status', async route => {
    const response = await route.fetch()
    const state = await response.json()
    await route.fulfill({ json: { ...state, connection: 'disconnected', orders_at: time, positions_at: time,
      positions: [{ id: 'broker-position-test', symbol: 'XAUUSD', side: 'SELL', volume: '0.0700', openPrice: '2443.49000', stopLoss: '2447.04000', takeProfit: '2436.38000', netProfit: '49.77', openTime: time },
        { id: 'second-position-test', symbol: 'EURUSD', side: 'BUY', volume: '0.20', openPrice: '1.123456789', profit: '-8.20', openTime: time }],
      orders: [{ id: 'broker-order-test', symbol: 'EURUSD', side: 'BUY', type: 'LIMIT', volume: '0.10', activationPrice: '1.12000', stopLoss: '1.11500', takeProfit: '1.13000', creationTimeIso: time }] } })
  })
  await page.route('**/api/trade-mappings', async route => {
    const response = await route.fetch(); const json = await response.json()
    await route.fulfill({ json: { ...json, mappings: [record] } })
  })
  await page.goto(url)
  await page.getByRole('button', { name: 'Orders', exact: true }).click()
  const board = page.getByRole('region', { name: 'Orders workspace' })
  await expect(board.locator('.order-card')).toHaveCount(2)
  await expect(board.locator('.order-profit').first()).toContainText('+49.77')
  await expect(board.getByText('broker-position-test', { exact: true })).not.toBeVisible()
  await page.screenshot({ path: 'test-results/orders-cards-desktop.png', fullPage: true })
  await board.getByRole('navigation', { name: 'Order views' }).getByRole('button', { name: 'Pending orders' }).click()
  await expect(board.locator('.order-card')).toContainText('Waiting to fill')
  await board.getByRole('navigation', { name: 'Order views' }).getByRole('button', { name: 'Copy activity' }).click()
  await expect(board.locator('.order-identity h4')).toHaveText('EURUSD')
  await expect(board.getByText(record.trade_id, { exact: true })).not.toBeVisible()
  await page.screenshot({ path: 'test-results/orders-activity-desktop.png', fullPage: true })
  await board.locator('.order-details > summary').click()
  await expect(board.getByText(record.trade_id, { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
  await page.screenshot({ path: 'test-results/orders-cards-mobile.png', fullPage: true })
  expect(errorMessages).toEqual([])
})
