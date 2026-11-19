import { Card, Descriptions, Form, Input, Button, Alert, Empty, Space, Statistic, Table, Tag, Typography } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { authApi } from '../api/auth'
import { getApiErrorMessage } from '../api/errors'
import { pointsApi } from '../api/points'
import { useAuthStore, type AuthUser } from '../stores/authStore'

function toAuthUser(user: Awaited<ReturnType<typeof authApi.me>>): AuthUser {
  return { id: user.id, email: user.email, studentId: user.student_id, staffId: user.staff_id, createdAt: user.created_at, displayName: user.nickname ?? user.student_id ?? user.staff_id ?? user.email, role: user.role }
}

export function AccountPage() {
  const setUser = useAuthStore((state) => state.setUser)
  const queryClient = useQueryClient()
  const profile = useQuery({ queryKey: ['auth', 'me'], queryFn: authApi.me })
  const points = useQuery({ queryKey: ['points', 'mine'], queryFn: pointsApi.getMine })
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  if (profile.isLoading) return <Card loading bordered={false} />
  if (profile.isError || !profile.data) return <Empty description="暂时无法加载个人资料" />
  const user = profile.data
  const saveProfile = async (values: { nickname?: string; college?: string; class_name?: string }) => {
    setBusy(true); setErrorMessage(null); setSuccessMessage(null)
    try { const updated = await authApi.updateProfile({ nickname: values.nickname || null, college: values.college || null, class_name: values.class_name || null }); setUser(toAuthUser(updated)); await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] }); setSuccessMessage('个人资料已保存') } catch (error) { setErrorMessage(getApiErrorMessage(error)) } finally { setBusy(false) }
  }
  const sendCode = async () => { setBusy(true); setErrorMessage(null); try { await authApi.sendEmailVerification(); setSuccessMessage('验证码已发送，请检查邮箱') } catch (error) { setErrorMessage(getApiErrorMessage(error)) } finally { setBusy(false) } }
  const confirmCode = async () => { setBusy(true); setErrorMessage(null); try { await authApi.confirmEmailVerification(code); setCode(''); await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] }); setSuccessMessage('邮箱验证成功') } catch (error) { setErrorMessage(getApiErrorMessage(error)) } finally { setBusy(false) } }
  return <div className="page-stack">
    <section className="page-intro"><div><Typography.Text className="eyebrow">ACCOUNT SETTINGS</Typography.Text><Typography.Title level={1}>个人资料</Typography.Title><Typography.Paragraph type="secondary">维护公开展示名、学院班级和邮箱验证状态。</Typography.Paragraph></div></section>
    {errorMessage ? <Alert type="error" showIcon message={errorMessage} /> : null}{successMessage ? <Alert type="success" showIcon message={successMessage} /> : null}
    <Card title="校园资料" bordered={false}><Form layout="vertical" initialValues={{ nickname: user.nickname ?? '', college: user.college ?? '', class_name: user.class_name ?? '' }} onFinish={saveProfile}><Form.Item label="昵称" name="nickname"><Input maxLength={30} /></Form.Item><Form.Item label="学院" name="college"><Input maxLength={64} /></Form.Item><Form.Item label="班级" name="class_name"><Input maxLength={64} /></Form.Item><Button type="primary" htmlType="submit" loading={busy}>保存资料</Button></Form></Card>
    <Card title="邮箱验证" bordered={false}><Space direction="vertical"><Descriptions column={1} items={[{ key: 'email', label: '邮箱', children: user.email }, { key: 'status', label: '状态', children: user.email_verified ? <Tag color="green">已验证</Tag> : <Tag>未验证</Tag> }]} />{!user.email_verified ? <Space wrap><Button onClick={() => void sendCode()} loading={busy}>发送验证码</Button><Input aria-label="邮箱验证码" placeholder="6 位数字验证码" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} /><Button type="primary" disabled={code.length !== 6} onClick={() => void confirmCode()} loading={busy}>确认验证</Button></Space> : null}</Space></Card>
    <Card title="我的积分" bordered={false}>{points.isLoading ? <Card loading bordered={false} /> : points.isError || !points.data ? <Empty description="暂时无法加载积分" /> : <><Statistic title="可用余额" value={points.data.balance} suffix="分" /><Table rowKey="event_id" pagination={false} dataSource={points.data.entries} columns={[{ title: '原因', dataIndex: 'reason' }, { title: '变化', dataIndex: 'delta', render: (value: number) => <Tag color={value >= 0 ? 'green' : 'red'}>{value > 0 ? `+${value}` : value}</Tag> }, { title: '时间', dataIndex: 'occurred_at', render: (value: string) => new Date(value).toLocaleString('zh-CN') }]} /></>}</Card>
  </div>
}
