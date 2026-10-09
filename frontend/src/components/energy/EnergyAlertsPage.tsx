'use client'

import { useState, useEffect } from 'react'
import { Button, Space, App, Tabs, DatePicker, Select } from 'antd'
import { usePagedList } from '@/lib/energy/usePagedList'
import { PlusOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { AlertRuleTable } from './AlertRuleTable'
import { AlertConfigDrawer } from './AlertConfigDrawer'
import { WorkshopConfigTable } from './WorkshopConfigTable'
import { WorkshopConfigDrawer } from './WorkshopConfigDrawer'
import { DailyPushConfigTable } from './DailyPushConfigTable'
import { DailyPushConfigDrawer } from './DailyPushConfigDrawer'
import { NitrogenPushConfigTable } from './NitrogenPushConfigTable'
import { NitrogenPushConfigDrawer } from './NitrogenPushConfigDrawer'
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
  getEnabledTypeConfigs,
} from '@/actions/energy'
import { useEnergyStore } from '@/stores/energy'
import { PageHeading } from '@/components/shared/PageHeading'
import { EnergyPageFrame } from './EnergyPageFrame'
import styles from './EnergyAlerts.module.css'

export function EnergyAlertsPage() {
  const { message } = App.useApp()
  const { openAlertConfigDrawer, openWorkshopConfigDrawer, openDailyPushConfigDrawer, openNitrogenPushConfigDrawer } = useEnergyStore()

  // ── 分页状态（列表数据由 usePagedList 管理）──
  const [rulesPage, setRulesPage] = useState(1)
  const [rulesPageSize, setRulesPageSize] = useState(10)
  const [configsPage, setConfigsPage] = useState(1)
  const [configsPageSize, setConfigsPageSize] = useState(10)
  const [pushConfigsPage, setPushConfigsPage] = useState(1)
  const [pushConfigsPageSize, setPushConfigsPageSize] = useState(10)

  // 手动推送
  const [sendConfigId, setSendConfigId] = useState<string | undefined>(undefined)
  const [sendDate, setSendDate] = useState<dayjs.Dayjs | null>(dayjs().subtract(1, 'day'))
  const [sending, setSending] = useState(false)

  // ── 氮气月度推送 ──
  const [nitrogenPushConfigsPage, setNitrogenPushConfigsPage] = useState(1)
  const [nitrogenPushConfigsPageSize, setNitrogenPushConfigsPageSize] = useState(10)

  const [nitrogenSendConfigId, setNitrogenSendConfigId] = useState<string | undefined>(undefined)
  const [nitrogenSendDate, setNitrogenSendDate] = useState<dayjs.Dayjs | null>(dayjs())
  const [nitrogenSending, setNitrogenSending] = useState(false)

  const [activeTab, setActiveTab] = useState<string>('rules')

  // 能源类型元数据（动态加载）
  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])

  useEffect(() => {
    getEnabledTypeConfigs().then((configs) => setTypeMetadata(configs)).catch(() => {})
  }, [])

  // 四个列表统一走 usePagedList。车间/推送/氮气三个 Tab 未激活时不请求，
  // 此时 data 为 undefined，Tab 徽标显示 '—' 而不是一个看起来像真数据的 0。
  const rulesQuery = usePagedList(['energy', 'alert-rules', rulesPage, rulesPageSize], () => getAlertRules({ page: rulesPage, page_size: rulesPageSize }), { errorMessage: '获取预警规则失败' })
  const configsQuery = usePagedList(['energy', 'workshop-configs', configsPage, configsPageSize], () => getWorkshopConfigs(configsPage, configsPageSize), { enabled: activeTab === 'workshop', errorMessage: '获取车间配置失败' })
  const pushQuery = usePagedList(['energy', 'daily-push-configs', pushConfigsPage, pushConfigsPageSize], () => getDailyPushConfigs(pushConfigsPage, pushConfigsPageSize), { enabled: activeTab === 'push', errorMessage: '获取推送配置失败' })
  const nitrogenQuery = usePagedList(['energy', 'nitrogen-push-configs', nitrogenPushConfigsPage, nitrogenPushConfigsPageSize], () => getNitrogenPushConfigs(nitrogenPushConfigsPage, nitrogenPushConfigsPageSize), { enabled: activeTab === 'nitrogen', errorMessage: '获取氮气推送配置失败' })

  const rules = rulesQuery.data?.items ?? []
  const configs = configsQuery.data?.items ?? []
  const pushConfigs = pushQuery.data?.items ?? []
  const nitrogenPushConfigs = nitrogenQuery.data?.items ?? []
  const rulesTotal = rulesQuery.data?.total ?? 0
  const configsTotal = configsQuery.data?.total ?? 0
  const pushConfigsTotal = pushQuery.data?.total ?? 0
  const nitrogenPushConfigsTotal = nitrogenQuery.data?.total ?? 0

  const handleEditRule = (record: AlertRule) => {
    openAlertConfigDrawer('edit', record.id)
  }

  const handleDeleteRule = async (id: string) => {
    try {
      await deleteAlertRule(id)
      message.success('删除成功')
      void rulesQuery.refetch()
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
      void configsQuery.refetch()
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
      void pushQuery.refetch()
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
      void pushQuery.refetch()
    } catch {
      message.error('推送失败')
    } finally {
      setSending(false)
    }
  }

  const handleEditNitrogenPushConfig = (record: NitrogenPushConfig) => {
    openNitrogenPushConfigDrawer('edit', record.id)
  }

  const handleDeleteNitrogenPushConfig = async (id: string) => {
    try {
      await deleteNitrogenPushConfig(id)
      message.success('删除成功')
      void nitrogenQuery.refetch()
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
      void nitrogenQuery.refetch()
    } catch {
      message.error('推送失败')
    } finally {
      setNitrogenSending(false)
    }
  }

  const tabItems = [
    {
      key: 'rules',
      label: <Space size={6}>预警规则 <span className={styles.tabMeta}>{rulesTotal}</span></Space>,
      children: (
        <div>
          <div className={styles.sectionIntro}><div><h2 className={styles.sectionTitle}>预警规则</h2><p className={styles.sectionDescription}>定义能源数据的阈值、等级与通知节奏，启用后自动触发预警。</p></div></div>
          <div className={styles.toolbar}>
            <span className={styles.statusSummary}>当前共 {rulesTotal} 条规则</span>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void rulesQuery.refetch()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openAlertConfigDrawer('create')}>
                新建规则
              </Button>
            </Space>
          </div>
          <AlertRuleTable
            data={rules}
            loading={rulesQuery.isFetching}
            total={rulesTotal}
            page={rulesPage}
            pageSize={rulesPageSize}
            onPageChange={(p, ps) => { setRulesPage(p); setRulesPageSize(ps) }}
            onEdit={handleEditRule}
            onDelete={handleDeleteRule}
            typeMetadata={typeMetadata}
          />
          <AlertConfigDrawer onRefresh={() => void rulesQuery.refetch()} />
        </div>
      ),
    },
    {
      key: 'workshop',
      label: <Space size={6}>车间预警 <span className={styles.tabMeta}>{configsQuery.data?.total ?? '—'}</span></Space>,
      children: (
        <div>
          <div className={styles.sectionIntro}><div><h2 className={styles.sectionTitle}>车间预警</h2><p className={styles.sectionDescription}>为车间关联预警规则和负责人，设置自动通知的执行方式。</p></div></div>
          <div className={styles.toolbar}>
            <span className={styles.statusSummary}>已配置 {configsTotal} 个车间</span>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void configsQuery.refetch()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openWorkshopConfigDrawer('create')}>
                新建车间配置
              </Button>
            </Space>
          </div>
          <WorkshopConfigTable
            data={configs}
            loading={configsQuery.isFetching}
            total={configsTotal}
            page={configsPage}
            pageSize={configsPageSize}
            onPageChange={(p, ps) => { setConfigsPage(p); setConfigsPageSize(ps) }}
            onEdit={handleEditConfig}
            onDelete={handleDeleteConfig}
          />
          <WorkshopConfigDrawer onRefresh={() => void configsQuery.refetch()} />
        </div>
      ),
    },
    {
      key: 'push',
      label: <Space size={6}>能源总耗推送 <span className={styles.tabMeta}>{pushQuery.data?.total ?? '—'}</span></Space>,
      children: (
        <div>
          <div className={styles.sectionIntro}><div><h2 className={styles.sectionTitle}>能源总耗推送</h2><p className={styles.sectionDescription}>按日汇总能源与设备数据，支持定时任务和指定日期的手动发送。</p></div></div>
          {/* 手动推送区域 */}
          <div
            className={styles.sendPanel}
          >
            <div className={styles.sendCopy}><p className={styles.sendTitle}>手动发送日报</p><p className={styles.sendDescription}>选择已启用的配置和目标日期后立即发送。</p></div>
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

          <div className={styles.toolbar}>
            <span className={styles.statusSummary}>共 {pushConfigsTotal} 个推送配置</span>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void pushQuery.refetch()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openDailyPushConfigDrawer('create')}>
                新建配置
              </Button>
            </Space>
          </div>
          <DailyPushConfigTable
            data={pushConfigs}
            loading={pushQuery.isFetching}
            total={pushConfigsTotal}
            page={pushConfigsPage}
            pageSize={pushConfigsPageSize}
            onPageChange={(p, ps) => { setPushConfigsPage(p); setPushConfigsPageSize(ps) }}
            onEdit={handleEditPushConfig}
            onDelete={handleDeletePushConfig}
          />
          <DailyPushConfigDrawer onRefresh={() => void pushQuery.refetch()} />
        </div>
      ),
    },
    {
      key: 'nitrogen',
      label: <Space size={6}>氮气计划 <span className={styles.tabMeta}>{nitrogenQuery.data?.total ?? '—'}</span></Space>,
      children: (
        <div>
          <div className={styles.sectionIntro}><div><h2 className={styles.sectionTitle}>氮气计划</h2><p className={styles.sectionDescription}>管理月度氮气消耗计划、保底用量及报告推送对象。</p></div></div>
          {/* 手动推送区域 */}
          <div
            className={`${styles.sendPanel} ${styles.sendPanelNitrogen}`}
          >
            <div className={styles.sendCopy}><p className={styles.sendTitle}>手动发送月报</p><p className={styles.sendDescription}>用于补发指定日期对应的氮气计划报告。</p></div>
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

          <div className={styles.toolbar}>
            <span className={styles.statusSummary}>共 {nitrogenPushConfigsTotal} 个氮气计划</span>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void nitrogenQuery.refetch()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openNitrogenPushConfigDrawer('create')}>
                新建配置
              </Button>
            </Space>
          </div>
          <NitrogenPushConfigTable
            data={nitrogenPushConfigs}
            loading={nitrogenQuery.isFetching}
            total={nitrogenPushConfigsTotal}
            page={nitrogenPushConfigsPage}
            pageSize={nitrogenPushConfigsPageSize}
            onPageChange={(p, ps) => { setNitrogenPushConfigsPage(p); setNitrogenPushConfigsPageSize(ps) }}
            onEdit={handleEditNitrogenPushConfig}
            onDelete={handleDeleteNitrogenPushConfig}
          />
          <NitrogenPushConfigDrawer onRefresh={() => void nitrogenQuery.refetch()} />
        </div>
      ),
    },
  ]

  return (
    <EnergyPageFrame>
      <PageHeading
        title="预警管理"
        subtitle="配置能源预警规则、车间通知及周期性报表推送，统一管理告警策略。"
      />
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        style={{ marginTop: 0 }}
      />
    </EnergyPageFrame>
  )
}
