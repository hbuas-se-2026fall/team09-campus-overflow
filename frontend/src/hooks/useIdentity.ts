import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { authApi } from '../api/auth'
import type { UserRole } from '../api/types'
import { useAuthStore } from '../stores/authStore'

export const roleNames: Record<UserRole, string> = { student: '学生', teacher: '教师', ta: '助教', admin: '管理员' }
export const roleOptions = Object.entries(roleNames).map(([value, label]) => ({ value: value as UserRole, label }))
export const canVerifyAnswers = (role?: UserRole) => role === 'teacher' || role === 'ta' || role === 'admin'

// 权限入口根据服务端实时身份展示；本地持久化角色不作为授权依据。
export function useIdentity(enabled = true) {
  const accessToken = useAuthStore((state) => state.accessToken)
  const setUser = useAuthStore((state) => state.setUser)
  const identity = useQuery({
    queryKey: ['identity', accessToken],
    queryFn: authApi.me,
    enabled: Boolean(accessToken) && enabled,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
    refetchInterval: 30_000,
    retry: false,
  })
  useEffect(() => {
    if (!identity.data || identity.isError) return
    const user = identity.data
    setUser({ id: user.id, email: user.email, studentId: user.student_id, staffId: user.staff_id, createdAt: user.created_at, displayName: user.nickname ?? user.student_id ?? user.staff_id ?? user.email, role: user.role })
  }, [identity.data, identity.isError, setUser])
  return { ...identity, data: accessToken && enabled && !identity.isError ? identity.data : undefined }
}
