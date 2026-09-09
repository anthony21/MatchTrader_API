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
  writeFileSync(localEnv, `MTR_PLATFORM_URL=https://broker.example\nMTR_ACCOUNT_ID=test-account\nMTR_ACCOUNT_IDS=second-test-account\nMTR_R01_LEDGER=${ledger.replaceAll('\\', '/')}\n`)
  const python = process.env.E2E_PYTHON || (process.platform === 'win32'
    ? join(root, '.venv/Scripts/python.exe') : join(root, '.venv/bin/python'))
  const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('MTR_')))
  child = spawn(python, ['-m', 'matchtrader.dashboard.cli', '--port', '8766', '--env', localEnv,
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

test('account selection, fresh ledger feed, and stop work in the browser', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.request().url().startsWith(url) ? route.continue() : route.abort())
  await page.goto(url)
  await expect(page.getByLabel('Trading account')).toHaveValue('test-account')
  await page.getByRole('button', { name: 'Start shadow bridge' }).click()
  await expect(page.getByText('Observing', { exact: true })).toBeVisible()
  appendFileSync(ledger, `${new Date().toISOString()},intent,test-source-order,XAUUSD,short,2400,2410,2380\n`)
  await expect(page.locator('tbody tr').filter({ hasText: 'XAUUSD' })).toContainText('observation')
  await expect(page.getByLabel('Trading account')).toBeDisabled()
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true })
  await page.getByRole('button', { name: 'Stop & disconnect' }).click()
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible()
  await page.getByLabel('Trading account').selectOption('second-test-account')
  await page.getByRole('button', { name: 'Start shadow bridge' }).click()
  await expect(page.getByText('Waiting for new events')).toBeVisible()
  await page.getByRole('button', { name: 'Stop & disconnect' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true })
  expect(errors).toEqual([])
})
