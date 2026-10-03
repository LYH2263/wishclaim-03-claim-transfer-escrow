<template>
  <div class="wall">
    <h1 class="serif">{{ w.title }}</h1>
    <p>{{ w.note }}</p>
    <p class="tag">状态 {{ w.status }} · 认领人 {{ w.claimer || '—' }}</p>
    <p v-if="w.status==='claimed'" class="tag">
      到期 {{ w.expires_at }} · 剩余 {{ fmt(w.remaining_seconds) }}
    </p>
    <p v-if="err" class="err">{{ err }}</p>

    <input v-model="claimer" placeholder="你的名字" />
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button @click="claim">认领锁定</button>
      <button class="ghost" @click="release">释放</button>
      <button class="ghost" @click="fulfill">核销完成</button>
    </div>

    <template v-if="w.status==='claimed'">
      <hr />
      <h3 class="serif">转让托管</h3>

      <div v-if="!w.transfer">
        <input v-model="target" placeholder="目标认领人" />
        <button @click="preview">转让预览</button>
        <div v-if="pv" class="card" style="margin-top:8px">
          <p class="tag">转让：{{ pv.from_claimer }} → {{ pv.to_claimer }}</p>
          <p class="tag">当前 expires_at：{{ pv.expires_at }}</p>
          <p class="tag">确认后认领人变为 {{ pv.to_claimer }}，到期时间不变（继承剩余秒数，不重开满额）</p>
          <button @click="confirmTransfer">确认转让</button>
          <button class="ghost" @click="pv=null">取消预览</button>
        </div>
      </div>

      <div v-else class="card">
        <p class="tag transfer-tag">
          进行中转让单 #{{ w.transfer.id }}：{{ w.transfer.from_claimer }} → {{ w.transfer.to_claimer }}
        </p>
        <p class="tag">未确认前他人无法认领；到期时间钉 {{ w.expires_at }}</p>
        <button @click="confirmTransfer">确认转让</button>
        <button class="ghost" @click="cancelTransfer">撤销转让单</button>
      </div>
    </template>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
const props = defineProps({ id: String })
const w = ref({})
const claimer = ref('访客')
const target = ref('')
const pv = ref(null)
const err = ref('')
let timer = null

function fmt(sec) {
  if (sec === null || sec === undefined) return '—'
  const h = String(Math.floor(sec / 3600)).padStart(2, '0')
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return `${h}:${m}:${s}`
}
async function load() {
  w.value = await api('/wishes/' + props.id)
  if (!w.value.transfer) pv.value = null
}
async function claim() {
  err.value=''; try { await api('/wishes/'+props.id+'/claim',{method:'POST',body:JSON.stringify({claimer:claimer.value})}); await load() } catch(e){ err.value=e.message }
}
async function release() {
  err.value=''; try { await api('/wishes/'+props.id+'/release',{method:'POST',body:'{}'}); await load() } catch(e){ err.value=e.message }
}
async function fulfill() {
  err.value=''; try { await api('/wishes/'+props.id+'/fulfill',{method:'POST',body:'{}'}); await load() } catch(e){ err.value=e.message }
}
async function preview() {
  err.value=''
  try {
    const out = await api('/wishes/'+props.id+'/transfers',
      {method:'POST',body:JSON.stringify({target:target.value})})
    pv.value = out.preview
    await load()  // projection now carries the pending order
  } catch(e){ err.value=e.message }
}
async function confirmTransfer() {
  err.value=''
  const orderId = w.value.transfer?.id
  if (!orderId) { err.value='no_pending_order'; return }
  try {
    await api('/transfers/'+orderId+'/confirm',{method:'POST',body:'{}'})
    pv.value=null; target.value=''
    await load()
  } catch(e){ err.value=e.message }
}
async function cancelTransfer() {
  err.value=''
  const orderId = w.value.transfer?.id
  if (!orderId) return
  try { await api('/transfers/'+orderId+'/cancel',{method:'POST',body:'{}'}); await load() }
  catch(e){ err.value=e.message }
}
function tick() {
  const x = w.value
  if (x && x.remaining_seconds !== null && x.remaining_seconds !== undefined && x.remaining_seconds > 0) x.remaining_seconds--
}
onMounted(async () => { await load(); timer = setInterval(tick, 1000) })
onUnmounted(() => clearInterval(timer))
</script>
