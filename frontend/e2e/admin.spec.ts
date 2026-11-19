import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const serverUser = {
  id: 'user-1', email: 'student@example.com', role: 'student',
  student_id: '20260001', staff_id: null, created_at: '2026-10-01T00:00:00Z',
}

async function saveSession(page: Page, role = 'student') {
  await page.addInitScript((savedRole) => {
    localStorage.setItem('campus-overflow-auth', JSON.stringify({
      version: 0,
      state: {
        accessToken: 'test-access', refreshToken: 'test-refresh',
        user: { id: 'user-1', email: 'student@example.com', role: savedRole, displayName: '测试用户' },
      },
    }))
  }, role)
}

async function selectFilter(page: Page, label: string, option: string) {
  await page.locator('.ant-select').filter({ has: page.getByRole('combobox', { name: label }) }).click()
  await page.locator('.ant-select-dropdown:visible').getByText(option, { exact: true }).click()
}

test('正式后台要求先登录', async ({ page }) => {
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByLabel('学号 / 工号')).toBeVisible()
})

for (const persistedRole of ['student', 'teacher', 'admin']) {
  test(`正式入口拒绝本地 ${persistedRole} 角色，并核验真实服务端身份`, async ({ page }) => {
    await saveSession(page, persistedRole)
    let identityRequests = 0
    await page.route('**/api/v1/auth/me', async (route) => {
      identityRequests++
      expect(route.request().headers().authorization).toBe('Bearer test-access')
      await route.fulfill({ json: serverUser })
    })
    await page.goto('/admin')
    await expect(page.getByText('管理后台尚未开放', { exact: true })).toBeVisible()
    await expect(page.getByText(/当前账号：student@example.com/)).toBeVisible()
    expect(identityRequests).toBeGreaterThan(0)
    await expect(page.getByRole('tab', { name: '用户管理' })).toHaveCount(0)
  })
}

test('身份核验失败可重试', async ({ page }) => {
  await saveSession(page)
  let fail = true
  await page.route('**/api/v1/auth/me', async (route) => {
    await route.fulfill(fail ? { status: 503, json: { detail: '服务暂时不可用' } } : { json: serverUser })
  })
  await page.goto('/admin')
  await expect(page.getByText('无法核验身份', { exact: true })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: '重新核验' }).click()
  await expect(page.getByText('管理后台尚未开放', { exact: true })).toBeVisible()
})

test('生产环境不暴露后台演示', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'production', '检查实际生产产物')
  await page.route(/\/api\/v1\/questions(?:\?.*)?$/, (route) => route.fulfill({
    json: { items: [], total: 0, page: 1, page_size: 10, total_pages: 0 },
  }))
  await page.goto('/admin/preview')
  await expect(page).toHaveURL(/\/questions$/)
  await expect(page.getByRole('link', { name: '后台演示' })).toHaveCount(0)
  await expect(page.getByText('开发演示 · 使用虚构数据')).toHaveCount(0)
})

