'use client'

// 职位列表数据源（含按部门分组视图）。此前异动弹窗/员工表单各写一遍加载与分组。

import { useCallback, useEffect, useState } from 'react'
import { fetchPositions } from '@/actions/hr'
import type { PositionOption } from '@/types/hr'

/** @param options.enabled false 时不请求（弹窗类组件打开才加载） */
export function useHrPositions(options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true

  const [positions, setPositions] = useState<PositionOption[]>([])
  const [positionsByDept, setPositionsByDept] = useState<Record<string, string[]>>({})

  const load = useCallback(async () => {
    try {
      const list = await fetchPositions()
      setPositions(list)
      const map: Record<string, string[]> = {}
      list.forEach((p) => {
        if (!map[p.department]) map[p.department] = []
        map[p.department].push(p.name)
      })
      setPositionsByDept(map)
    } catch {
      setPositions([])
      setPositionsByDept({})
    }
  }, [])

  useEffect(() => {
    if (enabled) load()
  }, [enabled, load])

  return { positions, positionsByDept, refresh: load }
}
