'use client'

import type { CSSProperties } from 'react'
import { Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { fetchRouteGraphClient, fetchRoutesClient } from '@/lib/api/production-client'

/** 选中路线的图数据（级联查询），分析页各组件共用。 */
export function useRouteGraph(scope: string, routeId: string | undefined) {
  const { data: graph } = useQuery({
    queryKey: [`production-analytics-${scope}-graph`, routeId],
    queryFn: () => fetchRouteGraphClient(routeId!),
    enabled: !!routeId,
  })
  return graph
}

/**
 * 产品的工艺路线列表（分析页各组件共用，同 key 共享缓存）。
 * 只保留非草稿路线：工段汇总后端按 exclude_draft_route 取数，
 * 草稿路线没有生产数据，列出来只会让两个分析页作用域不一致。
 */
export function useProductRoutes(productId: string) {
  const { data = [], isLoading } = useQuery({
    queryKey: ['production-analytics-routes', productId],
    queryFn: () => fetchRoutesClient(productId),
    enabled: !!productId,
  })
  return { routes: data.filter(r => r.status !== 'draft'), isLoading }
}

/**
 * 工艺路线选择器（分析页共用）。产品由页面左侧 ProductSidebar 选择后传入，
 * 这里只负责按产品过滤展示该产品的工艺路线。
 */
export function RouteSelect({
  value,
  onChange,
  productId,
  placeholder = '选择路线',
  style,
}: {
  value: string | undefined
  onChange: (v: string | undefined) => void
  productId: string
  placeholder?: string
  style?: CSSProperties
}) {
  const { routes } = useProductRoutes(productId)

  return (
    <Select
      allowClear
      showSearch={{ optionFilterProp: 'label' }}
      placeholder={placeholder}
      style={style}
      value={value}
      onChange={onChange}
      options={routes.map(r => ({ label: r.route_name, value: r.id }))}
      notFoundContent="该产品暂无工艺路线"
    />
  )
}
