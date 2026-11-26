import { Card, Descriptions, Empty, Skeleton, Space, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { profilesApi } from '../api/profiles'
import { roleNames } from '../hooks/useIdentity'
import type { UserRole } from '../api/types'

const badgeNames: Record<string, string> = {
  answers: '回答贡献',
  acceptance: '采纳质量',
  streak: '连续活跃',
}

export function ProfilePage() {
  const { userId } = useParams<{ userId: string }>()
  const profile = useQuery({ queryKey: ['profile', userId], queryFn: () => profilesApi.get(userId!), enabled: Boolean(userId) })
  const badges = useQuery({ queryKey: ['badges', userId], queryFn: () => profilesApi.badges(userId!), enabled: Boolean(userId) })
  if (profile.isLoading) return <Card loading bordered={false} />
  if (profile.isError || !profile.data) return <Empty description="找不到这个用户" />
  return <div className="page-stack">
    <section className="page-intro"><div><Typography.Text className="eyebrow">PUBLIC PROFILE</Typography.Text><Typography.Title level={1}>{profile.data.display_name}</Typography.Title><Typography.Paragraph type="secondary">公开个人主页</Typography.Paragraph></div></section>
    <Card bordered={false}><Descriptions column={1} items={[{ key: 'role', label: '身份', children: roleNames[profile.data.role as UserRole] ?? profile.data.role }, { key: 'nickname', label: '昵称', children: profile.data.nickname ?? '未设置' }, { key: 'college', label: '学院', children: profile.data.college ?? '未设置' }, { key: 'class', label: '班级', children: profile.data.class_name ?? '未设置' }]} /></Card>
    <Card title="贡献徽章" bordered={false}>
      {badges.isLoading ? <Skeleton active /> : badges.isError || !badges.data ? <Empty description="暂时无法加载徽章" /> : <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">回答 {badges.data.answer_count} 次 · 采纳 {badges.data.accepted_count} 次 · 采纳率 {(badges.data.acceptance_rate * 100).toFixed(1)}% · 最长连续活跃 {badges.data.longest_streak_days} 天</Typography.Text>
        {badges.data.badges.length ? <Space wrap>{badges.data.badges.map((badge) => <Tag color="gold" key={badge.code}>{badgeNames[badge.kind] ?? badge.kind} · {badge.tier}（{badge.threshold}）</Tag>)}</Space> : <Typography.Text type="secondary">暂时没有徽章</Typography.Text>}
      </Space>}
    </Card>
    <Typography.Text type="secondary">返回 <Link to="/questions">问题广场</Link></Typography.Text>
  </div>
}
