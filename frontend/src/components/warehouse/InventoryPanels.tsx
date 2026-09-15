'use client'

import { Tabs } from 'antd'
import { LocationTable } from './LocationTable'
import { MaterialTable } from './MaterialTable'
import { StockTable } from './StockTable'

interface InventoryPanelsProps {
  /** 驾驶舱下钻带入的初始筛选（来自 URL searchParams） */
  initialKeyword?: string
  initialCategory?: string
}

/** 库存管理页签容器：现有库存 / 物料主数据 / 库位管理。 */
export function InventoryPanels({
  initialKeyword,
  initialCategory,
}: InventoryPanelsProps = {}) {
  return (
    <Tabs
      defaultActiveKey="stock"
      items={[
        {
          key: 'stock',
          label: '现有库存',
          children: (
            <StockTable initialKeyword={initialKeyword} initialCategory={initialCategory} />
          ),
        },
        { key: 'material', label: '物料主数据', children: <MaterialTable /> },
        { key: 'location', label: '库位管理', children: <LocationTable /> },
      ]}
    />
  )
}
