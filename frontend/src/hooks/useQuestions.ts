import { useQuery } from '@tanstack/react-query'
import { questionsApi } from '../api/questions'
import type { QuestionListParams } from '../api/questions'

export function useQuestions(params: QuestionListParams & { page: number; pageSize: number }) {
  return useQuery({
    queryKey: ['questions', params],
    queryFn: () => {
      const { pageSize, ...rest } = params
      return questionsApi.list({ ...rest, page_size: pageSize })
    },
  })
}

export function useTags() {
  return useQuery({ queryKey: ['tags'], queryFn: questionsApi.listTags, staleTime: 300_000 })
}

export function useQuestion(questionId: string | undefined) {
  return useQuery({
    queryKey: ['questions', questionId],
    queryFn: () => questionsApi.get(questionId!),
    enabled: Boolean(questionId),
  })
}
