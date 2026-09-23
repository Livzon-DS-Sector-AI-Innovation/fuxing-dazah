'use client'

import { Button, Empty, Table } from 'antd'
import { EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { CollectLog, CollectStatus } from '@/types/energy'
import { useEnergyStore } from '@/stores/energy'
import { usePermission } from '@/hooks/usePermission'
import styles from './EnergyCollection.module.css'

const labels: Record<CollectStatus, string> = { success: '成功', partial: '部分成功', failed: '失败' }
export function CollectLogTable({ data, loading = false, total = 0, onRetry }: { data: CollectLog[]; loading?: boolean; total?: number; onRetry?: (platformCode: string) => void }) {
  const { logFilters, setLogFilters, openCollectLogDrawer } = useEnergyStore()
  const { hasPermission } = usePermission()
  const columns: TableColumnsType<CollectLog> = [
    { title: '平台编码', dataIndex: 'platform_code', key: 'platform_code', width: 150, render: (value: string) => <span className={styles.mono}>{value}</span> },
    { title: '采集时间', dataIndex: 'created_at', key: 'created_at', width: 190, render: (value: string) => <span className={styles.numeric}>{new Date(value).toLocaleString('zh-CN')}</span> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 120, render: (value: CollectStatus) => <span className={`${styles.status} ${styles[value]}`}>{labels[value]}</span> },
    { title: '成功 / 应采', key: 'count', width: 130, align: 'right', render: (_value, row) => { const expected = row.expected_count || row.device_count * 24; const tone = row.success_count >= expected ? styles.successText : row.success_count ? styles.warningText : styles.errorText; return <span className={styles.numeric}><strong className={tone}>{row.success_count}</strong> / {expected}</span> } },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true, render: (value: string | null) => value ? <span className={styles.errorText} title={value}>{value}</span> : <span className={styles.muted}>—</span> },
    { title: '操作', key: 'action', width: 150, render: (_value, row) => <div className={styles.actions}><Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openCollectLogDrawer(row.id)}>详情</Button>{row.status !== 'success' && onRetry && hasPermission('energy:collect:trigger') && <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => onRetry(row.platform_code)}>重试</Button>}</div> },
  ]
  return <Table<CollectLog> className={styles.table} columns={columns} dataSource={data} rowKey="id" loading={loading} locale={{ emptyText: <Empty description="暂无采集日志" /> }} scroll={{ x: 760 }} pagination={{ current: logFilters.page || 1, pageSize: logFilters.page_size || 10, total, showSizeChanger: true, showTotal: (value) => `共 ${value} 条`, onChange: (page, pageSize) => setLogFilters({ page, page_size: pageSize }) }} />
}
