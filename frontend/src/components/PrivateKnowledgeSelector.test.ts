import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
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

describe('咨询私人知识选择器', () => {
  it('默认未选择并明确提示只对本次发送生效', () => {
    const wrapper = mount(PrivateKnowledgeSelector, {
      props: { modelValue: [], collections },
      global: { stubs: { ElPopover: { template: '<div><slot name="reference"/><slot/></div>' } } },
    })
    expect(wrapper.text()).toContain('私人知识')
    expect(wrapper.text()).toContain('只对本次发送的问题生效')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('达到三个后禁用其余选项', () => {
    const wrapper = mount(PrivateKnowledgeSelector, {
      props: { modelValue: ['k1', 'k2', 'k3'], collections },
      global: { stubs: { ElPopover: { template: '<div><slot name="reference"/><slot/></div>' } } },
    })
    const boxes = wrapper.findAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(4)
    expect(boxes[3].attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('已选 3')
  })
})
