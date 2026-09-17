import { existsSync } from 'node:fs'
import { defineConfig } from '@playwright/test'

const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'

/**
 * 用**本机已装的浏览器**，不下载 Playwright 自带 Chromium（约 150MB）。
 * 目的不是省流量，而是：DSH 看不到界面，验收必须产出**可读的文字**，
 * 所以这套断言的关键在于能打印出元素、坐标和尺寸，而不是截图。
 */
const BROWSER_CANDIDATES = [
  process.env.E2E_BROWSER_PATH,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
]

function resolveBrowserPath(): string {
  const found = BROWSER_CANDIDATES.find(path => path && existsSync(path))
  if (!found) {
    throw new Error(
      '没有找到本机浏览器。请设置环境变量 E2E_BROWSER_PATH 指向 Chrome/Edge，'
      + '或执行 npx playwright install chromium（本项目默认不下载 Chromium）。',
    )
  }
  return found
}

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: true,
  // 只输出文本清单：这套验收的主要读者是看不到界面的 AI。
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    launchOptions: { executablePath: resolveBrowserPath() },
    // 截图和 trace 是给**人**看的；AI 读的是断言消息里的数字。
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    locale: 'zh-CN',
  },
  // 只起前端：接口一律用 page.route 拦截，因此不依赖后端与数据库。
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
})