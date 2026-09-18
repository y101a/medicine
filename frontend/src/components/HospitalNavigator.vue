<script setup lang="ts">
import { computed, ref } from 'vue'
import { Guide, LocationFilled, WarningFilled } from '@element-plus/icons-vue'
import { getApiErrorMessage } from '../api/http'
import {
  navigationApi,
  type HospitalNavigationItem,
} from '../api/navigation'

const visible = ref(false)
const loading = ref(false)
const fallback = ref(false)
const city = ref('')
const items = ref<HospitalNavigationItem[]>([])
const notice = ref('')
const error = ref('')

const hasResults = computed(() => items.value.length > 0)

function open() {
  visible.value = true
  error.value = ''
}

function useAreaFallback(message: string) {
  fallback.value = true
  items.value = []
  notice.value = message
  error.value = ''
  loading.value = false
}

async function loadNearby(latitude: number, longitude: number) {
  try {
    const result = await navigationApi.nearby(latitude, longitude)
    items.value = result.items
    notice.value = result.notice
    if (!result.items.length) error.value = '附近暂未找到可规划路线的医院，请改用城市或区县查询。'
  } catch (caught) {
    useAreaFallback(`${getApiErrorMessage(caught)}，已切换为城市或区县查询。`)
  } finally {
    loading.value = false
  }
}

function locationFailureMessage(positionError: GeolocationPositionError) {
  if (positionError.code === 1) {
    return '定位权限被拒绝。请在浏览器地址栏的网站权限中允许定位，或使用城市、区县查询。'
  }
  if (positionError.code === 2) {
    return '设备暂时无法提供位置。请检查 Windows 定位服务或网络后重试。'
  }
  if (positionError.code === 3) {
    return '获取位置超时。请检查设备定位服务或直接使用城市、区县查询。'
  }
  return '未能取得当前位置，已切换为城市或区县查询。'
}

function locate() {
  items.value = []
  error.value = ''
  notice.value = ''
  fallback.value = false
  if (window.isSecureContext === false) {
    useAreaFallback('浏览器只允许 HTTPS 或 localhost 页面使用定位，当前页面已切换为城市或区县查询。')
    return
  }
  if (!navigator.geolocation) {
    useAreaFallback('当前浏览器不支持定位，已切换为城市或区县查询。')
    return
  }
  loading.value = true
  navigator.geolocation.getCurrentPosition(
    position => void loadNearby(position.coords.latitude, position.coords.longitude),
    positionError => useAreaFallback(locationFailureMessage(positionError)),
    { enableHighAccuracy: false, timeout: 15_000, maximumAge: 300_000 },
  )
}

async function searchArea() {
  const value = city.value.trim()
  if (!value || loading.value) return
  loading.value = true
  error.value = ''
  items.value = []
  try {
    const result = await navigationApi.byArea(value)
    items.value = result.items
    notice.value = result.notice
    if (!result.items.length) error.value = '该城市或区县暂未找到医院，请检查名称或行政区编码。'
  } catch (caught) {
    error.value = getApiErrorMessage(caught)
  } finally {
    loading.value = false
  }
}

function formatDistance(meters?: number | null) {
  if (meters == null) return ''
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} 公里` : `${meters} 米`
}

function formatDuration(seconds?: number | null) {
  if (seconds == null) return ''
  const minutes = Math.max(1, Math.round(seconds / 60))
  return minutes >= 60
    ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`
    : `${minutes} 分钟`
}
</script>

