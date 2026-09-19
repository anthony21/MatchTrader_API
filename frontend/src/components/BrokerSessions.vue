<script setup>
import AccountControls from './AccountControls.vue'
defineProps({ brokers: { type: Array, default: () => [] }, selected: String, busy: Boolean })
defineEmits(['select', 'connect', 'disconnect', 'account'])
function localTime(value) { return value ? new Date(value).toLocaleTimeString() : '—' }
</script>
<template>
  <section class="broker-sessions" aria-label="Broker sessions">
    <div class="session-summary"><span class="session-pill">{{ brokers.filter(b => b.state === 'connected').length }} connected</span>
      <p>Your sessions stay available across pages. Tokens renew automatically.</p></div>
    <div class="broker-grid">
      <article v-for="broker in brokers" :key="broker.id" class="card broker-card"
        :class="{ online: broker.state === 'connected', selected: broker.id === selected }" :aria-label="broker.label">
        <div class="broker-heading">
          <div class="broker-identity"><span class="broker-icon" aria-hidden="true">{{ broker.label.slice(0, 1) }}</span>
            <div><h2>{{ broker.label }}</h2><span class="broker-state">{{ broker.state }}</span></div></div>
          <button class="view-pill" :disabled="busy || broker.id === selected"
            @click="$emit('select', broker.id)">{{ broker.id === selected ? 'In view' : 'Use broker' }}</button>
        </div>
        <AccountControls :broker="broker" :busy="busy" @connect="$emit('connect', broker.id)"
          @disconnect="$emit('disconnect', broker.id)" @account="$emit('account', { brokerId: broker.id, accountId: $event })" />
        <div class="session-times"><div><span>Next renewal</span><strong>{{ localTime(broker.refresh_at) }}</strong></div>
          <div><span>Token expires</span><strong>{{ localTime(broker.expires_at) }}</strong></div></div>
        <p v-if="broker.state === 'retrying'" class="session-message" role="alert">{{ broker.message }}</p>
      </article>
    </div>
  </section>
</template>
<style scoped>
.broker-sessions { margin-bottom: 24px; }
.session-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; margin-bottom: 22px; }
.session-summary p { color: #718197; font-size: 13px; }
.session-pill { padding: 8px 14px; border-radius: 20px; background: #e7f3ed; color: #146e5b; font-weight: 600; font-size: 12px; }
.broker-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 330px), 1fr)); gap: 22px; }
.broker-card { padding: 26px; border-top: 4px solid #cbd5df; }
.broker-card.online { border-top-color: #299b72; }
.broker-card.selected { box-shadow: 0 0 0 1px #b6c8d5; }
.broker-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 28px; }
.broker-identity { display: flex; align-items: center; gap: 12px; }
.broker-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 13px; background: #edf1f5; color: #748499; font-weight: 700; font-size: 20px; }
.online .broker-icon { background: #def3e9; color: #16815a; box-shadow: 0 0 0 4px #f0faf5; }
.online h2, .online .broker-state { color: #147957; }
.broker-state { display: block; margin-top: 5px; font-size: 11px; text-transform: capitalize; color: #7b8798; }
.view-pill { min-height: 30px; border-radius: 20px; padding: 6px 12px; font-size: 11px; background: #f7fafc; }
.view-pill:disabled { opacity: 1; color: #688093; }
.session-times { display: flex; gap: 32px; border-top: 1px solid #e9eef2; margin-top: 24px; padding-top: 19px; }
.session-times span { display: block; color: #8390a1; font-size: 11px; margin-bottom: 7px; }
.session-times strong { font-size: 12px; color: #52657e; font-variant-numeric: tabular-nums; }
.session-message { color: #976625; font-size: 12px; line-height: 1.5; }
</style>
