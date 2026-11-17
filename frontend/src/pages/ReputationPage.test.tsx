import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hookMocks = vi.hoisted(() => ({ useReputation: vi.fn() }))
vi.mock('../hooks/useReputation', () => hookMocks)

import { ReputationPage } from './ReputationPage'
import { useAuthStore } from '../stores/authStore'

const demoUser = {
  id: 'user-1',
  email: '20260001@campus.edu.cn',
  studentId: '20260001',
  staffId: null,
  createdAt: '2026-09-15T00:00:00Z',
  displayName: '20260001',
  role: 'student' as const,
}

describe('ReputationPage 组件', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.getState().logout()
  })

  it('渲染总声誉与变动流水', () => {
    useAuthStore.getState().setUser(demoUser)
    hookMocks.useReputation.mockReturnValue({
      data: {
        user_id: 'user-1',
        total: 28,
        entries: [
          { source: 'vote', event_id: 'event-1', delta: 10, reason: '回答被点赞', occurred_at: '2026-09-15T00:00:00Z' },
          { source: 'accept', event_id: 'event-2', delta: 15, reason: '回答被采纳', occurred_at: '2026-09-16T00:00:00Z' },
        ],
      },
      isLoading: false,
      isError: false,
    })

    render(<ReputationPage />)

    expect(screen.getByText('当前总声誉')).toBeInTheDocument()
    expect(screen.getByText('28')).toBeInTheDocument()
    expect(screen.getByText('回答被点赞')).toBeInTheDocument()
    expect(screen.getByText('回答被采纳')).toBeInTheDocument()
    expect(screen.getByText('+10')).toBeInTheDocument()
    expect(screen.getByText('+15')).toBeInTheDocument()
  })

  it('没有流水时展示空状态', () => {
    useAuthStore.getState().setUser(demoUser)
    hookMocks.useReputation.mockReturnValue({
      data: { user_id: 'user-1', total: 0, entries: [] },
      isLoading: false,
      isError: false,
    })

    render(<ReputationPage />)

    expect(screen.getByText('暂时没有声誉流水')).toBeInTheDocument()
  })

  it('请求失败时展示错误空状态', () => {
    useAuthStore.getState().setUser(demoUser)
    hookMocks.useReputation.mockReturnValue({ data: undefined, isLoading: false, isError: true })

    render(<ReputationPage />)

    expect(screen.getByText('暂时无法加载声誉，请稍后重试')).toBeInTheDocument()
  })
})
