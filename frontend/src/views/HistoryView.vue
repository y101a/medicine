<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useConsultationsStore } from '../stores/consultations'
import { consultationsApi } from '../api/consultations'
import { getApiErrorMessage } from '../api/http'
import type { Consultation } from '../types/consultations'

const store = useConsultationsStore()
const deleting = ref('')
onMounted(() => store.load())
async function remove(item: Consultation) {
  if (deleting.value) return
  try {
    await ElMessageBox.confirm('删除后，该咨询和其中的消息无法恢复。确定删除吗？', '删除咨询', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  deleting.value = item.id
  try {
    await consultationsApi.remove(item.id)
    ElMessage.success('咨询及消息已删除')
    await store.load()
  } catch (e) { ElMessage.error(getApiErrorMessage(e)) }
  finally { deleting.value = '' }
}
</script>
<template>
  <main class="history-page">
    <h1>咨询历史</h1><p>回顾已保存的消息，继续记录您的健康问题。</p>
    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" />
    <el-button v-if="store.error" @click="store.load()">重新加载</el-button>
    <p v-if="store.loading" role="status">正在加载…</p>
    <section v-if="!store.loading && !store.error && !store.items.length" class="history-empty">
      <h2>还没有咨询记录</h2><p>发送第一条消息即可保存一次咨询。</p>
      <router-link to="/app">开始新咨询 →</router-link>
    </section>
    <article v-for="item in store.items" :key="item.id" class="history-item">
      <router-link :to="`/app/consultations/${item.id}`">
        <strong>{{ item.title }}</strong>
        <span>{{ item.messageCount }} 条消息 · {{ new Date(item.updatedAt).toLocaleString('zh-CN') }}</span>
      </router-link>
      <el-button type="danger" plain :loading="deleting === item.id" :disabled="!!deleting"
        @click="remove(item)">删除</el-button>
    </article>
    <el-button v-if="store.hasMore" :loading="store.loading" @click="store.load(true)">加载更多</el-button>
  </main>
</template>
<style scoped>
.history-page { max-width: 980px; margin: auto; padding: 40px; }
h1 { font-size: 25px; font-weight: 600; } p { color: #8a99a8; font-size: 14px; }
.history-empty { text-align: center; padding: 90px 24px; margin-top: 40px; border: 1px dashed #dce5ee; border-radius: 18px; }
h2 { color: #4b6277; font-size: 18px; font-weight: 500; }
a { color: #237ac2; font-size: 14px; text-decoration: none; }
.history-item { display: flex; align-items: center; gap: 24px; border-bottom: 1px solid #e5edf4; padding: 24px 0; }
.history-item a { flex: 1; min-width: 0; }
.history-item strong { display: block; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
.history-item span { display: block; margin-top: 10px; color: #8a99a8; font-size: 12px; }
</style>
