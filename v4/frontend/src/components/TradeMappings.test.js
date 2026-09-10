import { mount } from '@vue/test-utils'
import { expect, test } from 'vitest'
import TradeMappings from './TradeMappings.vue'

test('shows independent identities, partials, merge evidence and uncertain actions', () => {
  const wrapper = mount(TradeMappings, { props: { mappings: [{ trade_id: 'trade1', broker: 'Aqua', account_id: 'demo',
    state: 'uncertain', mapping_status: 'uncertain', reasons: ['Merged source position requires allocation'],
    links: [{ side: 'source', scope: ['machine', 'connection', 'source'], kind: 'order', native_id: 'qt-order' },
      { side: 'destination', scope: ['Aqua', 'demo'], kind: 'order', native_id: 'broker-order' },
      { side: 'source', scope: ['machine', 'connection', 'source'], kind: 'position', native_id: 'merged',
        contributors: ['trade1', 'trade2'], observed_open_contribution: '.4', observed_close_contribution: '0' }],
    fills: [{ side: 'source', scope: 'source', execution_id: 'fill1', quantity: '.4', price: '1.15', effect: 'OPEN' }],
    quantities: [{ side: 'source', scope: 'source', unit: 'contracts', requested: '1', cumulative: '.4', remaining: '.6', partial: true }],
    actions: [{ action_key: 'CLOSE:c1', action: 'CLOSE', outcome: 'uncertain', request_id: 'c1', request: { positionId: 'broker-position' } }],
  }] } })
  for (const text of ['qt-order', 'broker-order', 'Partial fill', 'Merged position', 'trade2', 'unconfirmed', 'fill1', 'broker-position', 'uncertain']) {
    expect(wrapper.text()).toContain(text)
  }
  wrapper.unmount()
})

test('empty mappings do not imply an account is reconciled', () => {
  expect(mount(TradeMappings).text()).toContain('No captured trade mappings')
})
