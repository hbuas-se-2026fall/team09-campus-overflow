import { expect, test, type Page } from '@playwright/test'

type Role = 'student' | 'teacher' | 'ta' | 'admin'

async function setup(page: Page, role: Role = 'student') {
  const state = {
    role, userId: 'viewer', closed: false, verified: false, accepted: false, failVerify: false,
    verificationRequests: 0, notificationCount: 0, adminRequests: 0,
    deletedAnswer: false, deletedQuestion: false, courseFilter: '', enrolled: false,
    reply: '', reportReason: '', resolution: '', targetRole: 'student',
  }
  await page.addInitScript(() => localStorage.setItem('campus-overflow-auth', JSON.stringify({ version: 0, state: { accessToken: 'test-access', refreshToken: 'test-refresh', user: { id: 'viewer', role: 'admin', displayName: '旧身份', email: 'test@example.com' } } })))
  const course = { id: 'course-1', code: 'SE101', name: '软件工程', semester: '2026-Fall', teacher_id: 'teacher-1', teacher_name: '任课教师', created_at: '2026-11-26T00:00:00Z' }
  const user = () => ({ id: state.userId, email: 'test@example.com', role: state.role, student_id: '20260001', staff_id: null, created_at: '2026-11-26T00:00:00Z', nickname: '当前用户' })
  const root = { id: 'comment-1', author_id: 'author', author_name: '评论作者', body: '一级评论', parent_id: null, created_at: '2026-11-26T00:00:00Z' }
  const answer = () => ({ id: 'answer-1', body: '这是等待认证的回答', author_id: 'writer', author_name: '回答作者', votes: 2, is_accepted: state.accepted, is_teacher_verified: state.verified, verified_by_name: state.verified ? '认证老师' : null, verified_at: state.verified ? '2026-11-26T01:00:00Z' : null, created_at: '2026-11-26T00:00:00Z', comments: [] })
  const question = () => ({ id: 'question-1', title: 'F15 角色权限验收问题', body: '用于检查不同角色的认证与内容管理行为。', author_id: 'author', author_name: '提问作者', status: state.closed ? 'closed' : 'open', created_at: '2026-11-26T00:00:00Z', tags: [], course_id: 'course-1', course_name: '软件工程', accepted_answer_id: state.accepted ? 'answer-1' : null, answers: state.deletedAnswer ? [] : [answer()], comments: [root, ...(state.reply ? [{ ...root, id: 'reply-1', parent_id: root.id, body: state.reply, author_name: '当前用户' }] : [])] })
  const report = () => ({ id: 'report-1', reporter_id: 'viewer', reporter_name: '举报同学', target_type: 'answer', target_id: 'answer-1', reason: '举报理由需要核查', status: state.resolution ? 'dismissed' : 'pending', resolution_action: state.resolution || null, resolution_note: null, resolved_by_name: state.resolution ? '管理员' : null, created_at: '2026-11-26T00:00:00Z' })
  const paged = (items: unknown[], pageSize = 20) => ({ items, total: items.length, page: 1, page_size: pageSize, total_pages: items.length ? 1 : 0 })
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api/v1', '')
    const method = route.request().method()
    const ok = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === '/auth/me') return ok(user())
    if (path === '/notifications/unread-count') return ok({ count: state.notificationCount })
    if (path === '/notifications') return ok(paged([{ id: 'notice-1', type: 'answer_verified', actor_id: 'teacher-1', actor_name: '认证老师', target_type: 'answer', target_id: 'answer-1', question_id: 'question-1', is_read: false, created_at: '2026-11-26T01:00:00Z' }]))
    if (path === '/tags') return ok({ tags: ['React'] })
    if (path === '/questions/question-1/related') return ok([])
    if (path === '/questions/question-1/bounty') return route.fulfill({ contentType: 'application/json', body: 'null' })
    if (path === '/answers/answer-1/verify') {
      state.verificationRequests++
      if (state.role === 'student') return ok({ detail: '仅教职人员可认证回答' }, 403)
      if (state.closed || state.failVerify) return ok({ detail: '已关闭的问题不可认证回答' }, 409)
      if (method === 'POST') { if (!state.verified) state.notificationCount++; state.verified = true; return ok(answer()) }
      state.verified = false
      return route.fulfill({ status: 204 })
    }
    if (path === '/questions/question-1/comments' && method === 'POST') {
      const body = route.request().postDataJSON()
      expect(body.parent_id).toBe('comment-1')
      state.reply = body.body
      return ok({ ...root, id: 'reply-1', parent_id: root.id, body: state.reply }, 201)
    }
    if (path === '/questions/question-1' && method === 'DELETE') { state.deletedQuestion = true; return route.fulfill({ status: 204 }) }
    if (path === '/answers/answer-1' && method === 'DELETE') { state.deletedAnswer = true; return route.fulfill({ status: 204 }) }
    if (path === '/questions/question-1') return state.deletedQuestion ? ok({ detail: '问题不存在' }, 404) : ok(question())
    if (path === '/questions') {
      state.courseFilter = url.searchParams.get('course_id') ?? ''
      if (method === 'POST') { expect(route.request().postDataJSON().course_id).toBe('course-1'); return ok(question(), 201) }
      return ok(paged(state.deletedQuestion ? [] : [question()], 10))
    }
    if (path === '/courses') {
      if (method === 'POST') { expect(route.request().postDataJSON().code).toBe('SE102'); return ok({ ...course, code: 'SE102' }, 201) }
      return ok(paged([course], Number(url.searchParams.get('page_size') ?? 10)))
    }
    if (path === '/courses/course-1/enroll') { state.enrolled = true; return ok({ id: 'enroll-1', course_id: course.id, student_id: state.userId, student_name: '当前用户', enrolled_at: course.created_at }, 201) }
    if (path === '/courses/course-1/students') return ok(paged([{ student_id: 'learner', student_name: '选课学生', enrolled_at: course.created_at }]))
    if (path === '/courses/course-1/leaderboard') return ok({ course_id: course.id, course_name: course.name, course_code: course.code, entries: [{ user_id: 'learner', display_name: '课程贡献者', rank: 1, accepted_count: 1, net_votes: 2, answer_count: 3 }] })
    if (path === '/reports') { state.reportReason = route.request().postDataJSON().reason; return ok(report(), 201) }
    if (path.startsWith('/admin/')) {
      state.adminRequests++
      if (state.role !== 'admin') return ok({ detail: '无管理员权限' }, 403)
      if (path === '/admin/users') return ok(paged([{ ...user(), display_name: '当前管理员' }, { ...user(), id: 'target-user', role: state.targetRole, display_name: '目标学生', email: 'target@example.com' }]))
      if (path === '/admin/users/target-user/role') { state.targetRole = route.request().postDataJSON().role; return ok({ ...user(), id: 'target-user', role: state.targetRole, display_name: '目标学生' }) }
      if (path === '/admin/reports') return ok(paged([report()]))
      if (path === '/admin/reports/report-1/resolve') { state.resolution = route.request().postDataJSON().action; return ok(report()) }
    }
    return ok({ detail: `未预期请求：${method} ${path}` }, 404)
  })
  return state
}

