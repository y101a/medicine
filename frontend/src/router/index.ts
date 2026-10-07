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
      // 登录后的健康资讯门户：**独立布局**，不挂在 WorkspaceLayout 下，因此没有工作区侧栏，
      // 也不受 ADR-011（工作区 min-width:1000px）约束。规格见 backend/docs/NEWS_PORTAL_IMPLEMENTATION.md。
      path: '/portal',
      component: () => import('../layouts/PortalLayout.vue'),
      meta: { requiresAuth: true },
      children: [{ path: '', name: 'portal', component: () => import('../views/PortalView.vue') }],
    },
    {
      // 知识图谱探索页：**独立路由页**（产品决策 2026-10-07：路径就是 `/knowledge-graph`，
      // 入口在主导航；**不得**放进聊天输入框）。刻意不挂在 `WorkspaceLayout` 下——
      // 工作区带 ADR-011 的 `min-width: 1000px` 桌面优先约束，375px 必然横向溢出，
      // 而本页要求 1280px 与 375px 都不溢出；与 `/portal` 同一取舍，页面内提供「返回工作区」。
      path: '/knowledge-graph',
      name: 'knowledge-graph',
      component: () => import('../views/KnowledgeGraphView.vue'),
      meta: { requiresAuth: true },
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
        // 私人资料独立页面（方案 §8.1）：与公共医学知识搜索分开，不放进附件流程。
        {
          path: 'private-knowledge',
          name: 'private-knowledge',
          component: () => import('../views/PrivateKnowledgeView.vue'),
        },
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
    return { name: 'portal' }
  }

  return true
})

export default router
