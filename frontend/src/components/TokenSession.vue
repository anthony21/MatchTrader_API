<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({ state: Object, busy: Boolean, refreshing: Boolean })
defineEmits(['refresh'])
const now = ref(Date.now())
const offset = ref(0)
watch(() => props.state.server_time, value => {
  const server = Date.parse(value)
  if (Number.isFinite(server)) offset.value = server - Date.now()
  now.value = Date.now()
}, { immediate: true })
const timer = setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => clearInterval(timer))
const expiry = computed(() => Date.parse(props.state.token_expires_at))
const known = computed(() => Number.isFinite(expiry.value))
const remaining = computed(() => Math.max(0, Math.ceil((expiry.value - now.value - offset.value) / 1000)))
const countdown = computed(() => {
  if (!props.state.token_refresh_available) return 'Not connected'
  if (!known.value) return 'Expiration unavailable'
  if (!remaining.value) return 'Expired'
  const hours = Math.floor(remaining.value / 3600)
  const minutes = Math.floor(remaining.value % 3600 / 60)
  const seconds = remaining.value % 60
  return `${hours ? `${hours}:` : ''}${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')} remaining`
})
const expiryLabel = computed(() => known.value ? new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  second: '2-digit', timeZoneName: 'short',
}).format(new Date(expiry.value)) : '')
</script>

<template>
  <section class="card token-panel" aria-label="Session token">
    <div>
      <span class="metric-label">SESSION TOKEN</span>
      <strong class="token-countdown" :class="{ expired: known && remaining === 0 }" data-testid="token-countdown">{{ countdown }}</strong>
      <p v-if="known">Expires <time :datetime="state.token_expires_at" :title="state.token_expires_at">{{ expiryLabel }}</time></p>
      <p v-else>{{ state.token_refresh_available ? 'The token did not provide a readable expiration time.' : 'Connect an account to see its token expiration.' }}</p>
      <p v-if="state.token_message" role="status">{{ state.token_message }}</p>
    </div>
    <button class="secondary" :disabled="busy || !state.token_refresh_available" @click="$emit('refresh')">
      {{ refreshing ? 'Refreshing token…' : 'Refresh token' }}
    </button>
  </section>
</template>

<style scoped>
.token-panel{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:20px 24px;margin-bottom:24px}
.token-countdown{display:block;font-size:22px;font-weight:600;margin-top:8px;font-variant-numeric:tabular-nums}
.token-countdown.expired{color:#a34f37}
p{font-size:12px;line-height:1.6;color:#738296;margin:7px 0 0}
@media(max-width:720px){.token-panel{align-items:flex-start;flex-direction:column;padding:18px}.token-panel button{width:100%}}
</style>
