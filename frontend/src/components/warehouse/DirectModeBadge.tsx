'use client'

import { useQuery } from '@tanstack/react-query'
import { Tag, Tooltip } from 'antd'

const CLIENT_API = process.env.NEXT_PUBLIC_API_BASE_URL || ''

/** 直读模式探针：/stocks 首行 meta.mode（轻查，5 分钟缓存）。 */
export function useDirectMode(): boolean | undefined {
  const { data } = useQuery({
    queryKey: ['warehouse', 'direct-mode-probe'],
    queryFn: async () => {
      const resp = await fetch(
        `${CLIENT_API}/api/v1/warehouse/stocks?page_size=1`,
        { credentials: 'include' },
      )
      if (!resp.ok) return undefined
      const body = await resp.json()
      return body?.meta?.mode as string | undefined
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
  return data === 'direct'
}

/** 「多维表格直读」徽标：直读模式时展示（镜像模式不渲染）。 */
export function DirectModeBadge() {
  const direct = useDirectMode()
  if (!direct) return null
  return (
    <Tooltip title="数据实时直读生产多维表格（TTL 缓存约 5 分钟）；运行参数 warehouse_direct_read_enabled 可切回镜像">
      <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
        直读台账
      </Tag>
    </Tooltip>
  )
}
