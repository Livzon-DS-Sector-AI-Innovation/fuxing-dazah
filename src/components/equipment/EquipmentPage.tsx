'use client'

import { useEffect, useCallback, useState } from 'react'
import { App, ConfigProvider, Tabs, Button } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { MenuFoldOutlined, MenuUnfoldOutlined, ReloadOutlined } from '@ant-design/icons'
import { EquipmentCategory, Location, Equipment, EquipmentStatistics } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import { fetchEquipmentsClient, fetchEquipmentStatisticsClient, fetchCategoriesClient, fetchLocationsClient, fetchDepartmentsClient } from '@/lib/api/equipment-client'
import { StatsCards } from './StatsCards'
import { EquipmentTable } from './EquipmentTable'
import { CategoryTree } from './CategoryTree'
import { LocationTree } from './LocationTree'
import { EquipmentDrawer } from './EquipmentDrawer'
import { CategoryDrawer } from './CategoryDrawer'
import { LocationDrawer } from './LocationDrawer'
import { RepairDrawer } from './RepairDrawer'

interface EquipmentPageProps {
  initialCategories: EquipmentCategory[]
  initialLocations: Location[]
  initialEquipments: Equipment[]
  initialTotal: number
  initialStatistics: EquipmentStatistics
  initialDepartments: import('@/lib/api/equipment').DepartmentOption[]
}

const SIDEBAR_WIDTH = 280

