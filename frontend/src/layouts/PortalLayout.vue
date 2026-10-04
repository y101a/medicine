<script setup lang="ts">
/**
 * 资讯门户的独立布局：**不挂在 `WorkspaceLayout` 下**，因此没有工作区侧栏，
 * 也不受 ADR-011（工作区 `min-width: 1000px`、窄屏只给提示）约束——这里是
 * 真正的响应式页面，375px 纵向排列。
 *
 * 2026-10-04 用户要求：删掉页面顶部那条品牌栏（原来显示「病理诊断科普助手 /
 * 健康资讯门户」与用户名），让下面的分区铺满整页。所以这里只保留内容区与页脚。
 *
 * 刻意**不**在页面上再放一个「与 AI 对话」入口：同一功能只保留一个入口
 * （`AGENTS.md` 的界面入口纪律），聊天入口是内容区顶部那个按钮。
 */
</script>

<template>
  <div class="portal">
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
.portal-foot { margin-top: auto; padding: 18px clamp(16px, 3vw, 40px) 24px; border-top: 1px solid #e6edf3; background: #fff; }
.portal-foot p { max-width: 1000px; margin: 0 0 6px; color: #8c9ba9; font-size: 11px; line-height: 1.9; }
.foot-mark { color: #a9b6c1; }
</style>