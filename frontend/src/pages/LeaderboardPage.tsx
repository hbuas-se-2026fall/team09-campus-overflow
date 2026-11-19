import { Card, Empty, Select, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { leaderboardApi } from '../api/leaderboard'
import type { LeaderboardPeriod } from '../api/types'

export function LeaderboardPage() {
  const [period, setPeriod] = useState<LeaderboardPeriod>('week')
  const query = useQuery({ queryKey: ['leaderboard', period], queryFn: () => leaderboardApi.get(period) })
  return <div className="page-stack"><section className="page-intro"><div><Typography.Text className="eyebrow">COMMUNITY LEADERBOARD</Typography.Text><Typography.Title level={1}>贡献排行榜</Typography.Title><Typography.Paragraph type="secondary">按周期查看社区贡献积分。</Typography.Paragraph></div><Select aria-label="排行榜周期" value={period} options={[{ value: 'week', label: '本周' }, { value: 'month', label: '本月' }, { value: 'semester', label: '本学期' }]} onChange={(value: LeaderboardPeriod) => setPeriod(value)} /></section><Card bordered={false}>{query.isLoading ? <Card loading bordered={false} /> : query.isError || !query.data ? <Empty description="暂时无法加载排行榜" /> : query.data.entries.length ? <><Typography.Text type="secondary">统计区间：{new Date(query.data.period_start).toLocaleDateString('zh-CN')} 至 {new Date(query.data.period_end).toLocaleDateString('zh-CN')}</Typography.Text><Table rowKey="user_id" pagination={false} dataSource={query.data.entries} columns={[{ title: '排名', dataIndex: 'rank', render: (rank: number) => rank <= 3 ? <Tag color="gold">第 {rank} 名</Tag> : `第 ${rank} 名` }, { title: '用户', dataIndex: 'display_name', render: (name: string, entry) => <Link to={`/users/${entry.user_id}`}>{name}</Link> }, { title: '净得分', dataIndex: 'score' }]} /></> : <Empty description="这个周期还没有榜单数据" />}</Card></div>
}
