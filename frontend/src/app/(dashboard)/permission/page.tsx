'use client'

import { redirect } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'

/**
 * /permission 根路由：按权限跳第一个进得去的子页。
 * 「管理角色」或「委派管理角色」进角色管理；只有用户权限相关权限时直达用户权限页，
 * 避免落进无权的角色管理页。权限码与 menu-config 保持同口径；权限加载完成前保持空白一帧。
 */
export default function PermissionPage() {
  const { hasPermission, isLoaded } = usePermission()
  if (!isLoaded) return null
  if (hasPermission('permission:role:manage', 'permission:role:delegate')) redirect('/permission/roles')
  if (hasPermission('permission:user:assign', 'permission:user:view')) redirect('/permission/users')
  // 两个子页都无权：仍跳用户权限页，让页面守卫给出明确的提示
  redirect('/permission/users')
}
