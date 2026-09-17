'use client'

import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import { AlertTriangle, Boxes, Inbox, MapPin, Package, Send } from 'lucide-react'
import type { WarehouseOverview } from '@/types/warehouse'
import { getWarehouseOverview } from '@/actions/warehouse'
import { StatCard } from './ui/StatCard'
import { StatusTag } from './ui/StatusTag'

/** 库存管理概览：StatCard 行 + 低库存警示条（异常先行） */
export function WarehouseOverviewCards() {
  const [overview, setOverview] = useState<WarehouseOverview | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      setOverview(await getWarehouseOverview())
    } catch {
      // 概览加载失败不打断页面
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const t = setTimeout(fetchData, 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading && !overview) {
    return (
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-[86px] animate-pulse rounded-xl border border-[var(--color-hairline)] bg-white"
          />
        ))}
      </div>
    )
  }
  if (!overview) return null

  return (
    <div className="mb-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          emphasized
          label="库存 SKU"
          tone="primary"
          icon={<Boxes />}
          value={overview.stock_sku_count}
          sub={`${overview.material_count} 项物料`}
        />
        <StatCard label="物料主数据" icon={<Package />} value={overview.material_count} />
        <StatCard label="库位" icon={<MapPin />} value={overview.location_count} />
        <StatCard
          label="今日入库"
          tone="ok"
          icon={<Inbox />}
          value={overview.today_inbound_quantity.toFixed(2)}
        />
        <StatCard
          label="今日出库"
          tone="danger"
          icon={<Send />}
          value={overview.today_outbound_quantity.toFixed(2)}
        />
      </div>

      {overview.low_stock_materials.length > 0 && (
        <div
          className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-4 py-2.5 text-[13px]"
          style={{ background: 'var(--wh-warn-bg)', color: 'var(--wh-warn)' }}
        >
          <span className="inline-flex items-center gap-1.5 font-medium">
            <AlertTriangle size={15} />
            低于安全库存 {overview.low_stock_materials.length} 项：
          </span>
          {overview.low_stock_materials.map(name => (
            <StatusTag key={name} tone="warn" label={name} bordered />
          ))}
        </div>
      )}
    </div>
  )
}
