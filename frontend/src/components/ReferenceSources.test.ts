import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReferenceSources from './ReferenceSources.vue'
import type { MessageCitation } from '../types/consultations'

const citation: MessageCitation = {
  sourceKey: 'web_search_prototype',
  organization: '国家卫生健康委员会',
  title: '甲状腺结节科普',
  canonicalUrl: 'https://www.nhc.gov.cn/example',
  similarity: 0,
  trustLevel: 'prototype',
}

describe('联网参考来源', () => {
  it('标明未审核并只允许官方域名的原型摘要链接', () => {
    const wrapper = mount(ReferenceSources, { props: { citations: [citation] } })
    expect(wrapper.text()).toContain('历史检索资料（引用未核验）')
    expect(wrapper.text()).toContain('请勿视为回答依据')
    expect(wrapper.text()).toContain('联网原型')
    expect(wrapper.text()).toContain('未核对原文')
    expect(wrapper.find('a').attributes('href')).toBe('https://www.nhc.gov.cn/example')

    const fake = mount(ReferenceSources, {
      props: { citations: [{ ...citation, canonicalUrl: 'https://nhc.gov.cn.evil.test/' }] },
    })
    expect(fake.find('a').exists()).toBe(false)
  })

  it('保留手写开发原型无效链接不可点击的约束', () => {
    const wrapper = mount(ReferenceSources, {
      props: { citations: [{
        ...citation, sourceKey: 'developer_prototype_knowledge',
        canonicalUrl: 'https://prototype.invalid/medical-knowledge/test',
      }] },
    })
    expect(wrapper.find('a').exists()).toBe(false)
  })

  it('仅显示原始资料编号，避免来源列表过滤后编号错位', () => {
    const wrapper = mount(ReferenceSources, {
      props: { citations: [{ ...citation, referenceNumber: 3 }] },
    })
    expect(wrapper.find('.source-number').text()).toBe('3')
    expect(wrapper.find('.source-number').attributes('aria-label')).toBe('来源3')
    expect(wrapper.text()).not.toContain('历史检索资料')
  })
})
