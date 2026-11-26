import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Descriptions, Input, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi } from '../api/admin'
import { getApiErrorMessage } from '../api/errors'
import type { AdminUserItem, ReportAction, ReportResponse, ReportStatus, ReportTarget, UserRole } from '../api/types'
import { roleNames, roleOptions } from '../hooks/useIdentity'

const reportStatusNames = { pending: '待处理', resolved: '已处理', dismissed: '已驳回', all: '全部状态' }
const actionNames = { dismiss: '驳回举报', close_question: '关闭问题', soft_delete: '删除内容' }

function UsersPanel({ currentUserId }: { currentUserId: string }) {
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [role, setRole] = useState<UserRole>()
  const [target, setTarget] = useState<AdminUserItem | null>(null)
  const [newRole, setNewRole] = useState<UserRole>('student')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const users = useQuery({ queryKey: ['admin-users', currentUserId, page, role], queryFn: () => adminApi.users({ page, page_size: 20, role }) })
  const save = async () => {
    if (!target || target.id === currentUserId) return
    setBusy(true); setError(null)
    try {
      await adminApi.updateRole(target.id, newRole)
      setTarget(null)
      await client.invalidateQueries({ queryKey: ['admin-users'] })
      await client.invalidateQueries({ queryKey: ['profile', target.id] })
    } catch (cause) {
      setError(getApiErrorMessage(cause)); void client.invalidateQueries({ queryKey: ['identity'] })
    } finally { setBusy(false) }
  }
  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Select allowClear aria-label="管理用户角色筛选" placeholder="全部角色" value={role} options={roleOptions} style={{ width: 180 }} onChange={(value) => { setRole(value); setPage(1) }} />
    {error ? <Alert showIcon type="error" message={error} /> : null}
    {users.isError ? <Alert type="error" showIcon message={getApiErrorMessage(users.error)} action={<Button onClick={() => void users.refetch()}>重试</Button>} /> : <Table<AdminUserItem> rowKey="id" loading={users.isPending} dataSource={users.data?.items} scroll={{ x: 760 }} pagination={{ current: page, pageSize: 20, total: users.data?.total, showSizeChanger: false, onChange: setPage }} columns={[
      { title: '用户', render: (_, user) => <Space direction="vertical" size={0}><Link to={`/users/${user.id}`}>{user.display_name}</Link><Typography.Text type="secondary">{user.email}</Typography.Text></Space> },
      { title: '角色', dataIndex: 'role', render: (value: UserRole) => <Tag>{roleNames[value]}</Tag> },
      { title: '学院 / 班级', render: (_, user) => `${user.college ?? '未设置'} / ${user.class_name ?? '未设置'}` },
      { title: '邮箱', dataIndex: 'email_verified', render: (verified: boolean) => verified ? '已验证' : '未验证' },
      { title: '操作', render: (_, user) => <Button disabled={user.id === currentUserId} onClick={() => { setTarget(user); setNewRole(user.role); setError(null) }}>修改角色</Button> },
    ]} />}
    <Modal title="修改用户角色" open={Boolean(target)} onCancel={() => { if (!busy) setTarget(null) }} onOk={() => void save()} confirmLoading={busy} okText="确认修改" okButtonProps={{ disabled: newRole === target?.role }}>
      <Alert type="info" message="请确认目标账号与新角色" showIcon />{error ? <Alert type="error" message={error} showIcon /> : null}<Typography.Paragraph>为 {target?.display_name} 修改角色。新权限将在下一次请求时生效，原学号或工号继续用于登录。</Typography.Paragraph>
      <Select aria-label="新角色" value={newRole} onChange={setNewRole} options={roleOptions} style={{ width: '100%' }} />
    </Modal>
  </Space>
}

