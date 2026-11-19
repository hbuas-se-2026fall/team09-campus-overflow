import { apiClient } from './client'
import type { MyPointsResponse } from './types'

export const pointsApi = {
  getMine() {
    return apiClient.get<MyPointsResponse>('/v1/users/me/points').then(({ data }) => data)
  },
}
