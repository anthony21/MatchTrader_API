<script setup>
import { computed, ref, watch } from 'vue'
const props = defineProps({ broker: Object, busy: Boolean })
defineEmits(['connect', 'disconnect', 'account'])
const accounts = computed(() => props.broker.accounts?.length ? props.broker.accounts : props.broker.configured_accounts ?? [])
const connected = computed(() => props.broker.state === 'connected')
const choice = ref(props.broker.selected_account || '')
watch(() => props.broker.selected_account, value => { choice.value = value || '' })
</script>
<template>
  <section class="controls card account-controls" :aria-label="`${broker.label} trading account`">
    <div class="account-field">
      <label :for="`account-${broker.id}`">Trading account</label>
      <select :id="`account-${broker.id}`" v-model="choice"
        :disabled="busy || broker.capture_running || !accounts.length" @change="$emit('account', $event.target.value)">
        <option v-if="!accounts.length" value="">Connect to discover accounts</option>
        <option v-for="account in accounts" :key="account" :value="account">{{ account }}</option>
      </select>
      <span class="account-state" :class="{ connected }" role="status"><span class="status-dot" :class="{ on: connected }"></span>
        {{ connected ? 'Connected' : broker.state === 'retrying' ? 'Reconnecting' : 'Disconnected' }}</span>
      <div class="account-actions">
        <button class="primary" :disabled="busy || connected" @click="$emit('connect')">Connect</button>
        <button class="secondary" :disabled="busy || broker.state === 'disconnected'" @click="$emit('disconnect')">Disconnect</button>
      </div>
      <p v-if="broker.capture_running" class="account-note">Stop capture on Trading bridge to change accounts.</p>
    </div>
  </section>
</template>
<style scoped>
.account-controls { margin: 0; border: 0; box-shadow: none; padding: 0; background: transparent; }
.account-field { max-width: none; min-width: 0; }
.account-field select { border-radius: 22px; background: #f7fafc; }
.account-state { display: block; margin: 16px 0; font-size: 12px; color: #718197; font-weight: 600; }
.account-state.connected { color: #146e5b; }
.account-actions { display: flex; gap: 10px; }
.account-actions button { flex: 1; }
.account-actions button:disabled { background: #eff2f5; border-color: #e0e6ed; color: #94a0af; opacity: 1; }
.account-note { font-size: 12px; line-height: 1.5; color: #718197; margin-bottom: 0; }
</style>
