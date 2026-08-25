import { create } from 'zustand'
import { hasAnyPermission } from '@/lib/permissions'

interface PermissionState {
  permissions: Set<string>
  roles: string[]
  dataScopes: Record<string, string>
  isLoaded: boolean
  loadError: boolean
  setPermissionData: (data: {
    permissions: string[]
    roles: string[]
    dataScopes: Record<string, string>
  }) => void
  setLoadError: () => void
  hasPermission: (...codes: string[]) => boolean
  reset: () => void
}

export const usePermissionStore = create<PermissionState>((set, get) => ({
  permissions: new Set(),
  roles: [],
  dataScopes: {},
  isLoaded: false,
  loadError: false,

  setPermissionData: (data) =>
    set({
      permissions: new Set(data.permissions),
      roles: data.roles,
      dataScopes: data.dataScopes,
      isLoaded: true,
      loadError: false,
    }),

  // 加载失败（重试耗尽）后也视为已加载：以空权限生效侧边栏/TopNav 过滤，
  // 权限受限菜单 fail-closed，避免整会话静默 fail-open
  setLoadError: () => set({ loadError: true, isLoaded: true }),

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
      loadError: false,
    }),
}))
