import { test, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
const root = resolve('..'), dir = mkdtempSync(join(tmpdir(), 'closed-history-ui-'))
const url = 'http://127.0.0.1:8768'
let child
test.beforeAll(async () => {
  const env = join(dir, '.env')
  writeFileSync(env, 'MTR_PLATFORM_URL=https://broker.example\nMTR_ACCOUNT_ID=test-account\nMTR_BRIDGE_TOKEN=history-test-token-with-32-characters\n')
  child = spawn(process.env.E2E_PYTHON, ['-m', 'matchtrader.dashboard.cli', '--port', '8768', '--ws-port', '0', '--env', env, '--assets', join(root, 'frontend/dist'), '--data', join(dir, 'data')], { cwd: root, env: process.env, windowsHide: true, stdio: 'pipe' })
  await new Promise((done, fail) => {
    const timeout = setTimeout(() => fail(Error('Dashboard did not start')), 15000)
    child.on('error', fail)
    child.stdout.on('data', data => { if (data.toString().includes('Dashboard ready')) { clearTimeout(timeout); done() } })
  })
})
test.afterAll(() => child?.kill())
test('Closed trades shows dates, prices, exit reasons and details on desktop and mobile', async ({ page }) => {
  let reads = 0
  await page.route('**/api/status', async route => {
    const response = await route.fetch()
    await route.fulfill({ json: { ...await response.json(), connection: 'connected' } })
  })
  await page.route('**/api/orders/refresh', route => route.fulfill({ json: {} }))
  await page.route('**/api/positions/refresh', route => route.fulfill({ json: {} }))
  await page.route('**/api/orders/closed', async route => {
    reads++
    expect(route.request().postDataJSON().account_id).toBe('test-account')
    await route.fulfill({ json: { account_id: 'test-account', currency: 'USD', updated_at: '2026-09-11T07:00:00Z',
      summary: { closed: 1, wins: 0, losses: 1, breakevens: 0, net_profit: '-24.66' },
      operations: [{ id: 'history-order', uid: 'close1', symbol: 'NAS100', side: 'SELL', volume: '0.2', openPrice: '29167.02', stopLoss: '29177.36', takeProfit: '29145.67', closePrice: '29177.74', netProfit: '-24.66', closeReason: 'CLOSE_REASON_STOP_LOSS', time: '2026-09-10T15:00:00Z' }] } })
  })
  await page.goto(url)
  await page.getByRole('button', { name: 'Orders', exact: true }).click()
  await page.getByRole('button', { name: 'Closed trades', exact: true }).click()
  expect(reads).toBe(0)
  await page.getByLabel('From date', { exact: true }).fill('2026-09-09')
  await page.getByLabel('Through date').fill('2026-09-10')
  await page.getByRole('button', { name: 'Load closed trades' }).click()
  await expect(page.getByRole('cell', { name: '29177.74', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Stop loss', exact: true })).toBeVisible()
  await page.getByText('View trade', { exact: true }).click()
  await expect(page.getByText('history-order', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/closed-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/closed-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByLabel('From date', { exact: true }).fill('2026-09-08')
  await expect(page.getByText('history-order', { exact: true })).toHaveCount(0)
  expect(reads).toBe(1)
})
