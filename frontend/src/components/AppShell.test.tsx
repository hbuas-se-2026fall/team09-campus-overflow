import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const authMocks = vi.hoisted(() => ({ logout: vi.fn() }))
vi.mock('../api/auth', () => ({ authApi: authMocks }))

import { AppShell } from './AppShell'
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

function renderShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/questions']}>
        <Routes>
          <Route path="*" element={<AppShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell 组件', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    vi.clearAllMocks()
  })

  it('访客态只展示公共导航与登录入口', () => {
    renderShell()
    expect(screen.getByText('问题广场')).toBeInTheDocument()
    expect(screen.getByText('标签目录')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /登\s*录/ })).toBeInTheDocument()
    expect(screen.queryByText('发布问题')).not.toBeInTheDocument()
    expect(screen.queryByText('我的声誉')).not.toBeInTheDocument()
  })

  it('登录态展示用户标识、个人导航与退出入口', () => {
    useAuthStore.getState().setTokens({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      token_type: 'bearer',
      expires_in: 900,
    })
    useAuthStore.getState().setUser(demoUser)

    renderShell()
    expect(screen.getByText('20260001')).toBeInTheDocument()
    expect(screen.getByText('发布问题')).toBeInTheDocument()
    expect(screen.getByText('我的声誉')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /退\s*出/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /登\s*录/ })).not.toBeInTheDocument()
  })
})
