<script setup>
defineProps({ state: Object, selected: String, busy: Boolean })
defineEmits(['start', 'stop'])
</script>

<template>
  <section class="controls card" aria-label="Account and bridge controls">
    <button class="primary" :disabled="busy || state.running || !selected" @click="$emit('start')">
      <span aria-hidden="true">▶</span> Start capture
    </button>
    <button class="secondary" :disabled="busy || (!state.running && state.connection === 'disconnected')"
      @click="$emit('stop')">Stop &amp; disconnect</button>
  </section>
</template>
