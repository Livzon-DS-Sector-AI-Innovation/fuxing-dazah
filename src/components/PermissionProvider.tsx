'use client'

import { usePermissionStore } from '@/stores/permission'

interface PermissionProviderProps {
  children: React.ReactNode
  initialPermissions: string[]
  initialRoles: string[]
  initialDataScopes: Record<string, string>
}

export function PermissionProvider({
  children,
  initialPermissions,
  initialRoles,
  initialDataScopes,
}: PermissionProviderProps) {
  const isLoaded = usePermissionStore((s) => s.isLoaded)
  const setPermissionData = usePermissionStore((s) => s.setPermissionData)

  // SSR 预取数据同步初始化 store，消除异步 gap。
  // 仅在 isLoaded 为 false 且有有效权限数据时写入。
  // SSR 失败时（空数组）不初始化，交由 usePermission hook 的客户端重试接管。
  if (!isLoaded && initialPermissions.length > 0) {
    setPermissionData({
      permissions: initialPermissions,
      roles: initialRoles,
      dataScopes: initialDataScopes,
    })
  }

  return <>{children}</>
}
