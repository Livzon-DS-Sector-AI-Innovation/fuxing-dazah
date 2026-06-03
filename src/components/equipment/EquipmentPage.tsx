'use client'

import { useEffect, useCallback } from 'react'
import { App, ConfigProvider, Tabs, Button, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { PlusOutlined } from '@ant-design/icons'
import { EquipmentCategory, Location, Equipment, EquipmentStatistics } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import { fetchEquipmentsClient, fetchEquipmentStatisticsClient } from '@/lib/api/equipment-client'
import { StatsCards } from './StatsCards'
import { EquipmentTable } from './EquipmentTable'
import { CategoryTree } from './CategoryTree'
import { LocationTree } from './LocationTree'
import { EquipmentDrawer } from './EquipmentDrawer'
import { CategoryDrawer } from './CategoryDrawer'
import { LocationDrawer } from './LocationDrawer'

interface EquipmentPageProps {
  initialCategories: EquipmentCategory[]
  initialLocations: Location[]
  initialEquipments: Equipment[]
  initialTotal: number
  initialStatistics: EquipmentStatistics
}

export function EquipmentPage({
  initialCategories,
  initialLocations,
  initialEquipments,
  initialTotal,
  initialStatistics,
}: EquipmentPageProps) {
  const {
    categories,
    locations,
    statistics,
    selectedCategory,
    selectedLocation,
    statusFilter,
    keyword,
    page,
    pageSize,
    loading,
    setCategories,
    setLocations,
    setEquipments,
    setStatistics,
    setTotal,
    setLoading,
    openEquipmentDrawer,
  } = useEquipmentStore()

  // 初始化数据
  useEffect(() => {
    setCategories(initialCategories)
    setLocations(initialLocations)
    setEquipments(initialEquipments)
    setStatistics(initialStatistics)
    setTotal(initialTotal)
  }, [initialCategories, initialLocations, initialEquipments, initialStatistics, initialTotal, setCategories, setLocations, setEquipments, setStatistics, setTotal])

  // 筛选/翻页时重新获取数据
  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [equipmentsResponse, stats] = await Promise.all([
        fetchEquipmentsClient({
          category_id: selectedCategory,
          location_id: selectedLocation,
          status: statusFilter || undefined,
          keyword: keyword || undefined,
          page,
          page_size: pageSize,
        }),
        fetchEquipmentStatisticsClient(),
      ])
      setEquipments(equipmentsResponse.items)
      setTotal(equipmentsResponse.total)
      setStatistics(stats)
    } catch (error) {
      console.error('获取设备数据失败:', error)
    } finally {
      setLoading(false)
    }
  }, [selectedCategory, selectedLocation, statusFilter, keyword, page, pageSize, setEquipments, setTotal, setStatistics, setLoading])

  // 监听筛选状态变化
  useEffect(() => {
    fetchData()
  }, [fetchData])

  const tabItems = [
    {
      key: 'category',
      label: '分类',
      children: <CategoryTree categories={categories} />,
    },
    {
      key: 'location',
      label: '位置',
      children: <LocationTree locations={locations} />,
    },
  ]

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        <div className="p-6">
          <h1
            className="font-semibold mb-4"
            style={{ fontSize: 22, color: '#1a1a1a', lineHeight: 1.3 }}
          >
            设备台账
          </h1>

          <StatsCards statistics={statistics ?? initialStatistics} />

          <div className="flex gap-4">
            {/* 左侧：分类/位置树 */}
            <div
              className="shrink-0"
              style={{
                width: 280,
                background: '#ffffff',
                padding: 16,
                borderRadius: 12,
                border: '1px solid #e5e3df',
              }}
            >
              <Tabs items={tabItems} />
            </div>

            {/* 右侧：设备列表 */}
            <div
              className="flex-1 min-w-0"
              style={{
                background: '#ffffff',
                padding: 20,
                borderRadius: 12,
                border: '1px solid #e5e3df',
                overflow: 'hidden',
              }}
            >
              <div className="mb-4 flex items-center justify-between">
                <h2
                  className="font-semibold"
                  style={{ fontSize: 18, color: '#1a1a1a', lineHeight: 1.4 }}
                >
                  设备列表
                </h2>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => openEquipmentDrawer()}
                >
                  新增设备
                </Button>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <Spin spinning={loading}>
                  <EquipmentTable onRefresh={fetchData} />
                </Spin>
              </div>
            </div>
          </div>

          {/* 抽屉组件 */}
          <EquipmentDrawer onRefresh={fetchData} />
          <CategoryDrawer />
          <LocationDrawer />
        </div>
      </App>
    </ConfigProvider>
  )
}
