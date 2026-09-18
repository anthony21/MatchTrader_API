import { mount } from '@vue/test-utils'
import { afterEach, expect, test, vi } from 'vitest'
import TokenSession from './TokenSession.vue'

afterEach(() => vi.useRealTimers())
test('counts down the exact expiry, updates after refresh, and stops at expired', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-09T18:00:00Z'))
  const state = { token_refresh_available: true, token_expires_at: '2026-09-09T18:00:02Z', server_time: '2026-09-09T18:00:00Z' }
  const wrapper = mount(TokenSession, { props: { state } })
  expect(wrapper.get('time').attributes('datetime')).toBe(state.token_expires_at)
  expect(wrapper.text()).toContain('00:02 remaining')
  await vi.advanceTimersByTimeAsync(2000)
  expect(wrapper.text()).toContain('Expired')
  await wrapper.setProps({ state: { ...state, token_expires_at: '2026-09-09T19:00:02Z', server_time: '2026-09-09T18:00:02Z' } })
  expect(wrapper.text()).toContain('1:00:00 remaining')
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('refresh')).toHaveLength(1)
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

test('uses server clock and keeps refresh available during capture', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-09T18:05:00Z'))
  const wrapper = mount(TokenSession, { props: { state: { running: true, token_refresh_available: true,
    server_time: '2026-09-09T18:00:00Z', token_expires_at: '2026-09-09T18:01:00Z' } } })
  expect(wrapper.text()).toContain('01:00 remaining')
  expect(wrapper.get('button').element.disabled).toBe(false)
  await wrapper.setProps({ busy: true, refreshing: true })
  expect(wrapper.get('button').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('Refreshing token')
  wrapper.unmount()
})

test('does not invent an expiry when disconnected or token claims are missing', async () => {
  const wrapper = mount(TokenSession, { props: { state: {} } })
  expect(wrapper.text()).toContain('Not connected')
  expect(wrapper.get('button').element.disabled).toBe(true)
  await wrapper.setProps({ state: { token_refresh_available: true, token_expires_at: null, token_message: 'Token refresh failed.' } })
  expect(wrapper.text()).toContain('Expiration unavailable')
  expect(wrapper.text()).toContain('Token refresh failed.')
  expect(wrapper.get('button').element.disabled).toBe(false)
  wrapper.unmount()
})
