import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import BrokerSessions from './BrokerSessions.vue'

test('broker cards show green connections and independent account actions', async () => {
  const wrapper = mount(BrokerSessions, { props: { selected: 'AQUA', brokers: [
    { id: 'AQUA', label: 'AquaFunded', state: 'connected', accounts: ['123', '456'], selected_account: '123' },
    { id: 'GTR', label: 'GooeyTrade', state: 'disconnected', accounts: [], selected_account: '' },
  ] } })
  const cards = wrapper.findAll('article')
  expect(cards[0].classes()).toContain('online')
  expect(cards[1].classes()).not.toContain('online')
  expect(cards[0].get('select').findAll('option')).toHaveLength(2)
  expect(cards[1].get('select').element.disabled).toBe(true)
  await cards[1].get('button.primary').trigger('click')
  expect(wrapper.emitted('connect')).toEqual([['GTR']])
  await cards[0].get('select').setValue('456')
  expect(wrapper.emitted('account')).toEqual([[{ brokerId: 'AQUA', accountId: '456' }]])
  await cards[1].get('.view-pill').trigger('click')
  expect(wrapper.emitted('select')).toEqual([['GTR']])
})
