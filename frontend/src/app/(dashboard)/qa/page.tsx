'use client'

import { redirect } from 'next/navigation'
import { QaWorkspace } from '@/components/qa'
import { usePermission } from '@/hooks/usePermission'
import { moduleMenus, type SubMenuItem } from '@/lib/menu-config'

/**
 * /qa 概览需要知识库读权限；没有就跳第一个可读的 QA 子页，
 * 避免只有偏差/CAPA/PQR/COA 权限的人落在满屏 403 的概览页。
 */
export default function QaHomePage() {
  const { hasPermission, isLoaded } = usePermission()
  if (!isLoaded) return null

  const qa = moduleMenus.find((m) => m.key === 'qa')
  const overview = qa?.children.find((c) => c.key === 'overview')
  const canOverview =
    !overview?.permissions?.length || hasPermission(...overview.permissions)
  if (canOverview) return <QaWorkspace view="home" />

  const canSee = (item: SubMenuItem): boolean => {
    if (item.permissions?.length && !hasPermission(...item.permissions)) return false
    if (item.children?.length) return item.children.some(canSee)
    return true
  }
  const target = qa?.children.find((c) => c.key !== 'overview' && canSee(c))
  redirect(target?.path ?? '/')
}