export function EquipmentPage({
  initialCategories,
  initialLocations,
  initialEquipments,
  initialTotal,
  initialStatistics,
  initialDepartments,
}: EquipmentPageProps) {
  const {
    categories,
    locations,
    statistics,
    equipments,
    failureCodes,
    selectedCategory,
    selectedLocation,
    statusFilter,
    departmentFilter,
    departments,
    keyword,
    loading,
    setSelectedCategory,
    setSelectedLocation,
    setCategories,
    setLocations,
    setEquipments,
    setStatistics,
    setTotal,
    setLoading,
    setDepartments,
  } = useEquipmentStore()

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [resetKey, setResetKey] = useState(0)

  // 初始化 store 数据（包含 SSR 数据）
  useEffect(() => {
    setCategories(initialCategories)
    setLocations(initialLocations)
    setEquipments(initialEquipments)
    setTotal(initialTotal)
    setStatistics(initialStatistics)
  }, [])

  // 初始化部门列表（服务端数据）
  useEffect(() => {
    setDepartments(initialDepartments)
  }, [])

  // 客户端补偿加载：如果服务端初始数据为空（某个 API 失败导致），从客户端重新获取
  useEffect(() => {
    const loadMissing = async () => {
      const tasks: Promise<void>[] = []
      if (!categories.length) {
        tasks.push(
          fetchCategoriesClient().then(cats => { setCategories(cats) }).catch(e => { console.warn('客户端加载分类失败:', e) })
        )
      }
      if (!locations.length) {
        tasks.push(
          fetchLocationsClient().then(locs => { setLocations(locs) }).catch(e => { console.warn('客户端加载位置失败:', e) })
        )
      }
      if (!departments.length) {
        tasks.push(
          fetchDepartmentsClient().then(depts => { setDepartments(depts) }).catch(e => { console.warn('客户端加载部门失败:', e) })
        )
      }
      if (tasks.length) {
        await Promise.allSettled(tasks)
      }
    }
    loadMissing()
  }, [])

  // 获取列表数据
  const fetchData = useCallback(async (p: number, ps: number) => {
    setLoading(true)
    try {
      const equipmentsResponse = await fetchEquipmentsClient({
        category_id: selectedCategory,
        location_id: selectedLocation,
        department_id: departmentFilter,
        status: statusFilter || undefined,
        keyword: keyword || undefined,
        page: p,
        page_size: ps,
      })
      setEquipments(equipmentsResponse.items)
      setTotal(equipmentsResponse.total)
    } catch (error) {
      console.error('获取设备数据失败:', error)
    } finally {
      setLoading(false)
    }
  }, [selectedCategory, selectedLocation, departmentFilter, statusFilter, keyword, setEquipments, setTotal, setLoading])

  // 单独刷新统计（仅 mount 或需要时使用）
  const refreshStatistics = useCallback(async () => {
    try {
      const stats = await fetchEquipmentStatisticsClient()
      setStatistics(stats)
    } catch { /* 静默 */ }
  }, [setStatistics])

  // 刷新分类和位置树
  const refreshCategoriesAndLocations = useCallback(async () => {
    try {
      const [cats, locs] = await Promise.all([fetchCategoriesClient(), fetchLocationsClient()])
      setCategories(cats)
      setLocations(locs)
    } catch (error) {
      console.error('刷新分类/位置失败:', error)
    }
  }, [setCategories, setLocations])

  // 筛选变化时重置到第一页（含首次加载）
  useEffect(() => {
    fetchData(1, 20)
    setResetKey(k => k + 1)
  }, [selectedCategory, selectedLocation, departmentFilter, statusFilter, keyword])

  const tabItems = [
    {
      key: 'category',
      label: '分类',
      children: <CategoryTree categories={categories} onRefresh={refreshCategoriesAndLocations} />,
    },
    {
      key: 'location',
      label: '位置',
      children: <LocationTree locations={locations} onRefresh={refreshCategoriesAndLocations} />,
    },
  ]

  const tabBarExtra = (selectedCategory || selectedLocation) ? (
    <Button
      type="text"
      size="small"
      icon={<ReloadOutlined />}
      onClick={() => {
        setSelectedCategory(null)
        setSelectedLocation(null)
      }}
      style={{ color: '#787671', marginRight: 4 }}
    >
      重置
    </Button>
  ) : null

  const currentStats = statistics ?? initialStatistics

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        {/* 标题行 */}
        <div style={{ marginBottom: 24 }}>
          <h2
            style={{
              fontSize: 22, fontWeight: 600, color: '#1a1a1a',
              margin: 0, marginBottom: 4, lineHeight: 1.3,
            }}
          >
            设备台账
          </h2>
          <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
            分类管理 · 位置管理 · 设备档案 · 状态追踪
          </p>
        </div>

        <div className="flex gap-4" style={{ height: 'calc(100vh - 210px)', minHeight: 400 }}>
          {/* 左侧：可折叠分类/位置树 */}
          {!sidebarCollapsed && (
            <div
              className="shrink-0"
              style={{
                width: SIDEBAR_WIDTH,
                background: '#ffffff',
                padding: 16,
                borderRadius: 12,
                border: '1px solid #e5e3df',
                display: 'flex', flexDirection: 'column',
                overflow: 'hidden',
              }}
            >
              <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
                <Tabs items={tabItems} tabBarExtraContent={tabBarExtra} />
              </div>
            </div>
          )}

          {/* 右侧：设备列表 */}
          <div
            className="flex-1 min-w-0"
            style={{
              background: '#ffffff',
              padding: '16px 20px',
              borderRadius: 12,
              border: '1px solid #e5e3df',
              display: 'flex', flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* 折叠按钮 + 统计 + 标题 */}
            <div className="mb-3 flex items-center gap-3" style={{ flexShrink: 0 }}>
              <Button
                type="text"
                icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
                style={{ color: '#5d5b54', flexShrink: 0 }}
              />
              <StatsCards statistics={currentStats} compact />
            </div>

            {/* 表格区域 */}
            <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
              <EquipmentTable loading={loading} resetKey={resetKey} onPageChange={(p, ps) => fetchData(p, ps)} />
            </div>
          </div>
        </div>

        {/* 抽屉组件 */}
        <EquipmentDrawer onRefresh={() => { fetchData(1, 20); setResetKey(k => k + 1) }} />
        <CategoryDrawer onRefresh={refreshCategoriesAndLocations} />
        <LocationDrawer onRefresh={refreshCategoriesAndLocations} />
        <RepairDrawer
          equipments={equipments.map(e => ({
            id: e.id, equipment_no: e.equipment_no, name: e.name, importance: e.importance,
          }))}
          symptoms={failureCodes.symptoms}
          onRefresh={() => fetchData(1, 20)}
        />
      </App>
    </ConfigProvider>
  )
}
