<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

/**
 * 资讯门户的独立布局：**不挂在 `WorkspaceLayout` 下**，因此没有工作区侧栏，
 * 也不受 ADR-011（工作区 `min-width: 1000px`、窄屏只给提示）约束——这里是
 * 真正的响应式页面，375px 纵向排列。
 *
 * 刻意**不**在页头再放一个「与 AI 对话」入口：同一功能只保留一个入口
 * （`AGENTS.md` 的界面入口纪律），聊天入口是 AI 展示区那个按钮。
 */
const auth = useAuthStore()
const displayName = computed(() => auth.user?.realName || auth.user?.username || '用户')
</script>

<template>
  <div class="portal">
    <header class="portal-top">
      <div class="brand">
        <span class="mark" aria-hidden="true">✦</span>
        <span class="brand-text">
          <strong>病理诊断科普助手</strong>
          <small>健康资讯门户</small>
        </span>
      </div>
      <p class="who">{{ displayName }}</p>
    </header>
    <router-view />
    <footer class="portal-foot">
      <p>
        本门户只做健康资讯聚合与科普，不提供诊断、处方或治疗建议；资讯未经医学审核，
        请以原始来源为准。身体不适请及时就医，紧急情况请拨打 120。
      </p>
      <p class="foot-mark">病理诊断科普助手 · 开发原型</p>
    </footer>
  </div>
</template>

<style scoped>
.portal { display: flex; flex-direction: column; min-height: 100vh; background: #f5f8fb; color: #334d64; }
.portal-top { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 16px clamp(16px, 5vw, 48px); background: #fff; border-bottom: 1px solid #e6edf3; }
.brand { display: flex; align-items: center; gap: 11px; }
.mark { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 12px; background: #eaf4fc; color: #2a7fc3; font-size: 20px; }
.brand-text strong { display: block; color: #24445f; font-size: 15px; }
.brand-text small { display: block; margin-top: 2px; color: #90a0b0; font-size: 10px; letter-spacing: 1px; }
.who { margin: 0; color: #7d8fa0; font-size: 12px; }
.portal-foot { margin-top: auto; padding: 22px clamp(16px, 5vw, 48px) 28px; border-top: 1px solid #e6edf3; background: #fff; }
.portal-foot p { max-width: 860px; margin: 0 0 8px; color: #8c9ba9; font-size: 11px; line-height: 1.9; }
.foot-mark { color: #a9b6c1; }
</style>