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

/** 后端对非受信网页给出「未核实网站（域名）」，非官网来源必须能点开核对。 */
const unverified: MessageCitation = {
  ...citation,
  organization: '未核实网站（health-news.example）',
  title: '某健康网站的快讯',
  canonicalUrl: 'https://health-news.example/article/1',
}

describe('联网参考来源', () => {
  it('非官网网页来源可点开核对，并标明未核实与未经医学审核', () => {
    const wrapper = mount(ReferenceSources, { props: { citations: [unverified] } })
    expect(wrapper.text()).toContain('未核实网页')
    expect(wrapper.text()).toContain('未经医学审核')
    expect(wrapper.text()).toContain('来源网址：health-news.example')
    expect(wrapper.find('a').attributes('href')).toBe('https://health-news.example/article/1')
    expect(wrapper.find('a').attributes('rel')).toContain('noopener')
    expect(wrapper.text()).toContain('前往 health-news.example 核对')
    // 非官网来源不得出现「官网」字样，避免被当成官方或已审核内容。
    expect(wrapper.text()).not.toContain('官网')
  })

  it('官方域名来源标为官网摘要并保留链接', () => {
    const wrapper = mount(ReferenceSources, { props: { citations: [citation] } })
    expect(wrapper.text()).toContain('官网摘要')
    expect(wrapper.text()).toContain('历史检索资料（引用未核验）')
    expect(wrapper.text()).toContain('请勿视为回答依据')
    expect(wrapper.find('a').attributes('href')).toBe('https://www.nhc.gov.cn/example')
  })

  it('疑似仿冒域名仍可点开核对，但只能显示为未核实网页', () => {
    const wrapper = mount(ReferenceSources, {
      props: { citations: [{ ...unverified, organization: '未核实网站（nhc.gov.cn.evil.test）', canonicalUrl: 'https://nhc.gov.cn.evil.test/' }] },
    })
    expect(wrapper.text()).toContain('未核实网页')
    expect(wrapper.text()).toContain('nhc.gov.cn.evil.test')
    expect(wrapper.text()).not.toContain('官网摘要')
  })

  it('非 https 与手写原型占位地址不可点击', () => {
    const insecure = mount(ReferenceSources, {
      props: { citations: [{ ...unverified, canonicalUrl: 'http://health-news.example/article/1' }] },
    })
    expect(insecure.find('a').exists()).toBe(false)

    const placeholder = mount(ReferenceSources, {
      props: { citations: [{
        ...citation, sourceKey: 'developer_prototype_knowledge',
        canonicalUrl: 'https://prototype.invalid/medical-knowledge/test',
      }] },
    })
    expect(placeholder.find('a').exists()).toBe(false)
    expect(placeholder.text()).toContain('开发原型')
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