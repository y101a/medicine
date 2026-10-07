import { describe, expect, it } from 'vitest'
import type { GraphRelation } from '../api/knowledgeGraph'
import {
  conceptTypeLabel,
  groupRelationsByPredicate,
  isHttpUrl,
  predicateLabel,
  readRelationReview,
} from './knowledgeGraphUi'

/**
 * 知识图谱展示层的纯函数测试。
 *
 * 这里独立覆盖 `readRelationReview`：它是「未审核关系必须标注」这条红线唯一的判定点，
 * 放在页面测试里被别的东西挡住了就看不出来。
 */

function relation(predicate: string, claimId = `claim-${predicate}`): GraphRelation {
  return {
    claimId,
    subject: { id: 's1', name: '儿童发热', type: 'topic' },
    object: { id: 'o1', name: '某个表现', type: 'symptom' },
    predicate,
    evidence: [],
  }
}

describe('知识图谱展示层纯函数', () => {
  it('按冻结的关系类型顺序分组，未登记的类型排在最后并标记出来', () => {
    const groups = groupRelationsByPredicate([
      relation('RELATED_TOPIC'),
      relation('HAS_RED_FLAG'),
      relation('CAUSES'),
      relation('MAY_INCLUDE_SYMPTOM'),
    ])

    expect(groups.map(group => group.predicate)).toEqual([
      'MAY_INCLUDE_SYMPTOM',
      'HAS_RED_FLAG',
      'RELATED_TOPIC',
      'CAUSES',
    ])
    expect(groups.map(group => group.label)).toEqual([
      '可能出现的表现',
      '需要警惕的红旗提醒',
      '相关主题',
      'CAUSES',
    ])
    expect(groups.map(group => group.known)).toEqual([true, true, true, false])
  })

  it('没有审核字段时按已审核处理（后端只发布 approved + published）', () => {
    expect(readRelationReview(relation('RELATED_TOPIC'))).toEqual({ reviewed: true, raw: null })
    expect(readRelationReview(null)).toEqual({ reviewed: true, raw: null })
  })

  it('出现 candidate / pending / rejected 等取值时必须判为未审核', () => {
    expect(readRelationReview({ reviewDecision: 'pending' })).toEqual({
      reviewed: false,
      raw: 'pending',
    })
    expect(readRelationReview({ status: 'candidate' }).reviewed).toBe(false)
    expect(readRelationReview({ status: 'published', reviewDecision: 'approved' })).toEqual({
      reviewed: true,
      raw: 'published / approved',
    })
    // 字段混用时只要有一个不是已审核值，就不能当成事实展示。
    expect(readRelationReview({ status: 'published', reviewDecision: 'returned' }).reviewed).toBe(
      false,
    )
  })

  it('标签查不到时回落到后端原值，不做假翻译；只有 http(s) 才允许生成外链', () => {
    expect(predicateLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
    expect(conceptTypeLabel('topic')).toBe('主题')
    expect(conceptTypeLabel('unknown_type')).toBe('unknown_type')

    expect(isHttpUrl('https://example.org/a')).toBe(true)
    expect(isHttpUrl('http://example.org/a')).toBe(true)
    expect(isHttpUrl('javascript:alert(1)')).toBe(false)
    expect(isHttpUrl('data:text/html,<script></script>')).toBe(false)
    expect(isHttpUrl(null)).toBe(false)
    expect(isHttpUrl(undefined)).toBe(false)
  })
})