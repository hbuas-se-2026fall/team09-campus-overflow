import { CheckOutlined } from '@ant-design/icons'
import { Button, Card, Empty, List, Pagination, Select, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { notificationsApi } from '../api/notifications'
import { getApiErrorMessage } from '../api/errors'

function notificationText(type: string) {
  if (type === 'answer_posted') return '回答了你的问题'
  if (type === 'answer_accepted') return '采纳了你的回答'
  if (type === 'comment_created') return '评论了你的内容'
  return '与你产生了互动'
}

export function NotificationsPage() {
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['notifications', page, unreadOnly], queryFn: () => notificationsApi.list({ page, page_size: 20, unread_only: unreadOnly }) })
  const markRead = async (id: string) => { try { await notificationsApi.markRead(id); await client.invalidateQueries({ queryKey: ['notifications'] }) } catch (error) { setErrorMessage(getApiErrorMessage(error)) } }
  const markAll = async () => { try { await notificationsApi.markAllRead(); await client.invalidateQueries({ queryKey: ['notifications'] }) } catch (error) { setErrorMessage(getApiErrorMessage(error)) } }
  return <div className="page-stack"><section className="page-intro"><div><Typography.Text className="eyebrow">INBOX</Typography.Text><Typography.Title level={1}>通知中心</Typography.Title><Typography.Paragraph type="secondary">查看回答、采纳和评论提醒。</Typography.Paragraph></div><Space><Select aria-label="通知筛选" value={unreadOnly ? 'unread' : 'all'} options={[{ value: 'all', label: '全部通知' }, { value: 'unread', label: '只看未读' }]} onChange={(value) => { setUnreadOnly(value === 'unread'); setPage(1) }} /><Button icon={<CheckOutlined />} onClick={() => void markAll()}>全部已读</Button></Space></section>{errorMessage ? <Typography.Text type="danger">{errorMessage}</Typography.Text> : null}<Card bordered={false}>{list.isLoading ? <Card loading bordered={false} /> : list.isError || !list.data ? <Empty description="暂时无法加载通知" /> : list.data.items.length ? <><List dataSource={list.data.items} renderItem={(item) => <List.Item actions={!item.is_read ? [<Button key="read" type="link" onClick={() => void markRead(item.id)}>标为已读</Button>] : []}><List.Item.Meta avatar={<Tag color={item.is_read ? 'default' : 'blue'}>{item.is_read ? '已读' : '未读'}</Tag>} title={<Space><Typography.Text strong={!item.is_read}>{item.actor_name}</Typography.Text><Typography.Text>{notificationText(item.type)}</Typography.Text></Space>} description={<Space direction="vertical" size={0}><Typography.Text type="secondary">{new Date(item.created_at).toLocaleString('zh-CN')}</Typography.Text>{item.question_id ? <Link to={`/questions/${item.question_id}`}>查看相关问题</Link> : null}</Space>} /></List.Item>} /><Pagination current={list.data.page} pageSize={list.data.page_size} total={list.data.total} showSizeChanger={false} onChange={setPage} /></> : <Empty description="暂无通知" />}</Card></div>
}
