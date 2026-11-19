import { apiClient } from './client'
import type { AnswerResponse, CommentResponse } from './types'

export type QuestionSort = 'latest' | 'votes'
export type QuestionStatus = 'open' | 'closed'

export type QuestionListItem = {
  id: string
  title: string
  author_id: string
  author_name: string
  created_at: string
  tags: string[]
  status: QuestionStatus
}

export type QuestionListResponse = {
  items: QuestionListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export type QuestionResponse = {
  id: string
  title: string
  body: string
  author_id: string
  author_name: string
  created_at: string
  tags: string[]
  status: QuestionStatus
}

export type QuestionDetailResponse = QuestionResponse & {
  accepted_answer_id: string | null
  answers: AnswerResponse[]
  comments: CommentResponse[]
}

export type QuestionDetail = QuestionResponse & {
  accepted_answer_id: string | null
  tags: string[]
  answers: AnswerResponse[]
  comments: CommentResponse[]
}

export type QuestionListParams = {
  page?: number
  page_size?: number
  sort?: QuestionSort
  q?: string
  tag?: string[]
  status?: QuestionStatus
  created_from?: string
  created_to?: string
}

function normalizeAnswer(answer: AnswerResponse): AnswerResponse {
  return { ...answer, comments: answer.comments ?? [] }
}

export const questionsApi = {
  list(params?: QuestionListParams) {
    return apiClient.get<QuestionListResponse>('/v1/questions', { params }).then(({ data }) => ({
      ...data,
      items: data.items.map((item) => ({ ...item, tags: item.tags ?? [] })),
    }))
  },
  get(questionId: string) {
    return apiClient.get<QuestionDetailResponse>(`/v1/questions/${questionId}`).then(({ data }) => ({
      ...data,
      tags: data.tags ?? [],
      answers: (data.answers ?? []).map(normalizeAnswer),
      accepted_answer_id: data.accepted_answer_id ?? null,
      comments: data.comments ?? [],
    }))
  },
  create(payload: { title: string; body: string; tags?: string[] }) {
    return apiClient.post<QuestionResponse>('/v1/questions', payload).then(({ data }) => ({ ...data, tags: data.tags ?? [] }))
  },
  edit(questionId: string, payload: { title?: string; body?: string }) {
    return apiClient.patch<QuestionResponse>(`/v1/questions/${questionId}`, payload).then(({ data }) => ({ ...data, tags: data.tags ?? [] }))
  },
  close(questionId: string) {
    return apiClient.post<void>(`/v1/questions/${questionId}/close`)
  },
  postAnswer(questionId: string, payload: { body: string }) {
    return apiClient.post<AnswerResponse>(`/v1/questions/${questionId}/answers`, payload).then(({ data }) => normalizeAnswer(data))
  },
  editAnswer(answerId: string, payload: { body: string }) {
    return apiClient.patch<AnswerResponse>(`/v1/answers/${answerId}`, payload).then(({ data }) => normalizeAnswer(data))
  },
  voteQuestion(questionId: string, direction: 'up' | 'down') {
    return apiClient.post<void>(`/v1/questions/${questionId}/vote`, { direction })
  },
  voteAnswer(questionId: string, answerId: string, direction: 'up' | 'down') {
    return apiClient.post<void>(`/v1/questions/${questionId}/answers/${answerId}/vote`, { direction })
  },
  commentQuestion(questionId: string, payload: { body: string }) {
    return apiClient.post<CommentResponse>(`/v1/questions/${questionId}/comments`, payload).then(({ data }) => data)
  },
  commentAnswer(answerId: string, payload: { body: string }) {
    return apiClient.post<CommentResponse>(`/v1/answers/${answerId}/comments`, payload).then(({ data }) => data)
  },
  acceptAnswer(answerId: string) {
    return apiClient.post<void>(`/v1/answers/${answerId}/accept`)
  },
  related(questionId: string, limit = 5) {
    return apiClient.get<QuestionListItem[]>(`/v1/questions/${questionId}/related`, { params: { limit } }).then(({ data }) => data.map((item) => ({ ...item, tags: item.tags ?? [] })))
  },
  getBounty(questionId: string) {
    return apiClient.get<import('./types').BountyResponse | null>(`/v1/questions/${questionId}/bounty`).then(({ data }) => data)
  },
  createBounty(questionId: string, amount: number) {
    return apiClient.post<import('./types').BountyResponse>(`/v1/questions/${questionId}/bounty`, { amount }).then(({ data }) => data)
  },
  listTags() {
    return apiClient.get<{ tags: string[] }>('/v1/tags').then(({ data }) => data.tags)
  },
}
