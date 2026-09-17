import vue from '@vitejs/plugin-vue'
import { configDefaults, defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    // e2e/ 是 Playwright 的浏览器验收，不能被 Vitest 当单测收集
    // （否则 npx vitest run 会去跑 Playwright 的 test()，整个基线失败）。
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
