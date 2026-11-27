'use client'

import { useEffect } from 'react'
import { App } from 'antd'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { PaginatedResponse } from '@/types/energy'

/**
 * 分页列表查询：queryKey 变化自动重取，翻页时保留上一页数据避免表格闪烁。
 * enabled=false 时不发请求（例如尚未激活的 Tab），此时 data 为 undefined，
 * 调用方用 `data?.total ?? '—'` 展示未加载占位，不要落到 0。
 * errorMessage 传值时，请求失败会弹一次提示。
 */
export function usePagedList<T>(
  queryKey: readonly unknown[],
  fetcher: () => Promise<PaginatedResponse<T>>,
  { enabled = true, errorMessage }: { enabled?: boolean; errorMessage?: string } = {},
) {
  const { message } = App.useApp()
  const query = useQuery({
    queryKey,
    queryFn: () => fetcher(),
    enabled,
    placeholderData: keepPreviousData,
  })
  const { isError } = query
  useEffect(() => {
    if (isError && errorMessage) message.error(errorMessage)
  }, [isError, errorMessage, message])
  return query
}
