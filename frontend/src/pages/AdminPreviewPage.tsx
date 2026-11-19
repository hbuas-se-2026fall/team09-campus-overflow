import { useState } from 'react'
import { SearchOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, Col, Descriptions, Drawer, Empty, Input, Modal,
  Row, Select, Space, Statistic, Table, Tabs, Tag, Typography, message,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { createPreviewData } from '../admin/previewData'
import type { PreviewQuestion, PreviewUser } from '../admin/previewData'
import './AdminPreviewPage.css'

type Confirmation = { kind: 'close-question' | 'toggle-user'; id: string } | { kind: 'reset' }

export function AdminPreviewPage() {
  const [data, setData] = useState(createPreviewData)
  const [tab, setTab] = useState('overview')
  const [questionSearch, setQuestionSearch] = useState('')
  const [questionStatus, setQuestionStatus] = useState('all')
  const [questionPage, setQuestionPage] = useState(1)
  const [userSearch, setUserSearch] = useState('')
  const [userRole, setUserRole] = useState('all')
  const [userStatus, setUserStatus] = useState('all')
  const [userPage, setUserPage] = useState(1)
  const [questionId, setQuestionId] = useState<string | null>(null)
  const [userId, setUserId] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [messageApi, messageHolder] = message.useMessage()

  const authorEmail = (id: string) => data.users.find((user) => user.id === id)?.email ?? id
  const selectedQuestion = data.questions.find((question) => question.id === questionId)
  const selectedUser = data.users.find((user) => user.id === userId)
  const targetQuestion = confirmation?.kind === 'close-question'
    ? data.questions.find((question) => question.id === confirmation.id) : undefined
  const targetUser = confirmation?.kind === 'toggle-user'
    ? data.users.find((user) => user.id === confirmation.id) : undefined
  const filteredQuestions = data.questions.filter((question) => {
    const keyword = questionSearch.trim().toLowerCase()
    return (questionStatus === 'all' || question.status === questionStatus)
      && [question.title, authorEmail(question.authorId), ...question.tags].some((value) => value.toLowerCase().includes(keyword))
  })
  const filteredUsers = data.users.filter((user) => (
    (userRole === 'all' || user.role === userRole)
    && (userStatus === 'all' || user.status === userStatus)
    && `${user.email} ${user.identity}`.toLowerCase().includes(userSearch.trim().toLowerCase())
  ))
  const closedCount = data.questions.filter((question) => question.status === 'closed').length
  const disabledCount = data.users.filter((user) => user.status === 'disabled').length
  const tags = [...new Set(data.questions.flatMap((question) => question.tags))].sort()

  const confirmAction = () => {
    if (confirmation?.kind === 'reset') {
      setData(createPreviewData())
      setQuestionSearch(''); setQuestionStatus('all'); setQuestionPage(1)
      setUserSearch(''); setUserRole('all'); setUserStatus('all'); setUserPage(1)
      setQuestionId(null); setUserId(null)
      void messageApi.success('演示数据已重置')
    } else if (targetQuestion) {
      setData((current) => ({ ...current, questions: current.questions.map((question) => (
        question.id === targetQuestion.id ? { ...question, status: 'closed' } : question
      )) }))
      setQuestionPage(1)
      void messageApi.success('已在演示中关闭问题')
    } else if (targetUser) {
      setData((current) => ({ ...current, users: current.users.map((user) => (
        user.id === targetUser.id ? { ...user, status: user.status === 'active' ? 'disabled' : 'active' } : user
      )) }))
      setUserPage(1)
      void messageApi.success(targetUser.status === 'active' ? '已在演示中停用账号' : '已在演示中恢复账号')
    }
    setConfirmation(null)
  }

  const questionColumns: TableColumnsType<PreviewQuestion> = [
    { title: '问题', dataIndex: 'title', width: 280, render: (_, question) => (
      <div className="admin-question-cell">
        <Button type="link" className="admin-title-button" onClick={() => setQuestionId(question.id)}>{question.title}</Button>
        <Space size={[0, 4]} wrap>{question.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space>
      </div>
    ) },
    { title: '作者', dataIndex: 'authorId', width: 180, render: authorEmail },
    { title: '状态', dataIndex: 'status', width: 90, render: (status) => <Tag color={status === 'open' ? 'green' : 'default'}>{status === 'open' ? '开放' : '已关闭'}</Tag> },
    { title: '发布时间', dataIndex: 'createdAt', width: 110 },
    { title: '操作', key: 'actions', width: 150, render: (_, question) => <Space>
      <Button size="small" onClick={() => setQuestionId(question.id)}>详情</Button>
      <Button size="small" danger disabled={question.status === 'closed'} onClick={() => setConfirmation({ kind: 'close-question', id: question.id })}>关闭</Button>
    </Space> },
  ]
  const userColumns: TableColumnsType<PreviewUser> = [
    { title: '账号', dataIndex: 'email', width: 210 },
    { title: '学号 / 工号', dataIndex: 'identity', width: 130 },
    { title: '角色', dataIndex: 'role', width: 80, render: (role) => role === 'teacher' ? '教师' : '学生' },
    { title: '状态', dataIndex: 'status', width: 90, render: (status) => <Tag color={status === 'active' ? 'green' : 'red'}>{status === 'active' ? '正常' : '已停用'}</Tag> },
    { title: '注册日期', dataIndex: 'createdAt', width: 110 },
    { title: '操作', key: 'actions', width: 160, render: (_, user) => <Space>
      <Button size="small" onClick={() => setUserId(user.id)}>资料</Button>
      <Button size="small" danger={user.status === 'active'} onClick={() => setConfirmation({ kind: 'toggle-user', id: user.id })}>{user.status === 'active' ? '停用' : '恢复'}</Button>
    </Space> },
  ]

  return (
    <div className="page-stack admin-page">
      {messageHolder}
      <section className="page-intro">
        <div>
          <Typography.Text className="eyebrow">COMMUNITY ADMINISTRATION</Typography.Text>
          <Typography.Title level={1}>社区管理</Typography.Title>
          <Typography.Paragraph type="secondary">查看社区概况，维护提问秩序与账号状态。</Typography.Paragraph>
        </div>
        <Button onClick={() => setConfirmation({ kind: 'reset' })}>重置演示数据</Button>
      </section>
      <Alert type="warning" showIcon message="开发演示 · 使用虚构数据"
        description="当前后台尚未接入管理接口。所有操作仅影响本页演示数据，刷新页面即可还原。" />
      <Card className="admin-workspace">
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'overview', label: '社区概览', children: <div className="page-stack">
            <Typography.Text type="secondary">以下统计仅针对演示样本。</Typography.Text>
            <Row gutter={[16, 16]}>
              {[
                { title: '问题总数', value: data.questions.length },
                { title: '开放问题', value: data.questions.length - closedCount },
                { title: '已关闭问题', value: closedCount },
                { title: '用户总数', value: data.users.length },
                { title: '正常账号', value: data.users.length - disabledCount },
                { title: '已停用账号', value: disabledCount },
              ].map((stat) => <Col xs={12} md={8} key={stat.title}><Card size="small"><Statistic title={stat.title} value={stat.value} /></Card></Col>)}
            </Row>
            <div>
              <Typography.Title level={4}>管理工作台</Typography.Title>
              <Space wrap>
                <Button type="primary" onClick={() => setTab('questions')}>管理问题</Button>
                <Button onClick={() => setTab('users')}>管理用户</Button>
              </Space>
            </div>
            <div>
              <Typography.Title level={4}>样本标签目录</Typography.Title>
              <Space size={[0, 8]} wrap>{tags.map((tag) => <Tag color="blue" key={tag}>{tag}</Tag>)}</Space>
            </div>
          </div> },
          { key: 'questions', label: '问题管理', children: <div className="page-stack">
            <div className="admin-filters">
              <Input aria-label="搜索管理问题" allowClear prefix={<SearchOutlined />} placeholder="搜索标题、作者或标签"
                value={questionSearch} onChange={(event) => { setQuestionSearch(event.target.value); setQuestionPage(1) }} />
              <Select aria-label="问题状态筛选" value={questionStatus} onChange={(value) => { setQuestionStatus(value); setQuestionPage(1) }} options={[
                { value: 'all', label: '全部状态' }, { value: 'open', label: '开放' }, { value: 'closed', label: '已关闭' },
              ]} />
              <Button onClick={() => { setQuestionSearch(''); setQuestionStatus('all'); setQuestionPage(1) }}>清除问题筛选</Button>
            </div>
            <Typography.Text type="secondary">匹配 {filteredQuestions.length} 个演示问题</Typography.Text>
            <Table rowKey="id" columns={questionColumns} dataSource={filteredQuestions} scroll={{ x: 810 }}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的问题，请调整筛选条件" /> }}
              pagination={{ current: questionPage, pageSize: 5, total: filteredQuestions.length, showSizeChanger: false, onChange: setQuestionPage }} />
          </div> },
          { key: 'users', label: '用户管理', children: <div className="page-stack">
            <div className="admin-filters">
              <Input aria-label="搜索管理用户" allowClear prefix={<SearchOutlined />} placeholder="搜索邮箱、学号或工号"
                value={userSearch} onChange={(event) => { setUserSearch(event.target.value); setUserPage(1) }} />
              <Select aria-label="用户角色筛选" value={userRole} onChange={(value) => { setUserRole(value); setUserPage(1) }} options={[
                { value: 'all', label: '全部角色' }, { value: 'student', label: '学生' }, { value: 'teacher', label: '教师' },
              ]} />
              <Select aria-label="用户状态筛选" value={userStatus} onChange={(value) => { setUserStatus(value); setUserPage(1) }} options={[
                { value: 'all', label: '全部账号' }, { value: 'active', label: '正常' }, { value: 'disabled', label: '已停用' },
              ]} />
              <Button onClick={() => { setUserSearch(''); setUserRole('all'); setUserStatus('all'); setUserPage(1) }}>清除用户筛选</Button>
            </div>
            <Typography.Text type="secondary">匹配 {filteredUsers.length} 个演示用户</Typography.Text>
            <Table rowKey="id" columns={userColumns} dataSource={filteredUsers} scroll={{ x: 780 }}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的用户，请调整筛选条件" /> }}
              pagination={{ current: userPage, pageSize: 5, total: filteredUsers.length, showSizeChanger: false, onChange: setUserPage }} />
          </div> },
        ]} />
      </Card>
      <Drawer title="问题详情（演示）" open={Boolean(selectedQuestion)} onClose={() => setQuestionId(null)} width="min(540px, 100vw)">
        {selectedQuestion && <Space direction="vertical" size="large" className="admin-drawer-content">
          <Typography.Title level={3}>{selectedQuestion.title}</Typography.Title>
          <Descriptions column={1} items={[
            { key: 'author', label: '作者', children: authorEmail(selectedQuestion.authorId) },
            { key: 'status', label: '状态', children: selectedQuestion.status === 'open' ? '开放' : '已关闭' },
            { key: 'date', label: '发布时间', children: selectedQuestion.createdAt },
            { key: 'tags', label: '标签', children: selectedQuestion.tags.join('、') },
          ]} />
          <Typography.Paragraph className="admin-body">{selectedQuestion.body}</Typography.Paragraph>
          <Button danger disabled={selectedQuestion.status === 'closed'} onClick={() => setConfirmation({ kind: 'close-question', id: selectedQuestion.id })}>关闭此问题</Button>
        </Space>}
      </Drawer>
      <Drawer title="用户资料（演示）" open={Boolean(selectedUser)} onClose={() => setUserId(null)} width="min(480px, 100vw)">
        {selectedUser && <Descriptions column={1} items={[
          { key: 'email', label: '邮箱', children: selectedUser.email },
          { key: 'identity', label: '学号 / 工号', children: selectedUser.identity },
          { key: 'role', label: '角色', children: selectedUser.role === 'teacher' ? '教师' : '学生' },
          { key: 'status', label: '账号状态', children: selectedUser.status === 'active' ? '正常' : '已停用' },
          { key: 'created', label: '注册日期', children: selectedUser.createdAt },
        ]} />}
      </Drawer>
      <Modal open={Boolean(confirmation)} onCancel={() => setConfirmation(null)} onOk={confirmAction}
        title={confirmation?.kind === 'reset' ? '重置演示数据' : targetQuestion ? '关闭演示问题' : targetUser?.status === 'active' ? '停用演示账号' : '恢复演示账号'}
        okText="确认" cancelText="取消" okButtonProps={{ danger: Boolean(targetQuestion) || targetUser?.status === 'active' }}>
        {confirmation?.kind === 'reset' ? <p>将还原初始演示样本，并清除本页所有操作与筛选。</p>
          : targetQuestion ? <p>确认关闭「{targetQuestion.title}」？此操作只改变演示数据，不会关闭真实问题。</p>
            : <p>确认{targetUser?.status === 'active' ? '停用' : '恢复'} {targetUser?.email}？此操作不影响真实账号。</p>}
      </Modal>
    </div>
  )
}
