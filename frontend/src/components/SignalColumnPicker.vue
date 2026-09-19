<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { DEFAULT_COLUMNS, SIGNAL_COLUMNS } from './signalColumns.js'

const props = defineProps({ modelValue: { type: Array, required: true } })
const emit = defineEmits(['update:modelValue'])
const open = ref(false), group = ref(''), search = ref('')
const trigger = ref(null), panel = ref(null), placement = ref({})
const groups = [...new Set(SIGNAL_COLUMNS.map(column => column.group))]
const matches = column => `${column.label} ${column.key} ${column.group}`.toLowerCase().includes(search.value.toLowerCase())
const visibleGroups = computed(() => groups.filter(name => SIGNAL_COLUMNS.some(column => column.group === name && matches(column))))
const attributes = computed(() => SIGNAL_COLUMNS.filter(column => column.group === group.value && matches(column)))
const groupCount = name => SIGNAL_COLUMNS.filter(column => column.group === name).length
const selectedCount = name => SIGNAL_COLUMNS.filter(column => column.group === name && props.modelValue.includes(column.key)).length

function position() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const width = Math.min(320, window.innerWidth - 24)
  const below = window.innerHeight - rect.bottom - 18
  const above = rect.top - 18
  const upwards = below < 240 && above > below
  const height = Math.max(120, Math.min(480, upwards ? above : below))
  placement.value = {
    width: `${width}px`, maxHeight: `${height}px`,
    left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`,
    ...(upwards ? { bottom: `${window.innerHeight - rect.top + 6}px` } : { top: `${rect.bottom + 6}px` }),
  }
}
async function toggle() {
  if (open.value) return close()
  group.value = ''; search.value = ''; open.value = true
  position()
  await nextTick()
  panel.value?.querySelector('input[type="search"]')?.focus()
}
function close(restoreFocus = true) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
async function chooseGroup(name) {
  group.value = name
  await nextTick()
  panel.value?.querySelector('.group-back')?.focus()
}
async function back() {
  group.value = ''; search.value = ''
  await nextTick()
  panel.value?.querySelector('.group-button')?.focus()
}
function select(key, checked) {
  const keys = props.modelValue.filter(value => value !== key)
  if (checked) keys.push(key)
  if (keys.length) emit('update:modelValue', keys)
}
function outside(event) {
  if (open.value && !trigger.value?.contains(event.target) && !panel.value?.contains(event.target)) close(false)
}
function keyboard(event) {
  if (open.value && event.key === 'Escape') { event.preventDefault(); close() }
}
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  document.addEventListener('keydown', keyboard)
  window.addEventListener('resize', position)
  window.addEventListener('scroll', position, true)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('keydown', keyboard)
  window.removeEventListener('resize', position)
  window.removeEventListener('scroll', position, true)
})
</script>

<template>
  <button ref="trigger" class="columns-button" aria-label="Filter columns" aria-haspopup="dialog"
    :aria-expanded="open" :title="`Filter columns (${modelValue.length}/${SIGNAL_COLUMNS.length} selected)`" @click="toggle">
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
      <path d="M3 4h14l-5.5 6v5l-3 1v-6z" stroke-linejoin="round" />
    </svg>
  </button>
  <Teleport to="body">
    <section v-if="open" ref="panel" class="column-dropdown" :style="placement" role="dialog" aria-label="Column filters">
      <div class="dropdown-heading"><strong>Columns</strong><span>{{ modelValue.length }}/{{ SIGNAL_COLUMNS.length }} selected</span>
        <button class="close-picker" aria-label="Close column filters" @click="close()">×</button></div>
      <div class="column-search"><input v-model="search" type="search" aria-label="Find group or field" placeholder="Find group or field" /></div>
      <div v-if="!group" class="group-list">
        <button v-for="name in visibleGroups" :key="name" class="group-button" :aria-label="`${name} columns`" @click="chooseGroup(name)">
          <span>{{ name }}</span><small>{{ selectedCount(name) }}/{{ groupCount(name) }}</small><span aria-hidden="true">›</span>
        </button>
        <p v-if="!visibleGroups.length" class="no-columns">No groups match your search.</p>
      </div>
      <template v-else>
        <button class="group-back" @click="back"><span aria-hidden="true">‹</span> All groups</button>
        <fieldset class="attribute-list"><legend>{{ group }}</legend>
          <label v-for="column in attributes" :key="column.key" class="column-option">
            <input type="checkbox" :value="column.key" :checked="modelValue.includes(column.key)" :aria-label="`Show ${column.key} column`"
              :disabled="modelValue.length === 1 && modelValue.includes(column.key)" @change="select(column.key, $event.target.checked)" />
            <span>{{ column.label }}<small>{{ column.key }}</small></span>
          </label>
          <p v-if="!attributes.length" class="no-columns">No fields match your search.</p>
        </fieldset>
      </template>
      <div class="column-actions">
        <button @click="emit('update:modelValue', SIGNAL_COLUMNS.map(column => column.key))">Select all</button>
        <button @click="emit('update:modelValue', [...DEFAULT_COLUMNS])">Restore defaults</button>
      </div>
    </section>
  </Teleport>
</template>

<style scoped>
.columns-button { display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; min-height: 28px; width: 28px; padding: 5px; margin-right: 9px; border-color: #dce6ed; background: white; color: #276959; border-radius: 5px; }
.columns-button[aria-expanded="true"] { background: #e5f5ed; border-color: #90bfac; }
.column-dropdown { position: fixed; z-index: 100; display: flex; flex-direction: column; overflow: hidden; border: 1px solid #dce5ec; border-radius: 10px; background: white; box-shadow: 0 10px 35px #18334d26; color: #344f67; font-size: 12px; }
.dropdown-heading { display: flex; align-items: center; gap: 10px; padding: 12px 14px 8px; flex-shrink: 0; }
.dropdown-heading strong { font-size: 13px; }
.dropdown-heading > span { color: #7a8c9e; font-size: 10px; }
.close-picker { margin-left: auto; background: transparent; border: 0; min-height: 28px; padding: 3px 7px; color: #6e8195; font-size: 19px; }
.column-search { padding: 0 14px 10px; flex-shrink: 0; }
.column-search input { width: 100%; min-height: 34px; font-size: 12px; padding: 8px 10px; }
.group-list { padding: 0 6px 7px; overflow: auto; min-height: 0; }
.group-button { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; border: 0; padding: 11px 10px; background: white; color: #344f67; font-size: 12px; text-align: left; }
.group-button:hover, .group-button:focus-visible { background: #f0f6f4; }
.group-button span { margin: 0; font-size: 12px; }
.group-button small { margin-left: auto; color: #8192a4; font-weight: 400; }
.group-back { align-self: start; background: transparent; border: 0; color: #237461; font-size: 11px; min-height: 30px; padding: 5px 14px; }
.attribute-list { margin: 0; padding: 8px 14px 12px; border: 0; overflow: auto; min-height: 0; }
.attribute-list legend { padding: 3px 0; font-size: 11px; font-weight: 650; color: #38596e; }
.column-option { display: flex; align-items: center; gap: 10px; padding: 8px 2px; cursor: pointer; font-size: 12px; }
.column-option input { width: 16px; height: 16px; min-height: 0; padding: 0; margin: 0; accent-color: #176e5c; flex-shrink: 0; }
.column-option input:disabled { opacity: .5; }
.column-option small { display: block; font-size: 10px; color: #7a8c9e; margin-top: 3px; }
.column-actions { display: flex; gap: 8px; padding: 10px 14px; border-top: 1px solid #e8eef3; background: #f8fafc; flex-shrink: 0; }
.column-actions button { min-height: 32px; padding: 7px 10px; font-size: 11px; background: white; color: #38596e; }
.no-columns { padding: 8px 10px; color: #728198; font-size: 12px; }
</style>
