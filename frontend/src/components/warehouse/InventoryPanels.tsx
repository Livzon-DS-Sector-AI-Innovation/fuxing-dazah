'use client'

import { Tabs } from 'antd'
import { LocationTable } from './LocationTable'
import { MaterialTable } from './MaterialTable'
import { StockTable } from './StockTable'

/** 库存管理页签容器：现有库存 / 物料主数据 / 库位管理。 */
export function InventoryPanels() {
  return (
    <Tabs
      defaultActiveKey="stock"
      items={[
        { key: 'stock', label: '现有库存', children: <StockTable /> },
        { key: 'material', label: '物料主数据', children: <MaterialTable /> },
        { key: 'location', label: '库位管理', children: <LocationTable /> },
      ]}
    />
  )
}
