<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const preview = ref(null)
const scans = ref([])
const msg = ref('')
const err = ref('')

const STATE_TEXT = { none: '未扫描', valid: '有效', expired: '已过期', stale: '有新发放' }
const gate = computed(() => preview.value?.seal_gate || { allowed: false, reason: '' })
const scanInfo = computed(() => preview.value?.expire_scan || { state: 'none', scan: null })

async function load() {
  err.value = ''
  try {
    preview.value = await api.preview()
    scans.value = await api.scans(preview.value.business_day)
  } catch (e) { err.value = e.message }
}
async function scan() {
  msg.value = ''; err.value = ''
  try {
    const r = await api.scanExpire({})
    msg.value = `扫描批次 #${r.scan_id} · 发放 ${r.issued_count} · 作废未核 ${r.voided_count} 笔`
    await load()
  } catch (e) { err.value = e.message }
}
async function seal() {
  msg.value = ''; err.value = ''
  try {
    const r = await api.seal({ expire_scan_id: scanInfo.value.scan?.id })
    msg.value = `已钉扎批次 #${r.batch_id} · ${r.fact_count} 笔 · 合计 ${r.total_amount} · 绑定扫描 #${r.expire_scan_id}`
    await load()
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel" v-if="preview">
    <div class="grid">
      <div class="stat"><div class="k">业务日</div><div class="v">{{ preview.business_day }}</div></div>
      <div class="stat"><div class="k">待钉笔数</div><div class="v ticket">{{ preview.open_count }}</div></div>
      <div class="stat"><div class="k">待钉合计</div><div class="v ticket">{{ preview.open_total }}</div></div>
      <div class="stat"><div class="k">已钉扎</div><div class="v">{{ preview.already_sealed ? '是' : '否' }}</div></div>
      <div class="stat">
        <div class="k">过期扫描</div>
        <div class="v"><span class="tag" :class="scanInfo.state === 'valid' ? 'ok' : 'warn'">{{ STATE_TEXT[scanInfo.state] || scanInfo.state }}</span></div>
      </div>
      <div class="stat"><div class="k">最近作废</div><div class="v">{{ scanInfo.scan ? scanInfo.scan.voided_count : '—' }}</div></div>
    </div>
    <p class="msg" v-if="scanInfo.scan">
      扫描 #{{ scanInfo.scan.id }} · {{ scanInfo.scan.scanned_at }} · 发放 {{ scanInfo.scan.issued_count }} · 作废 {{ scanInfo.scan.voided_count }} · TTL {{ scanInfo.ttl_seconds }}s
    </p>
    <p class="msg" v-if="(preview.scan_voided_coupons || []).length">
      本扫描作废券码：{{ preview.scan_voided_coupons.join(', ') }}
    </p>
    <div class="row">
      <button type="button" class="ghost" @click="scan" :disabled="preview.already_sealed">执行过期扫描</button>
      <button type="button" @click="seal" :disabled="!gate.allowed">钉扎本日核销</button>
      <button type="button" class="ghost" @click="load">刷新预览</button>
    </div>
    <p class="msg err" v-if="!gate.allowed && gate.reason">钉闸未开：{{ gate.reason }}</p>
    <p class="msg err" v-if="(preview.scan_void_torn || []).length">
      扫描清单已宣告作废但事实未落 void：{{ preview.scan_void_torn.join(', ') }}，请重新扫描后再钉。
    </p>
    <p class="msg" v-if="msg">{{ msg }}</p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
  <div class="panel">
    <table>
      <thead><tr><th>事实ID</th><th>券码</th><th>活动</th><th>金额</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="f in (preview?.facts || [])" :key="f.id">
          <td>{{ f.id }}</td>
          <td>{{ f.coupon_code }}</td>
          <td>{{ f.campaign_code }}</td>
          <td>{{ f.amount }}</td>
          <td><span class="tag warn">{{ f.status }}</span></td>
        </tr>
      </tbody>
    </table>
  </div>
  <div class="panel">
    <h3>扫描批次（{{ preview?.business_day }}）</h3>
    <table>
      <thead><tr><th>批次</th><th>扫描时刻</th><th>发放数</th><th>作废数</th><th>事实已 void</th><th>覆盖至事件</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="s in scans" :key="s.id">
          <td>{{ s.id }}</td>
          <td>{{ s.scanned_at }}</td>
          <td>{{ s.issued_count }}</td>
          <td>{{ s.voided_count }}</td>
          <td>
            <span class="tag" :class="s.void_consistent ? 'ok' : 'warn'">
              {{ s.voided_count_effective }}
            </span>
          </td>
          <td>{{ s.covered_event_id }}</td>
          <td><span class="tag" :class="s.state === 'valid' ? 'ok' : 'warn'">{{ STATE_TEXT[s.state] || s.state }}</span></td>
        </tr>
        <tr v-if="!scans.length"><td colspan="7">尚无扫描批次</td></tr>
      </tbody>
    </table>
  </div>
</template>
