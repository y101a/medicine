import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import PrivateKnowledgeSelector from './PrivateKnowledgeSelector.vue'

const collections = [1, 2, 3, 4].map(index => ({
  id: `k${index}`,
  name: `知识库${index}`,
  description: null,
  status: 'active' as const,
  documentCount: index,
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-01T00:00:00Z',
}))

type SelectorProps = {
  modelValue: string[]
  collections: typeof collections
  loading?: boolean
  error?: string
}

/** 区块里的管理入口用 `router.push`，所以单测给一个真的 memory router，而不是 stub 组件。 */
function mountSelector(props: SelectorProps) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/app/private-knowledge', name: 'private-knowledge', component: { template: '<div />' } }],
  })
  const wrapper = mount(PrivateKnowledgeSelector, {
    props,
    global: { plugins: [router, ElementPlus] },
  })
  return { wrapper, router }
}

describe('咨询页私人知识区块（在「+」菜单内）', () => {
  it('默认收起并显示未选择，展开后说明只对本次发送生效', async () => {
    const { wrapper } = mountSelector({ modelValue: [], collections })
    expect(wrapper.text()).toContain('私人知识')
    expect(wrapper.text()).toContain('未选择')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    await wrapper.get('.private-knowledge-toggle').trigger('click')
    expect(wrapper.text()).toContain('只对本次发送的问题生效')
  })

  it('达到三个后禁用其余选项', async () => {
    const { wrapper } = mountSelector({ modelValue: ['k1', 'k2', 'k3'], collections })
    const boxes = wrapper.findAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(4)
    expect(boxes[3].attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('已选 3')
  })

  it('勾选通过受控事件上抛，组件自己不保存状态', async () => {
    const { wrapper } = mountSelector({ modelValue: [], collections })
    await wrapper.get('.private-knowledge-toggle').trigger('click')
    await wrapper.findAll('input[type="checkbox"]')[1].setValue(true)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([['k2']])
  })

  it('加载失败时显示受控原因并可重试，不再谎报成「还没有知识库」', async () => {
    const { wrapper } = mountSelector({
      modelValue: [], collections: [], error: '私人知识库暂时不可用，请稍后再试',
    })
    await wrapper.get('.private-knowledge-toggle').trigger('click')
    expect(wrapper.text()).toContain('知识库列表加载失败')
    expect(wrapper.text()).toContain('私人知识库暂时不可用，请稍后再试')
    expect(wrapper.text()).not.toContain('还没有知识库')

    await wrapper.get('.retry-collections').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('加载中显示加载态，不显示空态', async () => {
    const { wrapper } = mountSelector({ modelValue: [], collections: [], loading: true })
    await wrapper.get('.private-knowledge-toggle').trigger('click')
    expect(wrapper.text()).toContain('正在加载…')
    expect(wrapper.text()).not.toContain('还没有知识库')
  })

  it('真的没有知识库时给出可点的管理入口，而不只是一句死文案', async () => {
    const { wrapper, router } = mountSelector({ modelValue: [], collections: [] })
    await wrapper.get('.private-knowledge-toggle').trigger('click')
    expect(wrapper.text()).toContain('还没有知识库')

    await wrapper.get('.manage-link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('private-knowledge')
  })
})