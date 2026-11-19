import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const hookMocks = vi.hoisted(() => ({ useTags: vi.fn() }))
vi.mock('../hooks/useQuestions', () => hookMocks)

import { TagsPage } from './TagsPage'

describe('TagsPage 组件', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染标签目录与全部标签', () => {
    hookMocks.useTags.mockReturnValue({ data: ['React', 'TypeScript', 'PostgreSQL'], isLoading: false, isError: false })

    render(<TagsPage />)

    expect(screen.getByText('标签目录')).toBeInTheDocument()
    expect(screen.getByText('React')).toBeInTheDocument()
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL')).toBeInTheDocument()
  })

  it('无标签时展示空状态', () => {
    hookMocks.useTags.mockReturnValue({ data: [], isLoading: false, isError: false })

    render(<TagsPage />)

    expect(screen.getByText('还没有标签')).toBeInTheDocument()
  })

  it('加载失败时展示错误空状态', () => {
    hookMocks.useTags.mockReturnValue({ data: undefined, isLoading: false, isError: true })

    render(<TagsPage />)

    expect(screen.getByText('暂时无法加载标签')).toBeInTheDocument()
  })
})
