'use client'

import { useEffect } from 'react'
import { usePermissionStore } from '@/stores/permission'
import { getCurrentUser } from '@/actions/auth'

export function usePermission() {
  const { permissions, roles, dataScopes, isLoaded, hasPermission, setPermissionData, reset } =
    usePermissionStore()

  useEffect(() => {
    if (!isLoaded) {
      getCurrentUser().then((user) => {
        if (user) {
          setPermissionData({
            permissions: user.permissions ?? [],
            roles: user.roles ?? [],
            dataScopes: user.data_scopes ?? {},
          })
        }
      })
    }
  }, [isLoaded, setPermissionData])

  return { permissions, roles, dataScopes, isLoaded, hasPermission, reset }
}
