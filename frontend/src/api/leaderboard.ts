import { apiClient } from './client'
import type { LeaderboardPeriod, LeaderboardResponse } from './types'

export const leaderboardApi = {
  get(period: LeaderboardPeriod, limit = 10) {
    return apiClient.get<LeaderboardResponse>('/v1/leaderboard', { params: { period, limit } }).then(({ data }) => data)
  },
}
