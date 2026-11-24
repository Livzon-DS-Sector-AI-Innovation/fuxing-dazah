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
  /** 「未归类」版面：仅部门为空或不在部门表中的人员（独立 tab） */
  uncategorizedOnly?: boolean
  filters?: EmployeeFieldFilters
}

export function useEmployeeList(query: EmployeeListQuery) {
  const { message } = App.useApp()
  const { keyword, department, status, uncategorizedOnly, filters } = query

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
      // trim：输入停在全空格时不当关键词查（空串走全量），避免「删不干净」查 0 条
      keyword: keyword?.trim() || undefined,
      department: department || undefined,
      status: status || undefined,
      page,
      page_size: pageSize,
      uncategorized_only: uncategorizedOnly || undefined,
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
    // message 实例随 App.useApp() 每次渲染都是新引用，进依赖会无限请求（与原 loadData 一致不列入）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword, department, status, uncategorizedOnly, filters, page, pageSize, refreshSeq])

  const onPaginationChange = useCallback((newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }, [])

  const refresh = useCallback(() => setRefreshSeq((s) => s + 1), [])

  return { employees, total, page, pageSize, loading, onPaginationChange, refresh }
}
