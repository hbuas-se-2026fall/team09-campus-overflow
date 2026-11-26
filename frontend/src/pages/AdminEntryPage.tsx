import { lazy, Suspense } from 'react'
import { Button, Result, Skeleton } from 'antd'
import { Link } from 'react-router-dom'
import { getApiErrorMessage } from '../api/errors'
import { useIdentity } from '../hooks/useIdentity'

const AdminConsole = lazy(() => import('../admin/AdminConsole').then(({ AdminConsole: component }) => ({ default: component })))

export function AdminEntryPage() {
  const identity = useIdentity()

  if (identity.isPending) return <div role="status" aria-label="正在核验身份"><Skeleton active /></div>
  if (identity.isError || !identity.data) {
    return <Result status="error" title="无法核验身份" subTitle={getApiErrorMessage(identity.error)}
      extra={<Button onClick={() => { void identity.refetch() }}>重新核验</Button>} />
  }

  if (identity.data.role !== 'admin') {
    return <Result status="403" title="仅管理员可访问管理后台" subTitle="当前账号没有管理员权限。"
      extra={<Link to="/questions"><Button type="primary">返回问题广场</Button></Link>} />
  }
  return <Suspense fallback={<Skeleton active />}><AdminConsole currentUserId={identity.data.id} /></Suspense>
}
