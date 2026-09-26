import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { guestOnly: true },
    },
    {
      // 短信找回密码：只在登录页给入口，不占侧边栏（方案第 11 节）。
      path: '/forgot-password',
      name: 'forgot-password',
      component: () => import('../views/ForgotPasswordView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/app',
      component: () => import('../layouts/WorkspaceLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', name: 'home', component: () => import('../views/DashboardView.vue') },
        { path: 'chat', name: 'chat', component: () => import('../views/HomeView.vue') },
        { path: 'consultations/:id', name: 'consultation', component: () => import('../views/HomeView.vue') },
        { path: 'history', name: 'history', component: () => import('../views/HistoryView.vue') },
        { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
        // 旧路径保留为重定向：账户信息与健康记录已并入设置页分栏，任何旧链接仍然可用。
        { path: 'profile', redirect: { name: 'settings', query: { tab: 'account' } } },
        { path: 'health-records', redirect: { name: 'settings', query: { tab: 'health' } } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/login' },
  ],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  await authStore.initialize()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.meta.guestOnly && authStore.isAuthenticated) {
    return { name: 'home' }
  }

  return true
})

export default router
