'use client'

// 员工筛选面板下拉选项（各可枚举字段的现有取值聚合，后端提供）。

import { useCallback, useEffect, useState } from 'react'
import { fetchEmployeeFilterOptionsAction } from '@/actions/hr'
import type { EmployeeFilterOptions } from '@/types/hr'

export function useHrFilterOptions() {
  const [filterOptions, setFilterOptions] = useState<EmployeeFilterOptions>({})

  const load = useCallback(async () => {
    try {
      setFilterOptions(await fetchEmployeeFilterOptionsAction())
    } catch {
      // 选项加载失败不阻断列表，只是下拉暂无可选项
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return { filterOptions, refresh: load }
}
