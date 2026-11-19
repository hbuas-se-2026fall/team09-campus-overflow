// 仅供开发演示的视图模型，不代表后端 API 契约。
export type PreviewUser = {
  id: string
  email: string
  identity: string
  role: 'student' | 'teacher'
  status: 'active' | 'disabled'
  createdAt: string
}

export type PreviewQuestion = {
  id: string
  title: string
  body: string
  authorId: string
  tags: string[]
  status: 'open' | 'closed'
  createdAt: string
}

export function createPreviewData(): { users: PreviewUser[]; questions: PreviewQuestion[] } {
  const users: PreviewUser[] = [
    { id: 'demo-user-1', email: 'lin@example.com', identity: '20260001', role: 'student', status: 'active', createdAt: '2026-10-01' },
    { id: 'demo-user-2', email: 'chen@example.com', identity: '20260002', role: 'student', status: 'active', createdAt: '2026-10-02' },
    { id: 'demo-user-3', email: 'zhou@example.com', identity: 'T2026001', role: 'teacher', status: 'active', createdAt: '2026-10-03' },
    { id: 'demo-user-4', email: 'li@example.com', identity: '20260004', role: 'student', status: 'disabled', createdAt: '2026-10-04' },
    { id: 'demo-user-5', email: 'wang@example.com', identity: 'T2026002', role: 'teacher', status: 'active', createdAt: '2026-10-05' },
    { id: 'demo-user-6', email: 'xu@example.com', identity: '20260006', role: 'student', status: 'active', createdAt: '2026-10-06' },
    { id: 'demo-user-7', email: 'sun@example.com', identity: '20260007', role: 'student', status: 'active', createdAt: '2026-10-07' },
  ]
  const topics = [
    { title: 'React 登录状态应该如何管理？', tags: ['React', '前端'], body: '刷新页面后，如何恢复登录状态并处理令牌过期？' },
    { title: '数据库事务的隔离级别如何选择？', tags: ['数据库', '课程讨论'], body: '并发更新数据时，应该如何权衡一致性与性能？' },
    { title: '软件工程实验报告需要哪些证据？', tags: ['软件工程', '课程讨论'], body: '想了解实验报告中如何整理提交记录与评审证据。' },
    { title: '重复发布的课程讨论', tags: ['课程讨论'], body: '这是一个已关闭的重复问题样本。' },
    { title: 'TypeScript 联合类型如何缩小？', tags: ['TypeScript', '前端'], body: '使用联合类型时，如何安全访问不同分支的字段？' },
    { title: 'FastAPI 接口返回 422 怎么排查？', tags: ['Python', '后端'], body: '请求参数看起来正确，但接口校验失败，应该从哪里排查？' },
    { title: 'Git 合并冲突后如何保留两边改动？', tags: ['Git', '软件工程'], body: '两个人修改同一段代码，如何解决冲突并验证结果？' },
    { title: '如何设计稳定的浏览器测试？', tags: ['测试', '前端'], body: '测试中遇到异步加载和页面跳转，怎样避免不稳定断言？' },
    { title: '校园问答社区标签使用约定', tags: ['社区规范'], body: '发布问题时，请优先选择已有标签并清晰描述问题。' },
    { title: '缓存与数据库数据如何保持一致？', tags: ['后端', '数据库'], body: '更新数据时，如何处理缓存失效与并发读取？' },
    { title: '已解决的开发环境求助', tags: ['工具'], body: '环境问题已解决，此讨论作为关闭状态演示。' },
    { title: '小组项目怎样安排代码评审？', tags: ['软件工程'], body: '希望让代码评审有可执行的反馈，并留下真实记录。' },
  ]
  return {
    users,
    questions: topics.map((topic, index) => ({
      ...topic,
      id: `demo-question-${index + 1}`,
      authorId: users[index % users.length].id,
      status: index === 3 || index === 10 ? 'closed' : 'open',
      createdAt: `2026-11-${String(5 - Math.floor(index / 3)).padStart(2, '0')}`,
    })),
  }
}
