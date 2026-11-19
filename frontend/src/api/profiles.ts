import { apiClient } from './client'
import type { PublicUserProfileResponse, UserBadgesResponse } from './types'

export const profilesApi = {
  get(userId: string) {
    return apiClient.get<PublicUserProfileResponse>(`/v1/users/${userId}/profile`).then(({ data }) => data)
  },
  badges(userId: string) {
    return apiClient.get<UserBadgesResponse>(`/v1/users/${userId}/badges`).then(({ data }) => data)
  },
}
