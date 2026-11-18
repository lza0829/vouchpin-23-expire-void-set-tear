<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const d = ref(null)
const err = ref('')
const STATE_TEXT = { none: '未扫描', valid: '有效', expired: '已过期', stale: '有新发放' }
const scanState = computed(() => d.value?.expire_scan?.state || 'none')
const scan = computed(() => d.value?.expire_scan?.scan || null)
async function load() {
  err.value = ''
  try { d.value = await api.dashboard() } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
<template>
  <div class="panel">
    <div class="grid" v-if="d">
      <div class="stat"><div class="k">业务日</div><div class="v">{{ d.business_day }}</div></div>
      <div class="stat"><div class="k">今日事件</div><div class="v">{{ d.event_count }}</div></div>
      <div class="stat"><div class="k">核销事实</div><div class="v ticket">{{ d.fact_count }}</div></div>
      <div class="stat"><div class="k">待钉 open</div><div class="v">{{ d.open_fact_count }}</div></div>
      <div class="stat"><div class="k">今日核销额</div><div class="v ticket">{{ d.redeem_total_today }}</div></div>
      <div class="stat"><div class="k">日已钉扎</div><div class="v">{{ d.day_sealed ? '是' : '否' }}</div></div>
      <div class="stat"><div class="k">过期计数</div><div class="v">{{ d.expire_count }}</div></div>
      <div class="stat">
        <div class="k">过期扫描</div>
        <div class="v"><span class="tag" :class="scanState === 'valid' ? 'ok' : 'warn'">{{ STATE_TEXT[scanState] || scanState }}</span></div>
      </div>
      <div class="stat"><div class="k">扫描作废</div><div class="v">{{ scan ? scan.voided_count : '—' }}</div></div>
    </div>
    <p class="msg" v-if="!err && scan">最近扫描 #{{ scan.id }} · {{ scan.scanned_at }} · 发放 {{ scan.issued_count }} · 作废 {{ scan.voided_count }}</p>
    <p class="msg" v-if="!err">票根洋红标出核销侧数字；钉前必须过期扫描，钉扎后禁止再写入该日发放与核销。</p>
    <p class="msg err" v-if="err">{{ err }}</p>
  </div>
</template>
