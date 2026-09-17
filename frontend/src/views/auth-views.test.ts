import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import LoginView from './LoginView.vue'
import RegisterView from './RegisterView.vue'

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginView },
      { path: '/register', component: RegisterView },
      { path: '/app', component: { template: '<div>home</div>' } },
    ],
  })
}

describe('auth views', () => {
  it('登录页展示必要的认证入口', async () => {
    const router = createTestRouter()
    await router.push('/login')
    const wrapper = mount(LoginView, {
      global: { plugins: [createPinia(), router, ElementPlus] },
    })

    expect(wrapper.text()).toContain('病理诊断科普助手')
    expect(wrapper.text()).toContain('用户名')
    expect(wrapper.text()).toContain('密码')
    expect(wrapper.text()).toContain('注册账号')
  })

  it('注册页展示全部已确认字段', async () => {
    const router = createTestRouter()
    await router.push('/register')
    const wrapper = mount(RegisterView, {
      global: { plugins: [createPinia(), router, ElementPlus] },
    })

    for (const label of ['用户名', '姓名', '手机号', '性别', '身份证号码', '确认密码']) {
      expect(wrapper.text()).toContain(label)
    }
  })
})
