import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { setUnauthorizedHandler } from './api/http'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia).use(router).use(ElementPlus)

const authStore = useAuthStore(pinia)
setUnauthorizedHandler(() => {
  authStore.clearSession()
  // 只有「本来就需要登录」的页面才谈得上登录状态失效。
  // 未登录访客直接打开 /register（刷新、书签、外链）同样会收到 401，
  // 那不是过期；若在这里弹回登录页，注册页将永远无法直接访问。
  if (!router.currentRoute.value.meta.requiresAuth) return
  router.replace({ name: 'login', query: { reason: 'expired' } })
})

app.mount('#app')
