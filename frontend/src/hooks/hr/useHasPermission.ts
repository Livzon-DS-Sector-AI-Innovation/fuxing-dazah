'use client'

// 「有没有某个权限」的水合安全版本，给 Suspense 边界里的页面做条件渲染用。
//
// usePermission().hasPermission() 读的是权限 store 的实时状态。页面所在的 Suspense 边界可能比布局
// 晚水合，届时布局已经把权限加载好：首帧就会多渲染出按钮，和 SSR 输出的「无权限」HTML 对不上，
// 控制台报 Hydration failed（SOP 培训登记表 / 二级表实测踩到）。
// 这里改为订阅 store 快照：水合首帧用服务端那份初始状态（空权限），与 SSR 一致，权限加载完再正常重渲染。

import { hasAnyPermission } from '@/lib/permissions'
import { usePermission } from '@/hooks/usePermission'
import { usePermissionStore } from '@/stores/permission'

export function useHasPermission(...codes: string[]): boolean {
  // 权限加载仍由 usePermission 触发（和其它页面走同一条加载路径）
  usePermission()
  const permissions = usePermissionStore((s) => s.permissions)
  return hasAnyPermission(permissions, codes)
}
