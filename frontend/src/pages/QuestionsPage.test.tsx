import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hookMocks = vi.hoisted(() => ({ useQuestions: vi.fn() }))
vi.mock('../hooks/useQuestions', () => hookMocks)

import { QuestionsPage } from './QuestionsPage'

const questions = [
  {
    id: 'q1',
    title: '如何在 React 项目中设计登录状态管理？',
    author_id: 'author-1',
    created_at: '2026-09-15T00:00:00Z',
    tags: ['React', 'TypeScript'],
    status: 'open',
  },
  {
    id: 'q2',
    title: 'PostgreSQL 复合唯一索引如何避免重复投票？',
    author_id: 'author-2',
    created_at: '2026-09-16T00:00:00Z',
    tags: [],
    status: 'open',
  },
]

function renderQuestionsPage() {
  return render(
    <MemoryRouter initialEntries={['/questions']}>
      <QuestionsPage />
    </MemoryRouter>,
  )
}

describe('QuestionsPage 组件', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    hookMocks.useQuestions.mockReturnValue({
      data: { items: questions, total: 2, page: 1, page_size: 10, total_pages: 1 },
      isLoading: false,
      isError: false,
    })
  })

  it('渲染问题列表、标签与总数', () => {
    renderQuestionsPage()

    expect(screen.getByText('如何在 React 项目中设计登录状态管理？')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL 复合唯一索引如何避免重复投票？')).toBeInTheDocument()
    expect(screen.getByText('React')).toBeInTheDocument()
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
    expect(screen.getByText('共 2 个问题')).toBeInTheDocument()
  })

  it('搜索框只过滤当前页标题', async () => {
    const user = userEvent.setup()
    renderQuestionsPage()

    await user.type(screen.getByPlaceholderText('搜索当前页标题'), 'PostgreSQL')

    expect(screen.getByText('PostgreSQL 复合唯一索引如何避免重复投票？')).toBeInTheDocument()
    expect(screen.queryByText('如何在 React 项目中设计登录状态管理？')).not.toBeInTheDocument()
  })

  it('加载失败时展示空状态提示', () => {
    hookMocks.useQuestions.mockReturnValue({ data: undefined, isLoading: false, isError: true })

    renderQuestionsPage()

    expect(screen.getByText('暂时无法加载问题，请稍后再试')).toBeInTheDocument()
  })
})
