import { apiClient } from './client'
import type { NotificationListResponse } from './types'

export const notificationsApi = {
  list(params?: { page?: number; page_size?: number; unread_only?: boolean }) {
    return apiClient.get<NotificationListResponse>('/v1/notifications', { params }).then(({ data }) => data)
  },
  unreadCount() {
    return apiClient.get<{ count: number }>('/v1/notifications/unread-count').then(({ data }) => data)
  },
  markRead(notificationId: string) {
    return apiClient.post<void>(`/v1/notifications/${notificationId}/read`)
  },
  markAllRead() {
    return apiClient.post<{ updated: number }>('/v1/notifications/read-all').then(({ data }) => data)
  },
}
