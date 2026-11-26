import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('./client', () => ({ apiClient: apiMocks }))

import { questionsApi } from './questions'

describe('questionsApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses separate verification and soft-delete endpoints without changing acceptance', async () => {
    apiMocks.post.mockResolvedValue({ data: { id: 'answer-id', is_teacher_verified: true, verified_by_name: '教师', verified_at: '2026-11-26T00:00:00Z' } })
    apiMocks.delete.mockResolvedValue({ data: undefined })
    await expect(questionsApi.verifyAnswer('answer-id')).resolves.toMatchObject({ is_teacher_verified: true, comments: [] })
    await questionsApi.unverifyAnswer('answer-id')
    await questionsApi.deleteAnswer('answer-id')
    await questionsApi.deleteQuestion('question-id')
    expect(apiMocks.post).toHaveBeenCalledWith('/v1/answers/answer-id/verify')
    expect(apiMocks.delete.mock.calls.map(([url]) => url)).toEqual(['/v1/answers/answer-id/verify', '/v1/answers/answer-id', '/v1/questions/question-id'])
  })

  it('preserves reply parent, course unlink and answer verification data on edits', async () => {
    apiMocks.post.mockResolvedValue({ data: { id: 'reply', parent_id: 'root' } })
    await questionsApi.commentQuestion('question-id', { body: '回复', parent_id: 'root' })
    await questionsApi.commentAnswer('answer-id', { body: '答评回复', parent_id: 'answer-root' })
    apiMocks.patch.mockResolvedValue({ data: { id: 'question-id', course_id: null } })
    await questionsApi.edit('question-id', { course_id: null })
    apiMocks.patch.mockResolvedValue({ data: { id: 'answer-id', is_teacher_verified: true } })
    await expect(questionsApi.editAnswer('answer-id', { body: '修改后的回答' })).resolves.toMatchObject({ is_teacher_verified: true, comments: [] })
    expect(apiMocks.post).toHaveBeenCalledWith('/v1/questions/question-id/comments', { body: '回复', parent_id: 'root' })
    expect(apiMocks.post).toHaveBeenCalledWith('/v1/answers/answer-id/comments', { body: '答评回复', parent_id: 'answer-root' })
    expect(apiMocks.patch).toHaveBeenCalledWith('/v1/questions/question-id', { course_id: null })
    expect(apiMocks.patch).toHaveBeenCalledWith('/v1/answers/answer-id', { body: '修改后的回答' })
  })

  it('loads related questions and distinguishes absent bounty from a created bounty', async () => {
    apiMocks.get.mockResolvedValueOnce({ data: [{ id: 'related' }] }).mockResolvedValueOnce({ data: null })
    apiMocks.post.mockResolvedValue({ data: { id: 'bounty', amount: 10 } })
    await expect(questionsApi.related('question-id')).resolves.toEqual([{ id: 'related', tags: [] }])
    await expect(questionsApi.getBounty('question-id')).resolves.toBeNull()
    await expect(questionsApi.createBounty('question-id', 10)).resolves.toMatchObject({ amount: 10 })
  })

  it('requests the paginated question list with the contract path and params', async () => {
    apiMocks.get.mockResolvedValue({ data: {
      items: [{ id: 'question-id', title: '标题', author_id: 'author-id', created_at: '2026-09-15T00:00:00Z', status: 'closed' }],
      total: 1,
      page: 2,
      page_size: 10,
      total_pages: 1,
    } })

    await expect(questionsApi.list({ page: 2, page_size: 10, sort: 'votes' })).resolves.toMatchObject({
      items: [{ id: 'question-id', tags: [], status: 'closed' }],
    })

    expect(apiMocks.get).toHaveBeenCalledWith('/v1/questions', { params: { page: 2, page_size: 10, sort: 'votes' }, paramsSerializer: { indexes: null } })
  })

  it('posts only title and body when creating a question', async () => {
    apiMocks.post.mockResolvedValue({ data: { id: 'question-id' } })

    await questionsApi.create({ title: '一个问题标题', body: '问题的详细描述' })

    expect(apiMocks.post).toHaveBeenCalledWith('/v1/questions', {
      title: '一个问题标题',
      body: '问题的详细描述',
    })
  })

  it('normalizes optional detail collections to empty arrays', async () => {
    apiMocks.get.mockResolvedValue({
      data: {
        id: 'question-id',
        title: '问题标题',
        body: '问题正文',
        author_id: 'author-id',
        created_at: '2026-09-15T00:00:00Z',
        status: 'closed',
        answers: [{ id: 'answer-id', body: '回答', author_id: 'author-id', created_at: '2026-09-15T00:00:00Z', votes: 2, is_accepted: false }],
      },
    })

    await expect(questionsApi.get('question-id')).resolves.toMatchObject({
      tags: [],
      answers: [{ id: 'answer-id', comments: [] }],
      comments: [],
      accepted_answer_id: null,
      status: 'closed',
    })
    expect(apiMocks.get).toHaveBeenCalledWith('/v1/questions/question-id')
  })

  it('sends tags when creating a question and normalizes the response', async () => {
    apiMocks.post.mockResolvedValue({ data: { id: 'question-id', title: '标题', body: '正文' } })

    await expect(questionsApi.create({ title: '标题', body: '正文', tags: ['React'] })).resolves.toMatchObject({
      id: 'question-id',
      tags: [],
    })
    expect(apiMocks.post).toHaveBeenCalledWith('/v1/questions', { title: '标题', body: '正文', tags: ['React'] })
  })

  it('uses the answer, vote, comment, accept, and tag contract paths', async () => {
    apiMocks.post.mockImplementation(async (path: string) => {
      if (path.endsWith('/answers')) {
        return { data: { id: 'answer-id', body: '回答', author_id: 'author-id', created_at: '2026-09-15T00:00:00Z', votes: 0, is_accepted: false } }
      }
      if (path.includes('/comments')) {
        return { data: { id: 'comment-id', body: '评论', author_id: 'author-id', created_at: '2026-09-15T00:00:00Z' } }
      }
      return { data: undefined }
    })
    apiMocks.get.mockResolvedValue({ data: { tags: ['React', 'TypeScript'] } })

    await expect(questionsApi.postAnswer('question-id', { body: '回答' })).resolves.toMatchObject({ comments: [] })
    await questionsApi.voteQuestion('question-id', 'up')
    await questionsApi.voteAnswer('question-id', 'answer-id', 'down')
    await questionsApi.commentQuestion('question-id', { body: '评论问题' })
    await questionsApi.commentAnswer('answer-id', { body: '评论回答' })
    await questionsApi.acceptAnswer('answer-id')
    await expect(questionsApi.listTags()).resolves.toEqual(['React', 'TypeScript'])

    expect(apiMocks.post).toHaveBeenNthCalledWith(1, '/v1/questions/question-id/answers', { body: '回答' })
    expect(apiMocks.post).toHaveBeenNthCalledWith(2, '/v1/questions/question-id/vote', { direction: 'up' })
    expect(apiMocks.post).toHaveBeenNthCalledWith(3, '/v1/questions/question-id/answers/answer-id/vote', { direction: 'down' })
    expect(apiMocks.post).toHaveBeenNthCalledWith(4, '/v1/questions/question-id/comments', { body: '评论问题' })
    expect(apiMocks.post).toHaveBeenNthCalledWith(5, '/v1/answers/answer-id/comments', { body: '评论回答' })
    expect(apiMocks.post).toHaveBeenNthCalledWith(6, '/v1/answers/answer-id/accept')
    expect(apiMocks.get).toHaveBeenCalledWith('/v1/tags')
  })

  it('patches only provided fields and closes a question through the contract paths', async () => {
    apiMocks.patch.mockResolvedValue({ data: { id: 'question-id', title: '新标题', body: '正文' } })
    apiMocks.post.mockResolvedValue({ data: undefined })

    await expect(questionsApi.edit('question-id', { title: '新标题' })).resolves.toMatchObject({
      id: 'question-id',
      tags: [],
    })
    await questionsApi.close('question-id')

    expect(apiMocks.patch).toHaveBeenCalledWith('/v1/questions/question-id', { title: '新标题' })
    expect(apiMocks.post).toHaveBeenCalledWith('/v1/questions/question-id/close')
  })
})
