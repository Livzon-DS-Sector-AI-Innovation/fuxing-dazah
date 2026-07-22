'use client'

import { useState, useEffect, useCallback } from 'react'
import { Button, Space, message, Tabs } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  AlertRuleTable,
  AlertConfigDrawer,
  WorkshopConfigTable,
  WorkshopConfigDrawer,
} from '@/components/energy'
import { AlertRule, WorkshopConfig } from '@/types/energy'
import {
  getAlertRules,
  deleteAlertRule,
  getWorkshopConfigs,
  deleteWorkshopConfig,
} from '@/actions/energy'
import { useEnergyStore } from '@/stores/energy'

export default function AlertsPage() {
  const { openAlertConfigDrawer, openWorkshopConfigDrawer } = useEnergyStore()

  // ── 预警规则 ──
  const [rules, setRules] = useState<AlertRule[]>([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [rulesTotal, setRulesTotal] = useState(0)
  const [rulesPage, setRulesPage] = useState(1)
  const [rulesPageSize, setRulesPageSize] = useState(10)

  // ── 车间配置 ──
  const [configs, setConfigs] = useState<WorkshopConfig[]>([])
  const [configsLoading, setConfigsLoading] = useState(false)
  const [configsTotal, setConfigsTotal] = useState(0)
  const [configsPage, setConfigsPage] = useState(1)
  const [configsPageSize, setConfigsPageSize] = useState(10)

  const [activeTab, setActiveTab] = useState<string>('rules')

  // ── 预警规则 ──
  const fetchRules = useCallback(async (p = rulesPage, ps = rulesPageSize) => {
    setRulesLoading(true)
    try {
      const result = await getAlertRules({ page: p, page_size: ps })
      setRules(result.items)
      setRulesTotal(result.total)
    } catch {
      message.error('获取预警规则失败')
    } finally {
      setRulesLoading(false)
    }
  }, [rulesPage, rulesPageSize])

  useEffect(() => {
    fetchRules()
  }, [fetchRules])

  // ── 车间配置 ──
  const fetchConfigs = useCallback(async (p = configsPage, ps = configsPageSize) => {
    setConfigsLoading(true)
    try {
      const result = await getWorkshopConfigs(p, ps)
      setConfigs(result.items)
      setConfigsTotal(result.total)
    } catch {
      message.error('获取车间配置失败')
    } finally {
      setConfigsLoading(false)
    }
  }, [configsPage, configsPageSize])

  useEffect(() => {
    if (activeTab === 'workshop') {
      fetchConfigs()
    }
  }, [activeTab, fetchConfigs])

  const handleEditRule = (record: AlertRule) => {
    openAlertConfigDrawer('edit', record.id)
  }

  const handleDeleteRule = async (id: string) => {
    try {
      await deleteAlertRule(id)
      message.success('删除成功')
      fetchRules()
    } catch {
      message.error('删除失败')
    }
  }

  const handleEditConfig = (record: WorkshopConfig) => {
    openWorkshopConfigDrawer('edit', record.id)
  }

  const handleDeleteConfig = async (id: string) => {
    try {
      await deleteWorkshopConfig(id)
      message.success('删除成功')
      fetchConfigs()
    } catch {
      message.error('删除失败')
    }
  }

  const tabItems = [
    {
      key: 'rules',
      label: '预警规则',
      children: (
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => fetchRules()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openAlertConfigDrawer('create')}>
                新建规则
              </Button>
            </Space>
          </div>
          <AlertRuleTable
            data={rules}
            loading={rulesLoading}
            total={rulesTotal}
            page={rulesPage}
            pageSize={rulesPageSize}
            onPageChange={(p, ps) => { setRulesPage(p); setRulesPageSize(ps) }}
            onRefresh={() => fetchRules()}
            onEdit={handleEditRule}
            onDelete={handleDeleteRule}
          />
          <AlertConfigDrawer onRefresh={() => fetchRules()} />
        </div>
      ),
    },
    {
      key: 'workshop',
      label: '车间预警',
      children: (
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => fetchConfigs()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openWorkshopConfigDrawer('create')}>
                新建车间配置
              </Button>
            </Space>
          </div>
          <WorkshopConfigTable
            data={configs}
            loading={configsLoading}
            total={configsTotal}
            page={configsPage}
            pageSize={configsPageSize}
            onPageChange={(p, ps) => { setConfigsPage(p); setConfigsPageSize(ps) }}
            onEdit={handleEditConfig}
            onDelete={handleDeleteConfig}
          />
          <WorkshopConfigDrawer onRefresh={() => fetchConfigs()} />
        </div>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <h1
        style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.3, margin: '0 0 20px' }}
      >
        预警管理
      </h1>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        style={{ marginTop: 0 }}
      />
    </div>
  )
}
