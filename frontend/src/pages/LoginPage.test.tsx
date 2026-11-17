import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authMocks = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('../api/auth', () => ({ authApi: authMocks }))

import { LoginPage } from './LoginPage'
import { useAuthStore } from '../stores/authStore'

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/questions" element={<div>问题广场目标页</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LoginPage 组件', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    vi.clearAllMocks()
  })

  it('渲染学号/工号与密码输入框', () => {
    renderLoginPage()
    expect(screen.getByLabelText('学号 / 工号')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
  })

  it('空表单提交时展示必填校验且不调用登录接口', async () => {
    const user = userEvent.setup()
    renderLoginPage()

    await user.click(screen.getByRole('button', { name: /登\s*录/ }))

    expect(await screen.findByText('请输入学号或工号')).toBeInTheDocument()
    expect(await screen.findByText('请输入密码')).toBeInTheDocument()
    expect(authMocks.login).not.toHaveBeenCalled()
  })

  it('登录成功后写入令牌、用户信息并跳转问题广场', async () => {
    authMocks.login.mockResolvedValue({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      token_type: 'bearer',
      expires_in: 900,
    })
    authMocks.me.mockResolvedValue({
      id: 'user-1',
      role: 'student',
      email: '20260001@campus.edu.cn',
      student_id: '20260001',
      staff_id: null,
      created_at: '2026-09-15T00:00:00Z',
    })

    const user = userEvent.setup()
    renderLoginPage()
    await user.type(screen.getByLabelText('学号 / 工号'), '20260001')
    await user.type(screen.getByLabelText('密码'), 'Passw0rd8')
    await user.click(screen.getByRole('button', { name: /登\s*录/ }))

    await waitFor(() => expect(useAuthStore.getState().accessToken).toBe('access-token'))
    expect(useAuthStore.getState().user?.displayName).toBe('20260001')
    expect(await screen.findByText('问题广场目标页')).toBeInTheDocument()
    expect(authMocks.login).toHaveBeenCalledWith({ identifier: '20260001', password: 'Passw0rd8' })
  })

  it('登录失败时展示错误提示并清理本地会话', async () => {
    authMocks.login.mockRejectedValue(new Error('boom'))

    const user = userEvent.setup()
    renderLoginPage()
    await user.type(screen.getByLabelText('学号 / 工号'), '20260001')
    await user.type(screen.getByLabelText('密码'), 'Passw0rd8')
    await user.click(screen.getByRole('button', { name: /登\s*录/ }))

    expect(await screen.findByText('登录失败，请检查账号和密码')).toBeInTheDocument()
    expect(useAuthStore.getState().accessToken).toBeNull()
  })
})
