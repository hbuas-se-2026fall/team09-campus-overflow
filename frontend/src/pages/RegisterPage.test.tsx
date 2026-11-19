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

import { RegisterPage } from './RegisterPage'

function renderRegisterPage() {
  return render(
    <MemoryRouter initialEntries={['/register']}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<div>登录页目标</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RegisterPage 组件', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('默认学生身份展示学号，切换教师后展示工号', async () => {
    const user = userEvent.setup()
    renderRegisterPage()

    expect(screen.getByLabelText('学号')).toBeInTheDocument()
    expect(screen.queryByLabelText('工号')).not.toBeInTheDocument()

    await user.click(screen.getByText('教师'))

    expect(await screen.findByLabelText('工号')).toBeInTheDocument()
    expect(screen.queryByLabelText('学号')).not.toBeInTheDocument()
  })

  it('弱密码（缺少数字）提交时展示强度校验提示', async () => {
    const user = userEvent.setup()
    renderRegisterPage()

    await user.type(screen.getByLabelText('学号'), '20260002')
    await user.type(screen.getByLabelText('邮箱'), 'student@campus.edu.cn')
    await user.type(screen.getByLabelText('密码'), 'abcdefgh')
    await user.click(screen.getByRole('button', { name: /注册并开始/ }))

    expect(await screen.findByText('密码至少 8 位且需同时包含字母和数字')).toBeInTheDocument()
    expect(authMocks.register).not.toHaveBeenCalled()
  })

  it('学生注册成功后跳转登录页', async () => {
    authMocks.register.mockResolvedValue({
      id: 'user-1',
      role: 'student',
      email: 'student@campus.edu.cn',
      student_id: '20260002',
      staff_id: null,
      created_at: '2026-09-15T00:00:00Z',
    })

    const user = userEvent.setup()
    renderRegisterPage()
    await user.type(screen.getByLabelText('学号'), '20260002')
    await user.type(screen.getByLabelText('邮箱'), 'student@campus.edu.cn')
    await user.type(screen.getByLabelText('密码'), 'Passw0rd8')
    await user.click(screen.getByRole('button', { name: /注册并开始/ }))

    await waitFor(() =>
      expect(authMocks.register).toHaveBeenCalledWith({
        role: 'student',
        email: 'student@campus.edu.cn',
        password: 'Passw0rd8',
        student_id: '20260002',
      }),
    )
    expect(await screen.findByText('登录页目标')).toBeInTheDocument()
  })
})
