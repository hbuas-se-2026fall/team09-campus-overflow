import { apiClient } from './client'
import type { CourseLeaderboardResponse, CourseResponse, CourseStudentItem, EnrollmentResponse, PageResponse } from './types'

export const coursesApi = {
  list(params: { page?: number; page_size?: number; semester?: string } = {}) {
    return apiClient.get<PageResponse<CourseResponse>>('/v1/courses', { params }).then(({ data }) => data)
  },
  create(payload: { code: string; name: string; semester: string }) {
    return apiClient.post<CourseResponse>('/v1/courses', payload).then(({ data }) => data)
  },
  enroll(courseId: string) {
    return apiClient.post<EnrollmentResponse>(`/v1/courses/${courseId}/enroll`).then(({ data }) => data)
  },
  students(courseId: string, page: number) {
    return apiClient.get<PageResponse<CourseStudentItem>>(`/v1/courses/${courseId}/students`, { params: { page, page_size: 20 } }).then(({ data }) => data)
  },
  leaderboard(courseId: string) {
    return apiClient.get<CourseLeaderboardResponse>(`/v1/courses/${courseId}/leaderboard`, { params: { limit: 20 } }).then(({ data }) => data)
  },
}