async function select(page: Page, label: string, option: string) {
  await page.locator('.ant-select').filter({ has: page.getByRole('combobox', { name: label, exact: true }) }).click()
  await page.locator('.ant-select-dropdown:visible').getByText(option, { exact: true }).click()
}

for (const role of ['teacher', 'ta', 'admin'] as const) {
  test(`${role} 可以认证、刷新展示、取消认证，保持悬赏角色限制`, async ({ page }) => {
    const state = await setup(page, role)
    await page.goto('/questions/question-1')
    await expect(page.getByRole('button', { name: /认证回答$/ })).toBeVisible()
    await expect(page.getByRole('button', { name: '发起教师悬赏' })).toHaveCount(role === 'teacher' ? 1 : 0)
    await page.getByRole('button', { name: /认证回答$/ }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(page.getByText('教职认证', { exact: true })).toBeVisible()
    await expect(page.getByText(/认证人：认证老师/)).toBeVisible()
    await page.reload()
    await expect(page.getByText('教职认证', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: /取消认证$/ }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(page.getByText('教职认证', { exact: true })).toHaveCount(0)
    expect(state.verificationRequests).toBe(2)
    expect(state.notificationCount).toBe(1)
  })
}

test('学生忽略伪造本地管理员角色，不能认证或进入后台', async ({ page }) => {
  const state = await setup(page)
  await page.goto('/questions/question-1')
  await expect(page.getByRole('heading', { name: 'F15 角色权限验收问题' })).toBeVisible()
  await expect(page.getByRole('button', { name: /认证回答$/ })).toHaveCount(0)
  await page.goto('/admin')
  await expect(page.getByText('仅管理员可访问管理后台', { exact: true })).toBeVisible()
  expect(state.adminRequests).toBe(0)
  expect(state.verificationRequests).toBe(0)
})

test('教师被降级后认证返回403，页面移除入口', async ({ page }) => {
  const state = await setup(page, 'teacher')
  await page.goto('/questions/question-1')
  await page.getByRole('button', { name: /认证回答$/ }).click()
  state.role = 'student'
  await page.getByRole('button', { name: /^确\s*认$/ }).click()
  await expect(page.getByText('仅教职人员可认证回答')).toBeVisible()
  await expect(page.getByRole('button', { name: /认证回答$/ })).toHaveCount(0)
})

test('关闭问题禁止认证，认证409展示后端错误', async ({ page }) => {
  const state = await setup(page, 'ta')
  state.closed = true
  await page.goto('/questions/question-1')
  await expect(page.getByText('问题已关闭，相关操作已冻结。')).toBeVisible()
  await expect(page.getByRole('button', { name: /认证回答$/ })).toHaveCount(0)
  state.closed = false
  await page.reload()
  await page.getByRole('button', { name: /认证回答$/ }).click()
  state.failVerify = true
  await page.getByRole('button', { name: /^确\s*认$/ }).click()
  await expect(page.getByText('已关闭的问题不可认证回答')).toBeVisible()
  await expect(page.getByText('教职认证', { exact: true })).toHaveCount(0)
})

test('认证通知显示明确文案和问题链接', async ({ page }) => {
  await setup(page)
  await page.goto('/notifications')
  await expect(page.getByText('认证了你的回答')).toBeVisible()
  await expect(page.getByRole('link', { name: '查看相关问题' })).toHaveAttribute('href', '/questions/question-1')
})

test('真实后台可改他人角色，禁止改自己，并可审核回答举报', async ({ page }) => {
  const state = await setup(page, 'admin')
  await page.goto('/admin')
  const ownRow = page.getByRole('row').filter({ hasText: '当前管理员' })
  await expect(ownRow.getByRole('button', { name: '修改角色' })).toBeDisabled()
  await page.getByRole('row').filter({ hasText: '目标学生' }).getByRole('button', { name: '修改角色' }).click()
  await select(page, '新角色', '助教')
  await page.getByRole('button', { name: '确认修改' }).click()
  await expect(page.getByRole('row').filter({ hasText: '目标学生' }).getByText('助教', { exact: true })).toBeVisible()
  expect(state.targetRole).toBe('ta')
  await page.getByRole('tab', { name: '举报审核' }).click()
  await page.getByRole('button', { name: '审核举报' }).click()
  await page.locator('.ant-select').filter({ has: page.getByRole('combobox', { name: '举报处理动作' }) }).click()
  await expect(page.locator('.ant-select-dropdown:visible').getByText('关闭问题', { exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '确认处理' }).click()
  await expect(page.getByRole('button', { name: '审核举报' })).toBeDisabled()
  expect(state.resolution).toBe('dismiss')
})

test('二级回复发送parent_id，举报发送原因，问题删除后回列表', async ({ page }) => {
  const state = await setup(page)
  state.userId = 'author'
  await page.goto('/questions/question-1')
  await page.getByRole('button', { name: '回复', exact: true }).click()
  await page.getByRole('textbox', { name: '回复内容' }).fill('这是二级回复')
  await page.getByRole('button', { name: '发送回复' }).click()
  await expect(page.getByText('这是二级回复', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '举报回答', exact: true }).click()
  await page.getByRole('textbox', { name: '举报原因' }).fill('这条回答存在不适宜内容')
  await page.getByRole('button', { name: '提交举报' }).click()
  await expect(page.getByRole('button', { name: '举报已提交' })).toBeDisabled()
  expect(state.reportReason).toBe('这条回答存在不适宜内容')
  await page.getByRole('button', { name: '删除问题' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page).toHaveURL(/\/questions$/)
  expect(state.deletedQuestion).toBe(true)
})

test('回答作者可删除关闭问题下的未采纳回答', async ({ page }) => {
  const state = await setup(page)
  state.userId = 'writer'; state.closed = true
  await page.goto('/questions/question-1')
  await page.getByRole('button', { name: '删除回答' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page.getByText('这是等待认证的回答', { exact: true })).toHaveCount(0)
  expect(state.deletedAnswer).toBe(true)
})

test('课程中心可选课、查看贡献榜和按课程筛选问题', async ({ page }) => {
  const state = await setup(page)
  await page.goto('/courses')
  await page.getByRole('button', { name: '选修此课程' }).click()
  await expect(page.getByText('选课成功，现在可以关联该课程提问')).toBeVisible()
  expect(state.enrolled).toBe(true)
  await page.getByRole('button', { name: '课程贡献榜' }).click()
  await expect(page.getByRole('link', { name: '课程贡献者' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('link', { name: '课程问题', exact: true }).click()
  await expect(page).toHaveURL(/course_id=course-1/)
  await expect(page.getByRole('link', { name: 'F15 角色权限验收问题' })).toBeVisible()
  expect(state.courseFilter).toBe('course-1')
})

test('教师可创建课程和查看名录，助教不可创建课程', async ({ page }) => {
  const state = await setup(page, 'teacher')
  await page.goto('/courses')
  await page.getByRole('button', { name: '创建课程' }).click()
  await page.getByLabel('课程代码').fill('SE102')
  await page.getByLabel('课程名称', { exact: true }).fill('软件测试')
  await page.getByLabel('学期', { exact: true }).fill('2026-Fall')
  await page.getByRole('button', { name: '确认创建' }).click()
  await expect(page.getByText('课程创建成功')).toBeVisible()
  await page.getByRole('button', { name: '选课名录' }).click()
  await expect(page.getByRole('link', { name: '选课学生' })).toBeVisible()
  state.role = 'ta'
  await page.reload()
  await expect(page.getByRole('heading', { name: '课程中心' })).toBeVisible()
  await expect(page.getByRole('button', { name: '创建课程' })).toHaveCount(0)
})


test('关联课程提问向服务端提交course_id', async ({ page }) => {
  await setup(page)
  await page.goto('/questions/new')
  await page.getByLabel('标题', { exact: true }).fill('关联软件工程课程的问题')
  await page.getByLabel('问题描述', { exact: true }).fill('这是一个关联课程的问题描述，记录具体场景和已经尝试过的方法。')
  await select(page, '关联课程', 'SE101 · 软件工程（2026-Fall）')
  await page.getByRole('button', { name: '发布问题', exact: false }).click()
  await expect(page).toHaveURL(/\/questions\/question-1$/)
  await expect(page.getByRole('heading', { name: 'F15 角色权限验收问题' })).toBeVisible()
})
