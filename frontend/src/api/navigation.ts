import http from './http'

export type NavigationMode = 'driving' | 'walking'

export interface HospitalNavigationItem {
  poiId?: string | null
  name: string
  address?: string | null
  telephone?: string | null
  district?: string | null
  straightDistanceMeters?: number | null
  routeDistanceMeters?: number | null
  routeDurationSeconds?: number | null
  routeMode?: NavigationMode | null
  navigationUrl: string
}

export interface HospitalNavigationResponse {
  mode: 'nearby' | 'area'
  routeMode?: NavigationMode | null
  count: number
  items: HospitalNavigationItem[]
  notice: string
}

export const navigationApi = {
  async nearby(
    latitude: number,
    longitude: number,
  ) {
    return (await http.post<HospitalNavigationResponse>(
      '/navigation/nearby-hospitals',
      { latitude, longitude, locationConsent: true },
      { timeout: 30_000 },
    )).data
  },

  async byArea(city: string) {
    return (await http.post<HospitalNavigationResponse>(
      '/navigation/hospitals-by-area',
      { city },
    )).data
  },
}
