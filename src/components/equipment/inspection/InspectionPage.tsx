'use client'

import { useEffect, useCallback } from 'react'
import { Tabs, Button } from 'antd'
import {
  CheckSquareOutlined, EnvironmentOutlined, HistoryOutlined, FileTextOutlined, PlusOutlined,
} from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { useEquipmentStore } from '@/stores/equipment'
import { InspectionTasksTab } from './InspectionTasksTab'
import { InspectionRoutesTab } from './InspectionRoutesTab'
import { InspectionHistoryTab } from './InspectionHistoryTab'
import { InspectionExecuteView } from './InspectionExecuteView'
import { InspectionTaskDrawer } from './InspectionTaskDrawer'
import { InspectionRouteDrawer } from './InspectionRouteDrawer'
import { InspectionScheduleDrawer } from './InspectionScheduleDrawer'
import { InspectionRouteEquipmentDrawer } from './InspectionRouteEquipmentDrawer'
import { InspectionDetailDrawer } from './InspectionDetailDrawer'
import { InspectionTemplateTable, InspectionTemplateDrawer, InspectionItemDrawer } from '@/components/equipment'
import { fetchInspectionTemplatesClient } from '@/lib/api/equipment-client'
import type { InspectionTemplate, EquipmentCategory } from '@/types/equipment'

interface Props {
  initialTemplates: InspectionTemplate[]
  initialEquipments: { id: string; name: string; equipment_no: string }[]
  initialCategories: EquipmentCategory[]
  initialLocations: { id: string; name: string; code: string }[]
}

export function InspectionPage({ initialTemplates, initialEquipments, initialCategories, initialLocations }: Props) {
  const {
    activeTab, setActiveTab,
    executingTaskId, clearExecuting,
    templates, setTemplates,
  } = useInspectionStore()

  const {
    setInspectionTemplates, setInspectionTemplateTotal,
    inspectionTemplatePage, inspectionTemplatePageSize, inspectionTemplateKeyword,
    setInspectionTemplateLoading, openInspectionTemplateDrawer,
  } = useEquipmentStore()

  useEffect(() => {
    if (initialTemplates.length > 0 && templates.length === 0) {
      setTemplates(initialTemplates)
    }
  }, [initialTemplates, templates.length, setTemplates])

  const fetchTemplateData = useCallback(async () => {
    setInspectionTemplateLoading(true)
    try {
      const res = await fetchInspectionTemplatesClient({
        keyword: inspectionTemplateKeyword || undefined,
        page: inspectionTemplatePage, page_size: inspectionTemplatePageSize,
      })
      setInspectionTemplates(res.items)
      setInspectionTemplateTotal(res.total)
      // 同步活跃模板到巡检 store，确保任务/路线抽屉下拉即时更新
      const activeRes = await fetchInspectionTemplatesClient({ is_active: true, page: 1, page_size: 200 })
      setTemplates(activeRes.items)
    } catch (e) {
      console.error('获取巡检模板数据失败:', e)
    } finally {
      setInspectionTemplateLoading(false)
    }
  }, [inspectionTemplateKeyword, inspectionTemplatePage, inspectionTemplatePageSize, setInspectionTemplates, setInspectionTemplateTotal, setInspectionTemplateLoading, setTemplates])

  useEffect(() => {
    if (activeTab === 'templates') fetchTemplateData()
  }, [activeTab, fetchTemplateData])

  if (executingTaskId) {
    return <InspectionExecuteView onClose={clearExecuting} />
  }

  const tabItems = [
    {
      key: 'tasks',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <CheckSquareOutlined style={{ fontSize: 15 }} />
          巡检任务
        </span>
      ),
      children: <InspectionTasksTab templates={templates} equipments={initialEquipments} />,
    },
    {
      key: 'routes',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <EnvironmentOutlined style={{ fontSize: 15 }} />
          巡检线路
        </span>
      ),
      children: <InspectionRoutesTab templates={templates} equipments={initialEquipments} />,
    },
    {
      key: 'templates',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <FileTextOutlined style={{ fontSize: 15 }} />
          巡检模板
        </span>
      ),
      children: (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
              巡检模板列表
            </h2>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openInspectionTemplateDrawer()}
              style={{ borderRadius: 8, height: 36, background: '#5645d4', borderColor: '#5645d4', fontWeight: 600, fontSize: 13, boxShadow: 'none' }}>
              新建巡检模板
            </Button>
          </div>
          <InspectionTemplateTable onRefresh={fetchTemplateData} categories={initialCategories} />
        </div>
      ),
    },
    {
      key: 'history',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <HistoryOutlined style={{ fontSize: 15 }} />
          历史记录
        </span>
      ),
      children: <InspectionHistoryTab equipments={initialEquipments} />,
    }
  ]

  return (
    <div style={{ paddingBottom: 40 }}>
      {/* 页面头部 */}
      <div style={{
        marginBottom: 24,
      }}>
        <h2 style={{
          fontSize: 22, fontWeight: 600, color: '#1a1a1a',
          margin: 0, marginBottom: 4, lineHeight: 1.3,
        }}>
          设备巡检
        </h2>
        <p style={{
          fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5,
        }}>
          巡检线路管理 · 任务执行 · 历史追溯 · 模板管理
        </p>
      </div>

      {/* Tab 内容包进白色卡片，浮在 surface 背景上 */}
      <div style={{
        background: '#ffffff',
        borderRadius: 12,
        border: '1px solid #e5e3df',
        padding: '4px 24px 24px',
      }}>
        <Tabs
          activeKey={activeTab}
          onChange={key => setActiveTab(key as 'tasks' | 'routes' | 'history' | 'templates')}
          items={tabItems}
          tabBarStyle={{
            borderBottom: '1px solid #ede9e4',
            marginBottom: 20,
            paddingLeft: 0,
          }}
          tabBarGutter={32}
        />
      </div>

      <InspectionTaskDrawer templates={templates} equipments={initialEquipments} />
      <InspectionRouteDrawer />
      <InspectionScheduleDrawer />
      <InspectionRouteEquipmentDrawer equipments={initialEquipments} locations={initialLocations} templates={templates} />
      <InspectionDetailDrawer />
      <InspectionTemplateDrawer categories={initialCategories} onRefresh={fetchTemplateData} />
      <InspectionItemDrawer />
    </div>
  )
}
