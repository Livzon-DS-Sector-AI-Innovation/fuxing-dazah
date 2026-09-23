'use client'

import { useEffect, useMemo, useState } from 'react'
import { App, Button, Popconfirm, Select, Spin, Switch, TimePicker } from 'antd'
import { DeleteOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { useEnergyStore } from '@/stores/energy'
import { usePermission } from '@/hooks/usePermission'
import { getCollectLogs, getCollectSettings, triggerCollect, updateCollectSettings, clearCollectLogs } from '@/actions/energy'
import { fetchPlatformsClient, type PlatformInfo } from '@/lib/api/energy'
import { usePagedList } from '@/lib/energy/usePagedList'
import type { CollectLog, PaginatedResponse } from '@/types/energy'
import { PageHeading } from '@/components/shared/PageHeading'
import { EnergyErrorReporter } from './EnergyErrorReporter'
import { CollectLogTable } from './CollectLogTable'
import { CollectLogDetailDrawer } from './CollectLogDetailDrawer'
import { EnergyPageFrame } from './EnergyPageFrame'
import styles from './EnergyCollection.module.css'

const emptyLogs: PaginatedResponse<CollectLog> = { items: [], total: 0, page: 1, page_size: 10 }

export default function EnergyCollectLogsPage() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const { logFilters, setLogFilters, resetLogFilters, collectLogDrawerOpen, collectLogDrawerId, closeCollectLogDrawer } = useEnergyStore()
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [clearLoading, setClearLoading] = useState(false)
  const [autoCollectEnabled, setAutoCollectEnabled] = useState(false)
  const [dailyCollectTime, setDailyCollectTime] = useState('08:00')
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [timeSaving, setTimeSaving] = useState(false)
  const [platforms, setPlatforms] = useState<PlatformInfo[]>([])
  const canTrigger = hasPermission('energy:collect:trigger')
  const canClear = hasPermission('energy:collect_log:delete')

  const logsQuery = usePagedList(['energy', 'collect-logs', logFilters], () => getCollectLogs(logFilters), { errorMessage: '日志加载失败，请稍后重试' })
  const data = logsQuery.data ?? emptyLogs
  const loading = logsQuery.isFetching
  const fetchData = () => void logsQuery.refetch()

  useEffect(() => {
    if (!canTrigger) return
    let cancelled = false
    getCollectSettings().then((settings) => { if (!cancelled) { setAutoCollectEnabled(settings.auto_collect_enabled); setDailyCollectTime(settings.daily_collect_time || '08:00') } }).catch(() => { if (!cancelled) message.error('自动采集设置加载失败') })
    return () => { cancelled = true }
  }, [canTrigger, message])
  // 平台下拉是筛选选项，必须来自完整平台列表：当前页的日志只覆盖其中一部分。
  useEffect(() => {
    let active = true
    fetchPlatformsClient().then((list) => { if (active) setPlatforms(list) }).catch(() => undefined)
    return () => { active = false }
  }, [])

  const updateEnabled = async (enabled: boolean) => {
    setSettingsLoading(true)
    try { const result = await updateCollectSettings({ auto_collect_enabled: enabled }); setAutoCollectEnabled(result.auto_collect_enabled); message.success(enabled ? '自动采集已开启' : '自动采集已关闭') } catch { message.error('设置更新失败，请检查权限') } finally { setSettingsLoading(false) }
  }
  const updateTime = async (value: Dayjs | null, timeString: string | null) => {
    const next = timeString || ''
    if (!value || !next) return
    const previous = dailyCollectTime
    setDailyCollectTime(next); setTimeSaving(true)
    try { const result = await updateCollectSettings({ daily_collect_time: next }); setDailyCollectTime(result.daily_collect_time || next); message.success(`每日采集时间已设为 ${next}`) } catch { setDailyCollectTime(previous); message.error('采集时间更新失败，请检查权限') } finally { setTimeSaving(false) }
  }
  const handleTrigger = async (platformCode?: string) => {
    setTriggerLoading(true)
    try { await triggerCollect(platformCode); message.success(platformCode ? `已重新触发 ${platformCode}` : '采集任务已触发'); await logsQuery.refetch() } catch { message.error('触发采集失败，请检查权限或服务状态') } finally { setTriggerLoading(false) }
  }
  const handleClear = async () => {
    setClearLoading(true)
    // 回到第 1 页由 queryKey 变化自动重取；已经在第 1 页时 key 不变，才需要显式刷新。
    // 两种情况各只发一个请求，不要既改 key 又手动 refetch。
    try { await clearCollectLogs(); if (logFilters.page === 1) void logsQuery.refetch(); else setLogFilters({ page: 1 }); message.success('采集日志已清空') } catch { message.error('清空日志失败，请检查权限') } finally { setClearLoading(false) }
  }

  const stats = useMemo(() => data.items.reduce((result, row) => {
    result.total += 1
    result[row.status] += 1
    result.collected += row.success_count || 0
    result.expected += row.expected_count || row.device_count * 24
    return result
  }, { total: 0, collected: 0, expected: 0, success: 0, partial: 0, failed: 0 } as { total: number; collected: number; expected: number; success: number; partial: number; failed: number }), [data.items])
  const successRate = stats.expected ? Math.round((stats.collected / stats.expected) * 100) : 0

  return <EnergyPageFrame><div className={styles.stack}><EnergyErrorReporter /><PageHeading title="采集日志" subtitle="查看采集任务的当前页结果，处理失败任务并调整自动采集设置。" />
    <section className={styles.panel} aria-label="自动采集设置"><div className={styles.settings}><div className={styles.settingsTitle}><span className={styles.settingsIcon}><ThunderboltOutlined /></span><div><h2 className={styles.sectionTitle}>自动采集</h2><p className={styles.description}>统一设置每日采集时间，也可以立即运行一次采集。</p></div></div><div className={styles.actions}><label className={styles.inlineField}><span className={styles.fieldLabel}>启用</span><Switch checked={autoCollectEnabled} loading={settingsLoading} disabled={!canTrigger} onChange={updateEnabled} /></label><label className={styles.inlineField}><span className={styles.fieldLabel}>每日</span><TimePicker className={styles.time} value={dayjs(dailyCollectTime, 'HH:mm')} format="HH:mm" minuteStep={30} disabled={timeSaving || !canTrigger} onChange={updateTime} /></label><Button type="primary" icon={<ThunderboltOutlined />} loading={triggerLoading} disabled={!canTrigger} onClick={() => handleTrigger()}>立即采集</Button></div></div></section>
    <section className={styles.panel} aria-label="日志筛选"><div className={styles.filterGrid}><div className={styles.field}><span className={styles.fieldLabel}>采集状态</span><Select className={styles.select} placeholder="全部状态" allowClear value={logFilters.status} onChange={(status) => setLogFilters({ status, page: 1 })} options={[{ label: '成功', value: 'success' }, { label: '部分成功', value: 'partial' }, { label: '失败', value: 'failed' }]} /></div><div className={styles.field}><span className={styles.fieldLabel}>平台编码</span><Select className={styles.select} placeholder="全部平台" allowClear value={logFilters.platform_code} onChange={(platform_code) => setLogFilters({ platform_code, page: 1 })} options={platforms.map((platform) => ({ label: platform.name || platform.code, value: platform.code }))} /></div><Button onClick={resetLogFilters}>重置筛选</Button><div style={{ flex: 1 }} /><Popconfirm title="清空采集日志" description="确认清空所有采集日志？此操作不可恢复。" okText="确认清空" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={handleClear}><Button danger icon={<DeleteOutlined />} loading={clearLoading} disabled={!canClear}>清空日志</Button></Popconfirm></div></section>
    <div className={styles.metrics} aria-label="当前页统计"><div className={styles.metric}><span className={styles.metricLabel}>当前页任务</span><strong className={styles.metricValue}>{stats.total}</strong><span className={styles.metricHint}>服务端共 {data.total} 条</span></div><div className={styles.metric}><span className={styles.metricLabel}>成功任务</span><strong className={`${styles.metricValue} ${styles.successText}`}>{stats.success}</strong><span className={styles.metricHint}>本页状态为成功</span></div><div className={styles.metric}><span className={styles.metricLabel}>失败 / 部分成功</span><strong className={`${styles.metricValue} ${stats.failed ? styles.errorText : styles.warningText}`}>{stats.failed} / {stats.partial}</strong><span className={styles.metricHint}>按任务状态统计</span></div><div className={styles.metric}><span className={styles.metricLabel}>采集成功率</span><strong className={styles.metricValue}>{successRate}<small>%</small></strong><span className={styles.metricHint}>成功数据条数 / 应采条数</span></div></div>
    <section className={styles.panel}><div className={styles.sectionHeader}><div><h2>执行记录</h2><p className={styles.description}>失败任务可直接重试，详情中可查看设备级结果和错误信息。</p></div><Button onClick={fetchData} loading={loading}>刷新</Button></div><Spin spinning={loading} description="正在加载日志…"><CollectLogTable data={data.items} loading={false} total={data.total} onRetry={(platformCode) => handleTrigger(platformCode)} /></Spin></section>
    {collectLogDrawerOpen && collectLogDrawerId && <CollectLogDetailDrawer logId={collectLogDrawerId} open={collectLogDrawerOpen} onClose={closeCollectLogDrawer} />}
  </div></EnergyPageFrame>
}
