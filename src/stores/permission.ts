import { create } from 'zustand'
import { hasAnyPermission } from '@/lib/permissions'

interface PermissionState {
  permissions: Set<string>
  roles: string[]
  dataScopes: Record<string, string>
  isLoaded: boolean
  setPermissionData: (data: {
    permissions: string[]
    roles: string[]
    dataScopes: Record<string, string>
  }) => void
  hasPermission: (...codes: string[]) => boolean
  reset: () => void
}

export const usePermissionStore = create<PermissionState>((set, get) => ({
  permissions: new Set(),
  roles: [],
  dataScopes: {},
  isLoaded: false,

  setPermissionData: (data) =>
    set({
      permissions: new Set(data.permissions),
      roles: data.roles,
      dataScopes: data.dataScopes,
      isLoaded: true,
    }),

  hasPermission: (...codes: string[]) => {
    const { permissions } = get()
    return hasAnyPermission(permissions, codes)
  },

  reset: () =>
    set({
      permissions: new Set(),
      roles: [],
      dataScopes: {},
      isLoaded: false,
    }),
}))