function ReportsPanel({ currentUserId }: { currentUserId: string }) {
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<ReportStatus | 'all'>('pending')
  const [targetType, setTargetType] = useState<ReportTarget>()
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [action, setAction] = useState<ReportAction>('dismiss')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const reports = useQuery({ queryKey: ['admin-reports', currentUserId, page, status, targetType], queryFn: () => adminApi.reports({ page, page_size: 20, status, target_type: targetType }) })
  const resolve = async () => {
    if (!report) return
    setBusy(true); setError(null)
    try {
      await adminApi.resolveReport(report.id, { action, note: note.trim() || undefined })
      setReport(null)
      await client.invalidateQueries({ queryKey: ['admin-reports'] })
      await client.invalidateQueries({ queryKey: ['questions'] })
    } catch (cause) { setError(getApiErrorMessage(cause)); void client.invalidateQueries({ queryKey: ['identity'] }) } finally { setBusy(false) }
  }
  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Space wrap>
      <Select aria-label="举报状态筛选" value={status} options={Object.entries(reportStatusNames).map(([value, label]) => ({ value, label }))} onChange={(value) => { setStatus(value); setPage(1) }} />
      <Select allowClear aria-label="举报内容类型筛选" placeholder="全部类型" value={targetType} options={[{ value: 'question', label: '问题' }, { value: 'answer', label: '回答' }]} onChange={(value) => { setTargetType(value); setPage(1) }} style={{ minWidth: 130 }} />
    </Space>
    {error ? <Alert type="error" showIcon message={error} /> : null}
    {reports.isError ? <Alert type="error" showIcon message={getApiErrorMessage(reports.error)} action={<Button onClick={() => void reports.refetch()}>重试</Button>} /> : <Table<ReportResponse> rowKey="id" loading={reports.isPending} dataSource={reports.data?.items} scroll={{ x: 720 }} pagination={{ current: page, pageSize: 20, total: reports.data?.total, showSizeChanger: false, onChange: setPage }} columns={[
      { title: '举报内容', render: (_, item) => <Space direction="vertical" size={0}><Tag>{item.target_type === 'question' ? '问题' : '回答'}</Tag>{item.target_type === 'question' ? <Link to={`/questions/${item.target_id}`}>查看问题</Link> : <Typography.Text copyable>{item.target_id}</Typography.Text>}</Space> },
      { title: '举报人 / 原因', render: (_, item) => <Space direction="vertical" size={0}><Link to={`/users/${item.reporter_id}`}>{item.reporter_name}</Link><Typography.Text>{item.reason}</Typography.Text></Space> },
      { title: '处理结果', render: (_, item) => <Space direction="vertical" size={0}><Tag>{reportStatusNames[item.status]}</Tag>{item.resolution_action ? actionNames[item.resolution_action] : null}{item.resolution_note ? <Typography.Text>{item.resolution_note}</Typography.Text> : null}{item.resolved_by_name}</Space> },
      { title: '提交时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString('zh-CN') },
      { title: '操作', render: (_, item) => <Button disabled={item.status !== 'pending'} onClick={() => { setReport(item); setAction('dismiss'); setNote(''); setError(null) }}>审核举报</Button> },
    ]} />}
    <Modal title="审核举报" open={Boolean(report)} onCancel={() => { if (!busy) setReport(null) }} onOk={() => void resolve()} confirmLoading={busy} okText="确认处理">
      {error ? <Alert type="error" message={error} showIcon /> : null}<Descriptions column={1} items={[{ key: 'reason', label: '举报原因', children: report?.reason }]} />
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select aria-label="举报处理动作" value={action} onChange={setAction} style={{ width: '100%' }} options={Object.entries(actionNames).filter(([value]) => value !== 'close_question' || report?.target_type === 'question').map(([value, label]) => ({ value, label }))} />
        <Typography.Text type="secondary">确认后会立即执行所选动作。已有采纳答案等状态冲突会由服务端拒绝。</Typography.Text>
        <Input.TextArea aria-label="处理说明" value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} showCount placeholder="处理说明（可选）" />
      </Space>
    </Modal>
  </Space>
}

export function AdminConsole({ currentUserId }: { currentUserId: string }) {
  return <div className="page-stack">
    <section className="page-intro"><div><Typography.Text className="eyebrow">ADMINISTRATION</Typography.Text><Typography.Title level={1}>管理后台</Typography.Title><Typography.Paragraph type="secondary">管理用户角色与审核社区举报。</Typography.Paragraph></div></section>
    <Card variant="borderless"><Tabs items={[{ key: 'users', label: '用户管理', children: <UsersPanel currentUserId={currentUserId} /> }, { key: 'reports', label: '举报审核', children: <ReportsPanel currentUserId={currentUserId} /> }]} /></Card>
  </div>
}
