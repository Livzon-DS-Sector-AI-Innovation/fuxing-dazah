'use client'

// 部门列表数据源。此前档案页容器/异动弹窗/员工表单三处各写一遍加载逻辑。

import { useCallback, useEffect, useState } from 'react'
import { fetchDepartmentsAction } from '@/actions/hr'
import type { Department } from '@/types/hr'

/**
 * @param options.pageSize 单页条数（异动弹窗等仅取名池时调大）
 * @param options.enabled  false 时不请求（弹窗类组件打开才加载）
 */
export function useHrDepartments(options?: { pageSize?: number; enabled?: boolean }) {
  const { pageSize = 100, enabled = true } = options ?? {}

  const [departments, setDepartments] = useState<Department[]>([])

  const load = useCallback(async () => {
    try {
      const res = await fetchDepartmentsAction({ page_size: pageSize })
      setDepartments(res.data)
    } catch {
      setDepartments([])
    }
  }, [pageSize])

  useEffect(() => {
    if (enabled) load()
  }, [enabled, load])

  return { departments, refresh: load }
}
