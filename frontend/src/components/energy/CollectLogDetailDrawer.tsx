'use client'

import { useEffect, useState } from 'react'
import { Alert, App, Drawer, Empty, Spin, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import { InfoCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { CollectLogDetail, CollectLogDeviceDetail, CollectStatus, EnergyTypeMeta } from '@/types/energy'
import { fetchCollectLogDetailClient, fetchEnabledTypeConfigsClient } from '@/lib/api/energy'
import { reportEnergyError } from '@/lib/energy/error-report'
import styles from './EnergyCollection.module.css'

const labels: Record<CollectStatus, string> = { success: '成功', partial: '部分成功', failed: '失败' }
export function CollectLogDetailDrawer({ logId, open, onClose }: { logId: string; open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<CollectLogDetail | null>(null)
  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])
  useEffect(() => {
    if (!open || !logId) return
    let cancelled = false
    // Reset loading for the newly selected log; cleanup cancels stale responses.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    fetchCollectLogDetailClient(logId).then((nextDetail) => { if (!cancelled) setDetail(nextDetail) }).catch((error) => { if (!cancelled) { console.error('获取采集日志详情失败:', error); reportEnergyError({ message: error instanceof Error ? error.message : String(error), api_url: `/api/v1/energy/collect/logs/${logId}/detail`, page_url: window.location.href, component: 'CollectLogDetailDrawer' }); message.error('获取采集日志详情失败') } }).finally(() => { if (!cancelled) setLoading(false) })
    // 类型元数据只用于给能源类型标签上色，失败时退回原始 type_code 即可，不能连累已取回的详情。
    fetchEnabledTypeConfigsClient().then((configs) => { if (!cancelled) setTypeMetadata(configs.map((config) => ({ type_code: config.type_code, display_name: config.display_name, unit: config.unit, color: config.color, icon: config.icon }))) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [logId, open, message])
  const columns: TableColumnsType<CollectLogDeviceDetail> = [
    { title: '设备名称', dataIndex: 'device_name', key: 'device_name', width: 150, ellipsis: true },
    { title: '平台设备编码', dataIndex: 'platform_device_code', key: 'platform_device_code', width: 150, ellipsis: true, render: (value: string) => <span className={styles.mono}>{value}</span> },
    { title: '能源类型', dataIndex: 'energy_type', key: 'energy_type', width: 100, render: (value: string) => { const meta = typeMetadata.find((item) => item.type_code === value); return <Tag color={meta?.color || undefined}>{meta?.display_name || value}</Tag> } },
    { title: '采集值', dataIndex: 'value', key: 'value', width: 110, align: 'right', render: (value: number) => <span className={styles.numeric}>{value?.toFixed(4) || '—'}</span> },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 60 },
    { title: '数据时间', dataIndex: 'data_timestamp', key: 'data_timestamp', width: 190, render: (value: string, row) => { if (!value) return '—'; const start = new Date(value); const end = row.data_time_range_end ? new Date(row.data_time_range_end) : new Date(start.getTime() + (row.is_daily ? 86400000 : 3600000)); return <span className={styles.numeric}>{row.is_daily ? start.toLocaleDateString('zh-CN') : `${start.toLocaleString('zh-CN')} ～ ${end.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`}</span> } },
  ]
  const expected = detail ? detail.expected_count || detail.device_count * 24 : 0
  // 采集执行时间与数据归属时间相差过大，说明是延迟采集或补采历史数据，需要提醒数据时效性。
  const gapMinutes = detail?.time_range_start ? Math.abs(new Date(detail.created_at).getTime() - new Date(detail.time_range_start).getTime()) / 60000 : 0
  return <Drawer className={styles.drawer} title="采集日志详情" open={open} onClose={onClose} destroyOnHidden size={680}><Spin spinning={loading}>{detail ? <div className={styles.stack}><section className={styles.panel}><div className={styles.sectionHeader}><h2><InfoCircleOutlined /> 基本信息</h2><span className={`${styles.status} ${styles[detail.status]}`}>{labels[detail.status]}</span></div><div className={styles.panelBody}><dl className={styles.detailInfo}><div><dt>平台编码</dt><dd className={styles.mono}>{detail.platform_code}</dd></div><div><dt>采集时间</dt><dd>{new Date(detail.created_at).toLocaleString('zh-CN')}</dd></div><div><dt>成功 / 应采</dt><dd className={styles.numeric}>{detail.success_count} / {expected}</dd></div><div><dt>数据时间范围</dt><dd>{detail.time_range_start && detail.time_range_end ? `${new Date(detail.time_range_start).toLocaleString('zh-CN')} ～ ${new Date(detail.time_range_end).toLocaleString('zh-CN')}` : '—'}</dd></div></dl>{gapMinutes > 60 && <Alert type="warning" showIcon className={styles.detailAlert} title={`采集执行时间与数据归属时间相差 ${Math.round(gapMinutes)} 分钟，可能由定时采集延迟或补采历史数据导致，请关注数据时效性`} />}{detail.error_message && <Alert type="error" showIcon title="采集错误" description={detail.error_message} className={styles.detailAlert} />}</div></section><section className={styles.panel}><div className={styles.sectionHeader}><h2><ThunderboltOutlined /> 设备采集详情 <span className={styles.muted}>（{detail.devices.length}）</span></h2></div>{detail.devices.length ? <Table className={styles.table} columns={columns} dataSource={detail.devices} rowKey={(row) => `${row.platform_device_code}-${row.data_timestamp}`} pagination={false} scroll={{ x: 760 }} /> : <Empty description="未找到关联的设备采集数据" className={styles.empty} />}</section></div> : !loading && <Empty description="暂无数据" className={styles.empty} />}</Spin></Drawer>
}
