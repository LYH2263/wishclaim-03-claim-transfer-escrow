<template>
  <div class="wall">
    <h1 class="serif">愿望墙</h1>
    <p class="tag">无顶栏 · 瀑布流 · 点卡片认领</p>
    <div class="masonry">
      <article v-for="w in rows" :key="w.id" class="card" @click="$router.push('/wishes/'+w.id)">
        <h3>{{ w.title || '（无标题）' }}</h3>
        <p>{{ w.note }}</p>
        <span class="tag">{{ w.status }} · {{ w.data_quality }}</span>
        <p v-if="w.status==='claimed'" class="tag">
          认领人 {{ w.claimer }} · 剩余 {{ fmt(w.remaining_seconds) }}
        </p>
        <p v-if="w.transfer" class="tag transfer-tag">
          转让中：{{ w.transfer.from_claimer }} → {{ w.transfer.to_claimer }}
        </p>
      </article>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
const rows = ref([])
let timer = null
function fmt(sec) {
  if (sec === null || sec === undefined) return '—'
  const h = String(Math.floor(sec / 3600)).padStart(2, '0')
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return `${h}:${m}:${s}`
}
function tick() {
  // Count down locally against the pinned expires_at; refresh when a lock laps.
  let lapsed = false
  for (const w of rows.value) {
    if (w.remaining_seconds !== null && w.remaining_seconds > 0) w.remaining_seconds--
    else if (w.status === 'claimed') lapsed = true
  }
  if (lapsed) load()
}
async function load() { rows.value = await api('/wishes') }
onMounted(async () => { await load(); timer = setInterval(tick, 1000) })
onUnmounted(() => clearInterval(timer))
</script>
