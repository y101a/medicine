import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PrivateKnowledgeReferences from './PrivateKnowledgeReferences.vue'

describe('私人知识引用', () => {
  it('与公共来源分组显示且不生成外部链接', () => {
    const wrapper = mount(PrivateKnowledgeReferences, { props: { citations: [{
      referenceNumber: 1,
      documentId: 'd1',
      collectionName: '我的检验单',
      documentName: '血常规.txt',
      locator: '第 2 段',
      similarity: 0.8,
      status: 'available' as const,
    }] } })
    expect(wrapper.text()).toContain('你的资料（1）')
    expect(wrapper.text()).toContain('[P1]')
    expect(wrapper.text()).toContain('我的检验单')
    expect(wrapper.text()).toContain('未核验资料')
    expect(wrapper.find('a').exists()).toBe(false)
  })

  it('删除后只显示墓碑，不保留文档定位', () => {
    const wrapper = mount(PrivateKnowledgeReferences, { props: { citations: [{
      referenceNumber: 2,
      documentId: null,
      collectionName: null,
      documentName: '私人资料已删除',
      locator: null,
      similarity: 0.7,
      status: 'deleted' as const,
    }] } })
    expect(wrapper.text()).toContain('[P2]')
    expect(wrapper.text()).toContain('私人资料已删除')
    expect(wrapper.text()).not.toContain('第 2 段')
  })
})
