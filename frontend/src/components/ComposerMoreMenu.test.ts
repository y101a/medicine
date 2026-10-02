import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import ComposerMoreMenu from './ComposerMoreMenu.vue'
import type { PrivateKnowledgeCollection } from '../types/privateKnowledge'

/**
 * 输入框**左下角**的「+」菜单：只剩添加附件与私人知识。
 * 语音对话模式已按用户 2026-10-02 的第二条指令分离出去（见 `SpeechModeControl.test.ts`）。
 * 重点仍是那两件事：不再各自占输入框按钮；不可用时必须写明原因。
 */
const props = {
  attachmentsDisabledReason: '',
  attachmentCount: 0,
  attachmentLimit: 5,
  collections: [] as PrivateKnowledgeCollection[],
  collectionsLoading: false,
  collectionsError: '',
  selectedCollectionIds: [] as string[],
}

function mountMenu(overrides: Partial<typeof props> = {}) {
  // 私人知识区块里的管理入口走 router.push，所以这里给一个真的 memory router。
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/app/private-knowledge', name: 'private-knowledge', component: { template: '<div />' } }],
  })
  return mount(ComposerMoreMenu, {
    props: { ...props, ...overrides },
    attachTo: document.body,
    global: { plugins: [router, ElementPlus] },
  })
}

afterEach(() => {
  document.body.innerHTML = ''
})

/** 面板是否已收起：Element Plus 用 v-show/aria-hidden 控制弹层，判据取实际可见性。 */
function menuPopperHidden() {
  const menu = document.querySelector('.composer-more-menu')
  if (!menu) return true
  const popper = menu.closest('.el-popper')
  if (!popper) return true
  return popper.getAttribute('aria-hidden') === 'true'
    || (popper as HTMLElement).style.display === 'none'
}

describe('输入框左下角的「+」菜单', () => {
  it('收纳添加附件与私人知识，且不再包含语音对话模式', async () => {
    const wrapper = mountMenu()
    await wrapper.get('.composer-more-button').trigger('click')
    await nextTick()

    const menu = document.querySelector('.composer-more-menu')
    expect(menu?.textContent).toContain('添加附件')
    expect(menu?.textContent).toContain('私人知识')
    expect(menu?.textContent, '语音对话模式已分离为独立入口').not.toContain('语音对话模式')
    wrapper.unmount()
  })

  it('附件不可用时在面板里写明原因，而不是点了没反应', async () => {
    const wrapper = mountMenu({ attachmentsDisabledReason: '正在生成回答，稍后再添加' })
    await wrapper.get('.composer-more-button').trigger('click')
    await nextTick()

    expect(document.querySelector('.composer-more-menu')?.textContent).toContain('正在生成回答，稍后再添加')
    expect(document.querySelector<HTMLButtonElement>('.add-attachment')?.disabled).toBe(true)
    wrapper.unmount()
  })

  it('点「选择文档或图片」上抛事件并收起菜单，把屏幕让给系统文件选择器', async () => {
    const wrapper = mountMenu()
    await wrapper.get('.composer-more-button').trigger('click')
    await nextTick()

    document.querySelector<HTMLButtonElement>('.add-attachment')?.click()
    // ElPopover 的显隐由自身状态机驱动，收起要多等一个 tick 才反映到 DOM。
    await nextTick()
    await nextTick()

    expect(wrapper.emitted('add-attachment')).toHaveLength(1)
    expect(menuPopperHidden(), '点附件后菜单应收起，把屏幕让给系统文件选择器').toBe(true)
    wrapper.unmount()
  })
})