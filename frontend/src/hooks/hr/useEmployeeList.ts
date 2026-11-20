'use client'

// 员工档案列表数据源：分页状态 + 查询条件驱动加载 + 请求序号守卫丢弃过期响应。
// 此前 EmployeeProfileClient 手写 loadData/seqRef/useEffect 三件套，收敛于此。

import { useCallback, useEffect, useRef, useState } from 'react'
import { App } from 'antd'
import { fetchEmployeesAction } from '@/actions/hr'
import type { Employee, EmployeeFieldFilters } from '@/types/hr'
import { fieldFiltersToParams } from '@/lib/hr'

/** 列表查询条件：关键词/部门/状态来自页面工具栏，字段筛选来自筛选面板 */
export interface EmployeeListQuery {
  keyword?: string
  department?: string
  status?: string
  /** 「全部」视图并入未分类人员；具体部门视图不混入（未分类有独立 tab） */
  includeUncategorized?: boolean
  filters?: EmployeeFieldFilters
}

export function useEmployeeList(query: EmployeeListQuery) {
  const { message } = App.useApp()
  const { keyword, department, status, includeUncategorized, filters } = query

  const [employees, setEmployees] = useState<Employee[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const seqRef = useRef(0)
  // refresh 自增触发 effect 重查（查询条件不变时强制刷新用）
  const [refreshSeq, setRefreshSeq] = useState(0)

  // 搜索/状态/部门/字段筛选变化时回到第一页，避免深页筛选后出现空页
  useEffect(() => {
    setPage((p) => (p === 1 ? p : 1))
  }, [keyword, department, status, filters])

  useEffect(() => {
    const seq = ++seqRef.current
    setLoading(true)
    fetchEmployeesAction({
      keyword: keyword || undefined,
      department: department || undefined,
      status: status || undefined,
      page,
      page_size: pageSize,
      include_uncategorized: includeUncategorized,
      ...fieldFiltersToParams(filters ?? {}),
    })
      .then((res) => {
        if (seq !== seqRef.current) return // 过期响应丢弃，防止旧页数据覆盖新页
        setEmployees(res.data)
        setTotal(res.meta?.total || 0)
      })
      .catch((err: Error) => {
        if (seq !== seqRef.current) return
        message.error(err.message || '加载数据失败')
      })
      .finally(() => {
        if (seq === seqRef.current) setLoading(false)
      })
  }, [keyword, department, status, includeUncategorized, filters, page, pageSize, refreshSeq, message])

  const onPaginationChange = useCallback((newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }, [])

  const refresh = useCallback(() => setRefreshSeq((s) => s + 1), [])

  return { employees, total, page, pageSize, loading, onPaginationChange, refresh }
}
