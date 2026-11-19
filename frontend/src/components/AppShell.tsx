import { BellOutlined, ExperimentOutlined, LogoutOutlined, PlusOutlined, ReadOutlined, SettingOutlined, TagOutlined, TrophyOutlined } from '@ant-design/icons'
import { Badge, Button, Layout, Menu, Space, Tag, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { authApi } from '../api/auth'
import { isAdminPreview } from '../admin/mode'
import { notificationsApi } from '../api/notifications'

const { Header, Content, Footer } = Layout

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, refreshToken, logout } = useAuthStore()
  const unread = useQuery({ queryKey: ['notifications', 'unread-count'], queryFn: notificationsApi.unreadCount, enabled: Boolean(user), refetchInterval: 60_000 })
  const selectedMenuKey = location.pathname.startsWith('/admin')
    ? '/admin/preview'
    : location.pathname.startsWith('/leaderboard')
      ? '/leaderboard'
      : location.pathname.startsWith('/notifications')
        ? '/notifications'
        : location.pathname.startsWith('/account')
          ? '/account'
          : location.pathname.startsWith('/questions')
    ? '/questions'
    : location.pathname.startsWith('/tags')
      ? '/tags'
      : location.pathname.startsWith('/reputation')
        ? '/reputation'
        : '/questions'

  const menuItems: MenuProps['items'] = [
    { key: '/questions', icon: <ReadOutlined />, label: <Link to="/questions">问题广场</Link> },
    { key: '/tags', icon: <TagOutlined />, label: <Link to="/tags">标签目录</Link> },
    { key: '/leaderboard', icon: <TrophyOutlined />, label: <Link to="/leaderboard">排行榜</Link> },
    ...(user ? [{ key: '/notifications', icon: <BellOutlined />, label: <Link to="/notifications"><Badge count={unread.data?.count ?? 0} size="small" offset={[8, 0]}>通知中心</Badge></Link> }] : []),
    ...(isAdminPreview ? [{ key: '/admin/preview', icon: <ExperimentOutlined />, label: <Link to="/admin/preview">后台演示</Link> }] : []),
    ...(user
      ? [{ key: '/questions/new', icon: <PlusOutlined />, label: <Link to="/questions/new">发布问题</Link> }, { key: '/reputation', icon: <TrophyOutlined />, label: <Link to="/reputation">我的声誉</Link> }, { key: '/account', icon: <SettingOutlined />, label: <Link to="/account">个人资料</Link> }]
      : []),
  ]

  const handleLogout = async () => {
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken)
      } catch {
        // 本地清理仍需执行，退出接口失败不应阻止用户退出。
      }
    }
    logout()
    navigate('/questions')
  }

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <div className="header-inner">
          <Link className="brand" to="/questions">
            <span className="brand-mark">C</span>
            <span>CampusOverflow</span>
          </Link>
          <Menu
            className="main-menu"
            mode="horizontal"
            selectedKeys={[selectedMenuKey]}
            items={menuItems}
          />
          <Space className="header-actions">
            {user ? (
              <>
                <Tag color="blue">{user.displayName}</Tag>
                <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout}>
                  退出
                </Button>
              </>
            ) : (
              <Button type="primary" onClick={() => navigate('/login')}>
                登录
              </Button>
            )}
          </Space>
        </div>
      </Header>
      <Content className="app-content">
        <div className="content-container">
          <Outlet />
        </div>
      </Content>
      <Footer className="app-footer">
        <Typography.Text type="secondary">CampusOverflow · 校园问答社区</Typography.Text>
      </Footer>
    </Layout>
  )
}
