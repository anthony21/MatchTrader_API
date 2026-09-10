<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import Orders from '../react/Orders.jsx'
const props = defineProps({ state: Object, mappings: Array, busy: Boolean })
const emit = defineEmits(['refresh'])
const host = ref(null)
let root
function render() {
  if (root) flushSync(() => root.render(createElement(Orders, { state: { ...props.state },
    mappings: [...(props.mappings || [])], busy: props.busy, onRefresh: () => emit('refresh') })))
}
onMounted(() => { root = createRoot(host.value); render() })
watch(() => [props.state, props.mappings, props.busy], render, { deep: true })
onBeforeUnmount(() => root?.unmount())
</script>
<template><div ref="host"></div></template>
