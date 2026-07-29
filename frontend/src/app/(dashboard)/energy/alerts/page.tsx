'use client'

import { useState, useEffect, useCallback } from 'react'
import { Button, Space, App, Tabs, DatePicker, Select } from 'antd'
import { PlusOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  AlertRuleTable,
  AlertConfigDrawer,
  WorkshopConfigTable,
  WorkshopConfigDrawer,
  DailyPushConfigTable,
  DailyPushConfigDrawer,
  NitrogenPushConfigTable,
  NitrogenPushConfigDrawer,
} from '@/components/energy'
import { AlertRule, WorkshopConfig, DailyPushConfig, NitrogenPushConfig, EnergyTypeMeta } from '@/types/energy'
import {
  getAlertRules,
  deleteAlertRule,
  getWorkshopConfigs,
  deleteWorkshopConfig,
  getDailyPushConfigs,
  deleteDailyPushConfig,
  sendDailyReport,
  getNitrogenPushConfigs,
  deleteNitrogenPushConfig,
  sendNitrogenReport,
} from '@/actions/energy'
import { useEnergyStore } from '@/stores/energy'
import { fetchEnabledTypeConfigsClient } from '@/lib/api/energy'

export default function AlertsPage() {
  const { message } = App.useApp()
  const { openAlertConfigDrawer, openWorkshopConfigDrawer, openDailyPushConfigDrawer, openNitrogenPushConfigDrawer } = useEnergyStore()

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

  // ── 能源总耗推送 ──
  const [pushConfigs, setPushConfigs] = useState<DailyPushConfig[]>([])
  const [pushConfigsLoading, setPushConfigsLoading] = useState(false)
  const [pushConfigsTotal, setPushConfigsTotal] = useState(0)
  const [pushConfigsPage, setPushConfigsPage] = useState(1)
  const [pushConfigsPageSize, setPushConfigsPageSize] = useState(10)

  // 手动推送
  const [sendConfigId, setSendConfigId] = useState<string | undefined>(undefined)
  const [sendDate, setSendDate] = useState<dayjs.Dayjs | null>(dayjs().subtract(1, 'day'))
  const [sending, setSending] = useState(false)

  // ── 氮气月度推送 ──
  const [nitrogenPushConfigs, setNitrogenPushConfigs] = useState<NitrogenPushConfig[]>([])
  const [nitrogenPushConfigsLoading, setNitrogenPushConfigsLoading] = useState(false)
  const [nitrogenPushConfigsTotal, setNitrogenPushConfigsTotal] = useState(0)
  const [nitrogenPushConfigsPage, setNitrogenPushConfigsPage] = useState(1)
  const [nitrogenPushConfigsPageSize, setNitrogenPushConfigsPageSize] = useState(10)

  const [nitrogenSendConfigId, setNitrogenSendConfigId] = useState<string | undefined>(undefined)
  const [nitrogenSendDate, setNitrogenSendDate] = useState<dayjs.Dayjs | null>(dayjs())
  const [nitrogenSending, setNitrogenSending] = useState(false)

  const [activeTab, setActiveTab] = useState<string>('rules')

  // 能源类型元数据（动态加载）
  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])

  useEffect(() => {
    fetchEnabledTypeConfigsClient().then(configs => {
      setTypeMetadata(configs.map(c => ({
        type_code: c.type_code,
        display_name: c.display_name,
        unit: c.unit,
        color: c.color,
        icon: c.icon,
      })))
    }).catch(() => {})
  }, [])

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

  // ── 能源总耗推送 ──
  const fetchPushConfigs = useCallback(async (p = pushConfigsPage, ps = pushConfigsPageSize) => {
    setPushConfigsLoading(true)
    try {
      const result = await getDailyPushConfigs(p, ps)
      setPushConfigs(result.items)
      setPushConfigsTotal(result.total)
    } catch {
      message.error('获取推送配置失败')
    } finally {
      setPushConfigsLoading(false)
    }
  }, [pushConfigsPage, pushConfigsPageSize])

  useEffect(() => {
    if (activeTab === 'push') {
      fetchPushConfigs()
    }
  }, [activeTab, fetchPushConfigs])

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

  const handleEditPushConfig = (record: DailyPushConfig) => {
    openDailyPushConfigDrawer('edit', record.id)
  }

  const handleDeletePushConfig = async (id: string) => {
    try {
      await deleteDailyPushConfig(id)
      message.success('删除成功')
      fetchPushConfigs()
    } catch {
      message.error('删除失败')
    }
  }

  const handleSendReport = async () => {
    if (!sendConfigId) {
      message.warning('请先选择推送配置')
      return
    }
    if (!sendDate) {
      message.warning('请选择目标日期')
      return
    }
    setSending(true)
    try {
      const result = await sendDailyReport({
        config_id: sendConfigId,
        target_date: sendDate.format('YYYY-MM-DD'),
      })
      message.success(result.message || '推送完成')
      fetchPushConfigs()
    } catch {
      message.error('推送失败')
    } finally {
      setSending(false)
    }
  }

  // ── 氮气月度推送 ──
  const fetchNitrogenPushConfigs = useCallback(async (p = nitrogenPushConfigsPage, ps = nitrogenPushConfigsPageSize) => {
    setNitrogenPushConfigsLoading(true)
    try {
      const result = await getNitrogenPushConfigs(p, ps)
      setNitrogenPushConfigs(result.items)
      setNitrogenPushConfigsTotal(result.total)
    } catch {
      message.error('获取氮气推送配置失败')
    } finally {
      setNitrogenPushConfigsLoading(false)
    }
  }, [nitrogenPushConfigsPage, nitrogenPushConfigsPageSize])

  useEffect(() => {
    if (activeTab === 'nitrogen') {
      fetchNitrogenPushConfigs()
    }
  }, [activeTab, fetchNitrogenPushConfigs])

  const handleEditNitrogenPushConfig = (record: NitrogenPushConfig) => {
    openNitrogenPushConfigDrawer('edit', record.id)
  }

  const handleDeleteNitrogenPushConfig = async (id: string) => {
    try {
      await deleteNitrogenPushConfig(id)
      message.success('删除成功')
      fetchNitrogenPushConfigs()
    } catch {
      message.error('删除失败')
    }
  }

  const handleSendNitrogenReport = async () => {
    if (!nitrogenSendConfigId) {
      message.warning('请先选择推送配置')
      return
    }
    if (!nitrogenSendDate) {
      message.warning('请选择目标日期')
      return
    }
    setNitrogenSending(true)
    try {
      const result = await sendNitrogenReport({
        config_id: nitrogenSendConfigId,
        target_date: nitrogenSendDate.format('YYYY-MM-DD'),
      })
      message.success(result.message || '推送完成')
      fetchNitrogenPushConfigs()
    } catch {
      message.error('推送失败')
    } finally {
      setNitrogenSending(false)
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
            typeMetadata={typeMetadata}
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
    {
      key: 'push',
      label: '能源总耗推送',
      children: (
        <div>
          {/* 手动推送区域 */}
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 12,
              marginBottom: 16, padding: '16px 20px',
              background: '#f6f3ff', borderRadius: 10, border: '1px solid #e8e3f4',
            }}
          >
            <span style={{ fontSize: 14, fontWeight: 500, color: '#37352f', whiteSpace: 'nowrap' }}>
              📤 手动推送：
            </span>
            <Select
              placeholder="选择推送配置"
              value={sendConfigId}
              onChange={setSendConfigId}
              options={pushConfigs.filter(c => c.is_enabled).map(c => ({ label: c.name, value: c.id }))}
              style={{ minWidth: 200 }}
              allowClear
            />
            <DatePicker
              value={sendDate}
              onChange={setSendDate}
              format="YYYY-MM-DD"
              placeholder="选择目标日期"
              style={{ minWidth: 160 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={sending}
              onClick={handleSendReport}
              style={{ background: '#5645d4', borderColor: '#5645d4', borderRadius: 8, boxShadow: 'none' }}
            >
              发送推送
            </Button>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => fetchPushConfigs()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openDailyPushConfigDrawer('create')}>
                新建配置
              </Button>
            </Space>
          </div>
          <DailyPushConfigTable
            data={pushConfigs}
            loading={pushConfigsLoading}
            total={pushConfigsTotal}
            page={pushConfigsPage}
            pageSize={pushConfigsPageSize}
            onPageChange={(p, ps) => { setPushConfigsPage(p); setPushConfigsPageSize(ps) }}
            onEdit={handleEditPushConfig}
            onDelete={handleDeletePushConfig}
          />
          <DailyPushConfigDrawer onRefresh={() => fetchPushConfigs()} />
        </div>
      ),
    },
    {
      key: 'nitrogen',
      label: '氮气计划',
      children: (
        <div>
          {/* 手动推送区域 */}
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 12,
              marginBottom: 16, padding: '16px 20px',
              background: '#f0f5ff', borderRadius: 10, border: '1px solid #dce8f7',
            }}
          >
            <span style={{ fontSize: 14, fontWeight: 500, color: '#37352f', whiteSpace: 'nowrap' }}>
              📤 手动推送：
            </span>
            <Select
              placeholder="选择推送配置"
              value={nitrogenSendConfigId}
              onChange={setNitrogenSendConfigId}
              options={nitrogenPushConfigs.filter(c => c.is_enabled).map(c => ({ label: c.name, value: c.id }))}
              style={{ minWidth: 200 }}
              allowClear
            />
            <DatePicker
              value={nitrogenSendDate}
              onChange={setNitrogenSendDate}
              format="YYYY-MM-DD"
              placeholder="选择目标日期"
              style={{ minWidth: 160 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={nitrogenSending}
              onClick={handleSendNitrogenReport}
              style={{ background: '#5645d4', borderColor: '#5645d4', borderRadius: 8, boxShadow: 'none' }}
            >
              发送推送
            </Button>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => fetchNitrogenPushConfigs()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openNitrogenPushConfigDrawer('create')}>
                新建配置
              </Button>
            </Space>
          </div>
          <NitrogenPushConfigTable
            data={nitrogenPushConfigs}
            loading={nitrogenPushConfigsLoading}
            total={nitrogenPushConfigsTotal}
            page={nitrogenPushConfigsPage}
            pageSize={nitrogenPushConfigsPageSize}
            onPageChange={(p, ps) => { setNitrogenPushConfigsPage(p); setNitrogenPushConfigsPageSize(ps) }}
            onEdit={handleEditNitrogenPushConfig}
            onDelete={handleDeleteNitrogenPushConfig}
          />
          <NitrogenPushConfigDrawer onRefresh={() => fetchNitrogenPushConfigs()} />
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
