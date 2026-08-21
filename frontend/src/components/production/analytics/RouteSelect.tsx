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

/** 路线选择器：分析页共用同一份路线列表缓存。 */
export function RouteSelect({
  value,
  onChange,
  placeholder = '选择路线',
  style,
}: {
  value: string | undefined
  onChange: (v: string | undefined) => void
  placeholder?: string
  style?: CSSProperties
}) {
  const { data: routes = [] } = useQuery({
    queryKey: ['production-analytics-routes'],
    queryFn: () => fetchRoutesClient(),
  })
  return (
    <Select
      allowClear
      showSearch={{ optionFilterProp: 'label' }}
      placeholder={placeholder}
      style={style}
      value={value}
      onChange={onChange}
      options={routes.map(r => ({ label: r.route_name, value: r.id }))}
    />
  )
}
