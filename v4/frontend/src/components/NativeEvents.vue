<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import IncomingTrades from '../react/IncomingTrades.jsx'
const props = defineProps({ events: Array, legacyEvents: Array, state: Object, busy: Boolean, streamStatus: String })
const emit = defineEmits(['toggle'])
const host = ref(null)
let root
function render() {
  if (root) flushSync(() => root.render(createElement(IncomingTrades, {
    events: [...(props.events ?? [])], legacyEvents: [...(props.legacyEvents ?? [])],
    state: { ...props.state }, streamStatus: props.streamStatus, busy: props.busy, onToggle: () => emit('toggle'),
  })))
}
onMounted(() => { root = createRoot(host.value); render() })
watch(() => [props.events, props.legacyEvents, props.state, props.busy, props.streamStatus], render, { deep: true })
onBeforeUnmount(() => root?.unmount())
</script>
<template><div ref="host"></div></template>
