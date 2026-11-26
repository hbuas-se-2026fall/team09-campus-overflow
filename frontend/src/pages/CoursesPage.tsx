import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, List, Modal, Pagination, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { coursesApi } from '../api/courses'
import { getApiErrorMessage } from '../api/errors'
import type { CourseLeaderboardEntry, CourseResponse, CourseStudentItem } from '../api/types'
import { canVerifyAnswers, useIdentity } from '../hooks/useIdentity'

function CourseRoster({ courseId }: { courseId: string }) {
  const [page, setPage] = useState(1)
  const query = useQuery({ queryKey: ['course-students', courseId, page], queryFn: () => coursesApi.students(courseId, page) })
  if (query.isError) return <Alert type="error" showIcon message={getApiErrorMessage(query.error)} />
  return <Table<CourseStudentItem> rowKey="student_id" loading={query.isPending} dataSource={query.data?.items} pagination={{ current: page, pageSize: 20, total: query.data?.total, showSizeChanger: false, onChange: setPage }} columns={[{ title: '学生', render: (_, entry) => <Link to={`/users/${entry.student_id}`}>{entry.student_name}</Link> }, { title: '选课时间', dataIndex: 'enrolled_at', render: (value: string) => new Date(value).toLocaleString('zh-CN') }]} />
}

function CourseRanking({ courseId }: { courseId: string }) {
  const query = useQuery({ queryKey: ['course-leaderboard', courseId], queryFn: () => coursesApi.leaderboard(courseId) })
  if (query.isError) return <Alert type="error" showIcon message={getApiErrorMessage(query.error)} />
  return <Table<CourseLeaderboardEntry> rowKey="user_id" loading={query.isPending} dataSource={query.data?.entries} scroll={{ x: 460 }} pagination={false} columns={[{ title: '排名', dataIndex: 'rank' }, { title: '用户', render: (_, entry) => <Link to={`/users/${entry.user_id}`}>{entry.display_name}</Link> }, { title: '采纳数', dataIndex: 'accepted_count' }, { title: '净票数', dataIndex: 'net_votes' }, { title: '回答数', dataIndex: 'answer_count' }]} />
}

export function CoursesPage() {
  const identity = useIdentity()
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [semester, setSemester] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<{ course: CourseResponse; mode: 'students' | 'leaderboard' } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [enrolled, setEnrolled] = useState<string[]>([])
  const query = useQuery({ queryKey: ['courses', 'list', page, semester], queryFn: () => coursesApi.list({ page, page_size: 10, semester: semester.trim() || undefined }) })
  const create = async (values: { code: string; name: string; semester: string }) => {
    setBusy(true); setError(null); setSuccess(null)
    try {
      await coursesApi.create({ code: values.code.trim(), name: values.name.trim(), semester: values.semester.trim() })
      setCreateOpen(false); setSuccess('课程创建成功')
      await client.invalidateQueries({ queryKey: ['courses'] })
    } catch (cause) { setError(getApiErrorMessage(cause)) } finally { setBusy(false) }
  }
  const enroll = async (id: string) => {
    setBusy(true); setError(null); setSuccess(null)
    try { await coursesApi.enroll(id); setEnrolled((current) => [...current, id]); setSuccess('选课成功，现在可以关联该课程提问') } catch (cause) { setError(getApiErrorMessage(cause)) } finally { setBusy(false) }
  }
  const role = identity.data?.role
  return <div className="page-stack">
    <section className="page-intro"><div><Typography.Text className="eyebrow">CAMPUS COURSES</Typography.Text><Typography.Title level={1}>课程中心</Typography.Title><Typography.Paragraph type="secondary">发现课程、选课与查看课程贡献榜。</Typography.Paragraph></div>{role === 'teacher' || role === 'admin' ? <Button type="primary" onClick={() => setCreateOpen(true)}>创建课程</Button> : null}</section>
    <Input aria-label="按学期筛选" allowClear placeholder="输入学期筛选，例如 2026-Fall" value={semester} onChange={(event) => { setSemester(event.target.value); setPage(1) }} />
    {error ? <Alert message={error} type="error" showIcon /> : null}{success ? <Alert message={success} type="success" showIcon /> : null}
    <Card variant="borderless">{query.isError ? <Alert type="error" showIcon message={getApiErrorMessage(query.error)} action={<Button onClick={() => void query.refetch()}>重试</Button>} /> : <List loading={query.isPending} dataSource={query.data?.items} locale={{ emptyText: '暂无符合条件的课程' }} renderItem={(course) => <List.Item><Space direction="vertical" style={{ width: '100%' }}><Space wrap><Typography.Title level={4}>{course.name}</Typography.Title><Tag>{course.code}</Tag><Tag>{course.semester}</Tag></Space><Typography.Text type="secondary">任课教师：{course.teacher_name}</Typography.Text><Space wrap>
      <Link to={`/questions?course_id=${course.id}`}>课程问题</Link>
      <Button onClick={() => setSelected({ course, mode: 'leaderboard' })}>课程贡献榜</Button>
      {canVerifyAnswers(role) ? <Button onClick={() => setSelected({ course, mode: 'students' })}>选课名录</Button> : null}
      {role === 'student' ? <Button loading={busy} disabled={enrolled.includes(course.id)} onClick={() => void enroll(course.id)}>{enrolled.includes(course.id) ? '本次已选课' : '选修此课程'}</Button> : null}
    </Space></Space></List.Item>} />}</Card>
    {query.data ? <Pagination current={page} pageSize={10} total={query.data.total} showSizeChanger={false} onChange={setPage} /> : null}
    <Modal title="创建课程" open={createOpen} footer={null} onCancel={() => { if (!busy) setCreateOpen(false) }} destroyOnHidden>
      <Form layout="vertical" onFinish={create} preserve={false}>
        <Form.Item label="课程代码" name="code" rules={[{ required: true, min: 2, max: 32, whitespace: true }]}><Input maxLength={32} placeholder="例如 SE101" /></Form.Item>
        <Form.Item label="课程名称" name="name" rules={[{ required: true, min: 2, max: 100, whitespace: true }]}><Input maxLength={100} /></Form.Item>
        <Form.Item label="学期" name="semester" rules={[{ required: true, min: 2, max: 32, whitespace: true }]}><Input maxLength={32} placeholder="例如 2026-Fall" /></Form.Item>
        <Button type="primary" htmlType="submit" loading={busy}>确认创建</Button>
      </Form>
    </Modal>
    <Modal title={`${selected?.course.name ?? ''} · ${selected?.mode === 'students' ? '选课名录' : '课程贡献榜'}`} open={Boolean(selected)} footer={null} width={720} onCancel={() => setSelected(null)} destroyOnHidden>
      {selected?.mode === 'students' && canVerifyAnswers(role) ? <CourseRoster key={selected.course.id} courseId={selected.course.id} /> : selected?.mode === 'leaderboard' ? <CourseRanking key={selected.course.id} courseId={selected.course.id} /> : null}
    </Modal>
  </div>
}
