import { useQuery } from '@tanstack/react-query'
import { Button, Result, Skeleton } from 'antd'
import { Link } from 'react-router-dom'
import { authApi } from '../api/auth'
import { getApiErrorMessage } from '../api/errors'
import { useAuthStore } from '../stores/authStore'

export function AdminEntryPage() {
  const accessToken = useAuthStore((state) => state.accessToken)
  const identity = useQuery({
    queryKey: ['admin-entry-identity', accessToken],
    queryFn: authApi.me,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
  })

  if (identity.isPending) return <div role="status" aria-label="正在核验身份"><Skeleton active /></div>
  if (identity.isError) {
    return <Result status="error" title="无法核验身份" subTitle={getApiErrorMessage(identity.error)}
      extra={<Button onClick={() => { void identity.refetch() }}>重新核验</Button>} />
  }

  // 当前服务端契约只有 student/teacher。管理接口交付前，任何身份均不开放管理操作。
  return <Result status="403" title="管理后台尚未开放"
    subTitle={`当前账号：${identity.data.email}。服务端尚未提供管理员身份和管理接口，当前账号无法执行管理操作。`}
    extra={<Link to="/questions"><Button type="primary">返回问题广场</Button></Link>} />
}
