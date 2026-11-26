import { apiClient } from './client'
import type { ReportResponse, ReportTarget } from './types'

export const reportsApi = {
  create(payload: { target_type: ReportTarget; target_id: string; reason: string }) {
    return apiClient.post<ReportResponse>('/v1/reports', payload).then(({ data }) => data)
  },
}
