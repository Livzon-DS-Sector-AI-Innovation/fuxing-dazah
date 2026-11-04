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

  // 加载失败（重试耗尽）后标记 isLoaded + loadError；导航组件检测到 loadError 时
  // 降级展示完整菜单，避免临时接口故障把侧边栏/顶栏清空。真实权限仍由后端接口校验。
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
