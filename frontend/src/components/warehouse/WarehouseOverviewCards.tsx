'use client'

import { useEffect, useState } from 'react'
import { Alert, Card, Spin, Statistic } from 'antd'
import {
  AppstoreOutlined,
  DatabaseOutlined,
  InboxOutlined,
  DownloadOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { WarehouseOverview } from '@/types/warehouse'
import { getWarehouseOverview } from '@/actions/warehouse'

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
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Spin />
      </div>
    )
  }
  if (!overview) return null

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
        <Card size="small">
          <Statistic title="物料主数据" value={overview.material_count} prefix={<AppstoreOutlined />} />
        </Card>
        <Card size="small">
          <Statistic title="库位" value={overview.location_count} prefix={<DatabaseOutlined />} />
        </Card>
        <Card size="small">
          <Statistic title="库存 SKU" value={overview.stock_sku_count} prefix={<InboxOutlined />} />
        </Card>
        <Card size="small">
          <Statistic
            title="今日入库"
            value={overview.today_inbound_quantity}
            precision={2}
            prefix={<DownloadOutlined />}
          />
        </Card>
        <Card size="small">
          <Statistic
            title="今日出库"
            value={overview.today_outbound_quantity}
            precision={2}
            prefix={<UploadOutlined />}
          />
        </Card>
      </div>
      {overview.low_stock_materials.length > 0 && (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          showIcon
          message={`低于安全库存 ${overview.low_stock_materials.length} 项`}
          description={overview.low_stock_materials.join('；')}
        />
      )}
    </div>
  )
}