test.describe('开发后台演示', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'development', '演示仅在专用开发模式开放')
    // 演示必须完全在本地运行：任何 API 访问都算失败。
    await page.route(/^https?:\/\/[^/]+\/api\//, (route) => { throw new Error(`演示意外请求了业务接口：${route.request().url()}`) })
    await page.goto('/admin/preview')
    await expect(page.getByText('开发演示 · 使用虚构数据')).toBeVisible()
  })

  test('问题可分页、搜索、查看详情、确认关闭并同步统计', async ({ page }) => {
    await page.getByRole('tab', { name: '问题管理' }).click()
    await expect(page.getByText('匹配 12 个演示问题')).toBeVisible()
    await page.getByTitle('2', { exact: true }).click()
    await expect(page.getByRole('button', { name: 'Git 合并冲突后如何保留两边改动？' })).toBeVisible()
    await page.getByRole('textbox', { name: '搜索管理问题' }).fill('React')
    await expect(page.getByText('匹配 1 个演示问题')).toBeVisible()
    await page.getByRole('button', { name: /^详\s*情$/ }).click()
    const drawer = page.getByRole('dialog', { name: '问题详情（演示）' })
    await expect(drawer.getByText('刷新页面后，如何恢复登录状态并处理令牌过期？')).toBeVisible()
    await drawer.getByRole('button', { name: '关闭此问题' }).click()
    await page.getByRole('button', { name: /^取\s*消$/ }).click()
    await expect(drawer.getByRole('button', { name: '关闭此问题' })).toBeEnabled()
    await drawer.getByRole('button', { name: '关闭此问题' }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(drawer.getByRole('button', { name: '关闭此问题' })).toBeDisabled()
    await expect(drawer.getByText('已关闭', { exact: true })).toBeVisible()
    await drawer.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByRole('tab', { name: '社区概览' }).click()
    await expect(page.locator('.ant-statistic').filter({ hasText: '已关闭问题' }).locator('.ant-statistic-content')).toHaveText('3')
    await page.getByRole('button', { name: '重置演示数据' }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(page.locator('.ant-statistic').filter({ hasText: '已关闭问题' }).locator('.ant-statistic-content')).toHaveText('2')
  })

  test('问题筛选与空状态可恢复，刷新还原演示样本', async ({ page }) => {
    await page.getByRole('tab', { name: '问题管理' }).click()
    await selectFilter(page, '问题状态筛选', '已关闭')
    await expect(page.getByText('匹配 2 个演示问题')).toBeVisible()
    await page.getByRole('textbox', { name: '搜索管理问题' }).fill('不存在的提问')
    await expect(page.getByText('没有匹配的问题，请调整筛选条件')).toBeVisible()
    await page.getByRole('button', { name: '清除问题筛选' }).click()
    await page.getByRole('textbox', { name: '搜索管理问题' }).fill('React')
    await page.getByRole('button', { name: /^关\s*闭$/ }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(page.getByRole('button', { name: /^关\s*闭$/ })).toBeDisabled()
    await page.reload()
    await page.getByRole('tab', { name: '问题管理' }).click()
    await page.getByRole('textbox', { name: '搜索管理问题' }).fill('React')
    await expect(page.getByRole('button', { name: /^关\s*闭$/ })).toBeEnabled()
  })

  test('用户资料、角色筛选、停用和恢复账号', async ({ page }) => {
    await page.getByRole('tab', { name: '用户管理' }).click()
    await selectFilter(page, '用户角色筛选', '教师')
    await expect(page.getByText('匹配 2 个演示用户')).toBeVisible()
    await page.getByRole('button', { name: '清除用户筛选' }).click()
    await page.getByRole('textbox', { name: '搜索管理用户' }).fill('20260001')
    await page.getByRole('button', { name: /^资\s*料$/ }).click()
    const drawer = page.getByRole('dialog', { name: '用户资料（演示）' })
    await expect(drawer.getByText('lin@example.com')).toBeVisible()
    await drawer.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByRole('button', { name: /^停\s*用$/ }).click()
    await page.getByRole('button', { name: /^取\s*消$/ }).click()
    await expect(page.getByRole('button', { name: /^停\s*用$/ })).toBeEnabled()
    await page.getByRole('button', { name: /^停\s*用$/ }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(page.getByRole('cell', { name: '已停用', exact: true })).toBeVisible()
    await page.getByRole('button', { name: /^恢\s*复$/ }).click()
    await page.getByRole('button', { name: /^确\s*认$/ }).click()
    await expect(page.getByRole('cell', { name: '正常', exact: true })).toBeVisible()
    await selectFilter(page, '用户状态筛选', '已停用')
    await expect(page.getByText('没有匹配的用户，请调整筛选条件')).toBeVisible()
  })

  test('桌面与手机页面可用，横向滚动局限于表格', async ({ page }, testInfo) => {
    await page.screenshot({ path: testInfo.outputPath('admin-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('tab', { name: '问题管理' }).click()
    await expect(page.getByRole('textbox', { name: '搜索管理问题' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('admin-mobile.png'), fullPage: true })
  })
})
