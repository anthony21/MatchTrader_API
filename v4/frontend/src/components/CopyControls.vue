<script setup>
import { computed, ref, watch } from 'vue'
import { request } from '../api.js'
// Copy controls arrive on the stream. When the section is absent the safe reading is
// shown (paper, every source off) and the controls stay disabled; nothing is fetched.
const SOURCES = ['P01', 'X17', 'MANUAL']
const SAFE = Object.freeze({ mode: 'paper', sources: Object.freeze({ P01: false, X17: false, MANUAL: false }) })
const props = defineProps({ pushed: Object })
const current = ref(SAFE), busy = ref(false), error = ref('')
const reported = computed(() => !!props.pushed)
const live = computed(() => current.value.mode === 'live')
const normalise = value => ({ mode: value?.mode === 'live' ? 'live' : 'paper',
  sources: Object.fromEntries(SOURCES.map(code => [code, value?.sources?.[code] === true])) })
watch(() => props.pushed, value => { current.value = value ? normalise(value) : SAFE }, { immediate: true })
async function post(next) {
  busy.value = true; error.value = ''
  try {
    const result = await request('copy-controls', next)
    if (result && typeof result.mode === 'string') current.value = normalise(result)
  } catch (err) { error.value = err?.message || 'Copy controls could not be saved and the local API returned no message.' }
  finally { busy.value = false }
}
function toggleMode() {
  return post({ mode: live.value ? 'paper' : 'live', sources: { ...current.value.sources } })
}
</script>

<template>
  <section class="card copy-controls-panel" :class="{ live }" aria-label="Copy controls">
    <div class="section-heading"><h2>Broker orders</h2></div>
    <div class="controls-row">

      <span class="control-divider"></span>
      <button type="button" class="master" :class="{ live }" role="switch" aria-label="Live or Paper" :aria-checked="live" :disabled="busy || !reported" @click="toggleMode">{{ live ? 'Live' : 'Paper' }}</button>
    </div>
    <p v-if="error" role="alert" class="error-banner">{{ error }}</p>
  </section>
</template>

<style scoped>
.copy-controls-panel{margin-top:24px;padding-bottom:20px;border-width:2px}
.copy-controls-panel.live{border-color:#9b2226;background:#fff5f5}
.mode-banner{font-size:13px;padding:9px 14px;border-radius:30px;background:#e9f4ef;color:#27644e;border:1px solid #c9e4d7;white-space:nowrap}
.live .mode-banner{background:#9b2226;color:#fff;border-color:#9b2226;letter-spacing:.5px}
.controls-row{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:0 24px}
.source-switch{display:flex;align-items:center;gap:8px;font-weight:600;font-size:13px}
.source-switch input{min-height:auto;width:18px;height:18px}
.source-switch .subtext{margin:0;display:inline}
.master{background:#fff;color:#34465e}
.master.armed{background:#fff3de;border-color:#c98a1d;color:#7a4f00}
.master.live{background:#9b2226;border-color:#9b2226;color:#fff}
@media(max-width:720px){.controls-row{padding:0 17px}.control-divider{display:none}}
</style>
