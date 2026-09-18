<script setup>
defineProps({ state: Object, selected: String, busy: Boolean })
defineEmits(['update:selected', 'connect', 'start', 'stop'])
</script>

<template>
  <section class="controls card" aria-label="Account and bridge controls">
    <div class="account-field">
      <label for="account">Trading account</label>
      <select id="account" :value="selected" :disabled="busy || state.running"
        @change="$emit('update:selected', $event.target.value)">
        <option v-for="account in state.accounts" :key="account.id" :value="account.id">
          {{ account.id }} · {{ account.verified ? 'Verified' : 'Configured' }}
        </option>
      </select>
    </div>
    <button class="secondary" :disabled="busy || state.running || !selected" @click="$emit('connect')">
      Connect account
    </button>
    <div class="control-divider"></div>
    <button class="primary" :disabled="busy || state.running || !selected" @click="$emit('start')">
      <span aria-hidden="true">▶</span> Start capture
    </button>
    <button class="secondary" :disabled="busy || (!state.running && state.connection === 'disconnected')"
      @click="$emit('stop')">Stop &amp; disconnect</button>
  </section>
</template>
