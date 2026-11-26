import { apiClient } from './client'
import type { AdminUserItem, PageResponse, ReportAction, ReportResponse, ReportStatus, ReportTarget, UserRole } from './types'

export const adminApi = {
  users(params: { page: number; page_size: number; role?: UserRole }) {
    return apiClient.get<PageResponse<AdminUserItem>>('/v1/admin/users', { params }).then(({ data }) => data)
  },
  updateRole(userId: string, role: UserRole) {
    return apiClient.patch<AdminUserItem>(`/v1/admin/users/${userId}/role`, { role }).then(({ data }) => data)
  },
  reports(params: { page: number; page_size: number; status: ReportStatus | 'all'; target_type?: ReportTarget }) {
    return apiClient.get<PageResponse<ReportResponse>>('/v1/admin/reports', { params }).then(({ data }) => data)
  },
  resolveReport(reportId: string, payload: { action: ReportAction; note?: string }) {
    return apiClient.post<ReportResponse>(`/v1/admin/reports/${reportId}/resolve`, payload).then(({ data }) => data)
  },
}
