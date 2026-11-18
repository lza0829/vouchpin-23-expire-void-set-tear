<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
const day = ref('')
const ttl = ref('')
const msg = ref('')
const err = ref('')
async function load() {
  err.value = ''
  try {
    const r = await api.getDay()
    day.value = r.business_day
    const t = await api.getScanTtl()
    ttl.value = t.ttl_seconds
  } catch (e) { err.value = e.message }
}
async function save() {
  msg.value = ''; err.value = ''
  try {
    const r = await api.setDay(day.value)
    msg.value = `业务日已设为 ${r.business_day}`
  } catch (e) { err.value = e.message }
}
async function saveTtl() {
  msg.value = ''; err.value = ''
  try {
    const r = await api.setScanTtl(Number(ttl.value))
    msg.value = `扫描有效期已设为 ${r.ttl_seconds} 秒`
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel">
    <div class="row">
      <label>业务日 <input v-model="day" placeholder="YYYY-MM-DD" /></label>
      <button type="button" @click="save">保存</button>
    </div>
    <div class="row">
      <label>扫描有效期（秒） <input v-model="ttl" type="number" min="1" placeholder="3600" /></label>
      <button type="button" @click="saveTtl">保存</button>
    </div>
    <p class="msg">钉前必须过期扫描：钉扎请求须携带有效期内的 scan_id，超期或扫描后有新发放均需重扫。</p>
    <p class="msg" v-if="msg">{{ msg }}</p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
</template>
