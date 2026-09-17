import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import HospitalNavigator from './HospitalNavigator.vue'
import { navigationApi } from '../api/navigation'

vi.mock('../api/navigation', () => ({
  navigationApi: {
    nearby: vi.fn(),
    byArea: vi.fn(),
  },
}))

function setGeolocation(getCurrentPosition: Geolocation['getCurrentPosition']) {
  Object.defineProperty(navigator, 'geolocation', {
    value: { getCurrentPosition },
    configurable: true,
  })
}

function mountNavigator() {
  return mount(HospitalNavigator, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
}

beforeEach(() => {
  vi.resetAllMocks()
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('附近医院导航', () => {
  it('取得一次定位授权后查询路线，且只向接口传递本次坐标', async () => {
    const getCurrentPosition = vi.fn<Geolocation['getCurrentPosition']>((success) => success({
      coords: { latitude: 39.9, longitude: 116.4 },
    } as GeolocationPosition))
    setGeolocation(getCurrentPosition)
    vi.mocked(navigationApi.nearby).mockResolvedValue({
      mode: 'nearby',
      routeMode: 'driving',
      count: 1,
      notice: '最近不等于最适合。',
      items: [{
        poiId: 'p1',
        name: '测试医院',
        routeDistanceMeters: 1200,
        routeDurationSeconds: 360,
        routeMode: 'driving',
        navigationUrl: 'https://uri.amap.com/navigation?to=test',
      }],
    })
    const wrapper = mountNavigator()

    await wrapper.get('.navigator-trigger').trigger('click')
    expect(document.querySelector('[aria-label="出行方式"]')).toBeNull()
    expect(document.querySelector('.consent-actions')?.children).toHaveLength(2)
    await document.querySelector<HTMLButtonElement>('.locate-button')?.click()
    await flushPromises()

    expect(getCurrentPosition).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
      { enableHighAccuracy: false, timeout: 15_000, maximumAge: 300_000 },
    )
    expect(navigationApi.nearby).toHaveBeenCalledWith(39.9, 116.4)
    expect(document.body.textContent).toContain('测试医院')
    expect(document.body.textContent).toContain('预计 6 分钟')
    const link = document.querySelector<HTMLAnchorElement>('.hospital-card a')
    expect(link?.getAttribute('referrerpolicy')).toBe('no-referrer')
    wrapper.unmount()
  })

  it('定位被拒绝后自动切换城市或行政区查询', async () => {
    setGeolocation((_success, error) => error?.({ code: 1 } as GeolocationPositionError))
    vi.mocked(navigationApi.byArea).mockResolvedValue({
      mode: 'area',
      count: 1,
      notice: '不能判断哪家医院最近。',
      items: [{
        poiId: 'p2',
        name: '区域医院',
        navigationUrl: 'https://uri.amap.com/navigation?to=area',
      }],
    })
    const wrapper = mountNavigator()

    await wrapper.get('.navigator-trigger').trigger('click')
    await document.querySelector<HTMLButtonElement>('.locate-button')?.click()
    await flushPromises()
    expect(document.body.textContent).toContain('定位权限被拒绝')

    const input = document.querySelector<HTMLInputElement>('input[aria-label="城市或行政区编码"]')
    expect(input).not.toBeNull()
    if (input) {
      input.value = '110000'
      input.dispatchEvent(new Event('input'))
    }
    await flushPromises()
    await document.querySelector<HTMLFormElement>('.area-fallback form')?.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    )
    await flushPromises()

    expect(navigationApi.byArea).toHaveBeenCalledWith('110000')
    expect(document.body.textContent).toContain('区域医院')
    wrapper.unmount()
  })
})