<template>
  <div class="hospital-navigator">
    <button class="navigator-trigger" type="button" @click="open">
      <el-icon><LocationFilled /></el-icon>
      <span><strong>附近医院导航</strong><small>定位仅用于本次查询，不保存</small></span>
    </button>

    <el-dialog v-model="visible" title="附近医院导航" width="min(680px, 92vw)" destroy-on-close>
      <el-alert
        title="如有胸痛、严重呼吸困难、疑似卒中等危急表现，请立即拨打 120，不要自行驾车。"
        type="error"
        :closable="false"
        show-icon
      />

      <section v-if="!fallback && !hasResults" class="location-consent">
        <el-icon :size="30"><Guide /></el-icon>
        <h3>查找路线时间更短的附近医院</h3>
        <p>点击后浏览器会申请一次定位权限。坐标仅在本次请求内存中使用，会发送给高德进行周边搜索和路线规划，但不会保存到数据库或写入日志。</p>
        <div class="consent-actions">
          <el-button class="locate-button" type="primary" :loading="loading" @click="locate">
            同意并查找附近医院
          </el-button>
          <el-button :disabled="loading" @click="useAreaFallback('已切换为城市或区县查询，无法判断哪家医院最近。')">
            不使用定位
          </el-button>
        </div>
      </section>

      <section v-if="fallback" class="area-fallback">
        <div class="fallback-title">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ notice }}</span>
        </div>
        <form @submit.prevent="searchArea">
          <el-input
            v-model="city"
            maxlength="12"
            aria-label="城市或行政区编码"
            placeholder="输入城市、区县或 6 位行政区编码"
          />
          <el-button type="primary" native-type="submit" :loading="loading" :disabled="!city.trim()">
            查询医院
          </el-button>
        </form>
      </section>

      <el-alert v-if="error" class="navigation-error" :title="error" type="warning" :closable="false" show-icon />

      <section v-if="hasResults" class="hospital-results" aria-live="polite">
        <p class="result-notice">{{ notice }}</p>
        <article v-for="(hospital, index) in items" :key="hospital.poiId || hospital.name" class="hospital-card">
          <div class="hospital-rank">{{ index + 1 }}</div>
          <div class="hospital-info">
            <strong>{{ hospital.name }}</strong>
            <span>{{ [hospital.district, hospital.address].filter(Boolean).join(' · ') || '地址以高德地图为准' }}</span>
            <small v-if="hospital.routeDurationSeconds != null">
              预计 {{ formatDuration(hospital.routeDurationSeconds) }} · {{ formatDistance(hospital.routeDistanceMeters) }}
            </small>
            <small v-else-if="hospital.routeMode">路线暂不可用，当前距离为直线距离参考</small>
            <small v-else>区域查询结果，未计算当前位置和路线时间</small>
          </div>
          <a
            :href="hospital.navigationUrl"
            target="_blank"
            rel="noopener noreferrer"
            referrerpolicy="no-referrer"
          >打开高德导航</a>
        </article>
        <el-button v-if="!fallback" plain @click="useAreaFallback('已切换为城市或区县查询，无法判断哪家医院最近。')">
          改用城市或区县查询
        </el-button>
      </section>
    </el-dialog>
  </div>
</template>

<style scoped>
.navigator-trigger { width: auto; display: flex; align-items: center; gap: 8px; margin: 0; padding: 7px 10px; border: 1px solid #dce9f3; border-radius: 10px; background: #f7fbff; color: #3478ad; cursor: pointer; text-align: left; }
.navigator-trigger:hover { border-color: #9fc6e4; background: #f0f8fe; }
.navigator-trigger > span { display: flex; flex-direction: column; gap: 2px; }
.navigator-trigger strong { font-size: 13px; font-weight: 600; }
.navigator-trigger small { display: block; color: #7e94a7; font-size: 10px; }
.location-consent { padding: 28px 12px 12px; text-align: center; color: #4e677d; }
.location-consent > .el-icon { color: #377fb7; }
.location-consent h3 { margin: 12px 0 8px; color: #314e67; }
.location-consent p { max-width: 540px; margin: 0 auto 18px; color: #748799; font-size: 13px; line-height: 1.8; }
.consent-actions { display: flex; justify-content: space-between; align-items: center; gap: 24px; max-width: 540px; margin: 22px auto 0; }
.consent-actions .el-button { margin: 0; }
.area-fallback { margin-top: 18px; }
.fallback-title { display: flex; align-items: flex-start; gap: 8px; color: #8a6c2c; font-size: 13px; line-height: 1.6; }
.area-fallback form { display: flex; gap: 10px; margin-top: 12px; }
.navigation-error { margin-top: 16px; }
.hospital-results { margin-top: 18px; }
.result-notice { color: #718396; font-size: 12px; line-height: 1.6; }
.hospital-card { display: grid; grid-template-columns: 28px 1fr auto; gap: 12px; align-items: center; padding: 14px 0; border-top: 1px solid #edf1f4; }
.hospital-rank { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: #eaf4fb; color: #397dad; font-size: 12px; }
.hospital-info { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.hospital-info strong { color: #324e66; font-size: 14px; }
.hospital-info span, .hospital-info small { color: #80909f; font-size: 11px; overflow-wrap: anywhere; }
.hospital-card a { padding: 7px 10px; border: 1px solid #78abd2; border-radius: 8px; color: #2f79b2; font-size: 12px; text-decoration: none; white-space: nowrap; }
@media (max-width: 620px) {
  .hospital-card { grid-template-columns: 28px 1fr; }
  .hospital-card a { grid-column: 2; width: fit-content; }
  .area-fallback form { flex-direction: column; }
  .consent-actions { align-items: stretch; flex-direction: column; gap: 10px; }
}
</style>
