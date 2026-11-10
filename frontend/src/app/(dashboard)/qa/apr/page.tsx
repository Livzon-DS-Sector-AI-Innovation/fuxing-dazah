'use client'

import { redirect } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'

/**
 * /qa/apr 根路由：按权限跳第一个读得动的子页，而不是无条件进数据录入
 * （只读用户直达 /qa/apr 时不应落在一个满是只读痕迹的录入页）。
 * 权限码与 menu-config 保持同口径；权限加载完成前保持空白一帧。
 */
export default function QaAprPage() {
  const { hasPermission, isLoaded } = usePermission()
  if (!isLoaded) return null
  if (hasPermission('qa:apr:enter', 'qa:apr:read', 'qa:*:read')) redirect('/qa/apr/entry')
  if (hasPermission('qa:apr:read', 'qa:*:read')) redirect('/qa/apr/summary')
  if (hasPermission('qa:apr:manage')) redirect('/qa/apr/config')
  // 三个子页都无权：仍跳汇总页，让页面自身给出明确的错误/空态
  redirect('/qa/apr/summary')
}
