'use client'

import { useCallback } from 'react'
import { App, Table, Button } from 'antd'
import { EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { EnergyDeviceConfig, EnergyType } from '@/types/energy'
import { useEnergyStore } from '@/stores/energy'
import { deleteEnergyDevice } from '@/actions/energy'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

// ── 轻奢 Pill 样式（全圆角、半透明底色、轻字重） ──

const luxuryPill = (color: string, bg: string) =>
  ({
    display: 'inline-flex',
    alignItems: 'center',
    padding: '2px 12px',
    borderRadius: 9999,
    fontSize: 12,
    fontWeight: 500,
    lineHeight: '20px',
    color,
    background: bg,
  } as const)

const energyTypeConfig: Record<EnergyType, ReturnType<typeof luxuryPill>> = {
  electricity: luxuryPill('#0075de', '#dcecfa'),
  water: luxuryPill('#1aae39', '#d9f3e1'),
  gas: luxuryPill('#dd5b00', '#ffe8d4'),
}

const monitorConfig: Record<string, ReturnType<typeof luxuryPill>> = {
  normal: luxuryPill('#787671', '#f0eeec'),
  important: luxuryPill('#dd5b00', '#ffe8d4'),
  urgent: luxuryPill('#e03131', '#fde0ec'),
}

const enabledPill = luxuryPill('#1aae39', '#d9f3e1')
const disabledPill = luxuryPill('#787671', '#f0eeec')

// ── 表格样式注入（仅影响本组件范围内的 .luxury-device-table） ──

const tableStyles = `
.luxury-device-table .ant-table-thead > tr > th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #a4a097;
  background: #fafaf9;
  border-bottom: 1px solid #ede9e4;
  padding: 10px 16px;
  font-weight: 600;
}
.luxury-device-table .ant-table-thead > tr > th::before {
  display: none;
}
.luxury-device-table .ant-table-tbody > tr > td {
  border-bottom: 1px solid #ede9e4;
  border-inline-end: none;
  padding: 12px 16px;
  font-size: 14px;
  color: #37352f;
}
.luxury-device-table .ant-table-tbody > tr > td:last-child {
  border-inline-end: none;
}
.luxury-device-table .ant-table-tbody > tr:hover > td {
  background: #f6f3ff !important;
}
.luxury-device-table .ant-table-tbody > tr:hover > td:first-child {
  box-shadow: inset 2px 0 0 #5645d4;
}
.luxury-device-table .ant-table {
  border-inline-start: none !important;
  border-inline-end: none !important;
}
.luxury-device-table .ant-table-container {
  border-inline-start: none !important;
  border-inline-end: none !important;
}
/* 分页：去掉边框，精简化 */
.luxury-device-table .ant-pagination-item {
  border: none;
  background: transparent;
  font-size: 13px;
  color: #787671;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
  border-radius: 8px;
}
.luxury-device-table .ant-pagination-item:hover {
  background: #f6f3ff;
  color: #5645d4;
}
.luxury-device-table .ant-pagination-item-active {
  background: #f6f3ff;
  color: #5645d4;
  font-weight: 600;
}
.luxury-device-table .ant-pagination-item-active:hover {
  background: #f6f3ff;
  color: #5645d4;
}
.luxury-device-table .ant-pagination-prev,
.luxury-device-table .ant-pagination-next {
  border: none;
  background: transparent;
  color: #787671;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
  border-radius: 8px;
}
.luxury-device-table .ant-pagination-prev:hover,
.luxury-device-table .ant-pagination-next:hover {
  background: #f6f3ff;
  color: #5645d4;
}
.luxury-device-table .ant-pagination-total-text {
  font-size: 13px;
  color: #a4a097;
}
.luxury-device-table .ant-select-selector {
  border-radius: 8px !important;
}
/* loading 骨架保持克制 */
.luxury-device-table .ant-spin-container::after {
  background: transparent;
}
`

// ── Props ──

interface DeviceTableProps {
  data: EnergyDeviceConfig[]
  loading?: boolean
  total?: number
  onRefresh: () => void
}

export function DeviceTable({
  data,
  loading = false,
  total = 0,
  onRefresh,
}: DeviceTableProps) {
  const { message, modal } = App.useApp()
  const { deviceFilters, setDeviceFilters, openDeviceDrawer } = useEnergyStore()

  const handleDelete = useCallback(
    (record: EnergyDeviceConfig) => {
      modal.confirm({
        title: '确认删除',
        content: `确定要删除数据源 "${record.device_name}" 吗？`,
        okText: '确认',
        cancelText: '取消',
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await deleteEnergyDevice(record.id)
            message.success('删除成功')
            onRefresh()
          } catch (error: any) {
            message.error(error?.message || '删除失败')
          }
        },
      })
    },
    [modal, message, onRefresh],
  )

  const columns: TableColumnsType<EnergyDeviceConfig> = [
    {
      title: '数据源名称',
      dataIndex: 'device_name',
      key: 'device_name',
      width: 180,
      ellipsis: true,
    },
    {
      title: '平台编码',
      dataIndex: 'platform_device_code',
      key: 'platform_device_code',
      width: 200,
      ellipsis: true,
      render: (code: string) => (
        <span style={{ fontFamily: 'SF Mono, ui-monospace, monospace', fontSize: 13, color: '#5d5b54' }}>
          {code}
        </span>
      ),
    },
    {
      title: '能源类型',
      dataIndex: 'energy_type',
      key: 'energy_type',
      width: 90,
      render: (type: EnergyType) => {
        const s = energyTypeConfig[type]
        return <span style={s}>{type === 'electricity' ? '电力' : type === 'water' ? '水' : '气体'}</span>
      },
    },
    {
      title: '车间',
      dataIndex: 'workshop',
      key: 'workshop',
      width: 120,
      ellipsis: true,
    },
    {
      title: '间隔',
      dataIndex: 'collection_interval',
      key: 'collection_interval',
      width: 80,
      align: 'right',
      render: (v: number) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', color: '#5d5b54' }}>
          {v} min
        </span>
      ),
    },
    {
      title: '监控级别',
      dataIndex: 'monitor_level',
      key: 'monitor_level',
      width: 90,
      render: (level: string) => {
        const s = monitorConfig[level] || monitorConfig.normal
        const label = level === 'normal' ? '普通' : level === 'important' ? '重要' : '紧急'
        return <span style={s}>{label}</span>
      },
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 80,
      render: (enabled: boolean) => (
        <span style={enabled ? enabledPill : disabledPill}>
          {enabled ? '启用' : '禁用'}
        </span>
      ),
    },
    {
      title: '',
      key: 'action',
      width: 72,
      render: (_: unknown, record: EnergyDeviceConfig) => (
        <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
          <PermissionGuard permission="energy:device:manage">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => openDeviceDrawer('edit', record.id)}
              style={{ color: '#5645d4' }}
              aria-label="编辑"
            />
            <Button
              type="text"
              size="small"
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(record)}
              style={{ color: '#e03131' }}
              aria-label="删除"
            />
          </PermissionGuard>
        </div>
      ),
    },
  ]

  return (
    <>
      <style>{tableStyles}</style>
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          border: '1px solid #ede9e4',
          boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
          overflow: 'hidden',
        }}
      >
        <Table<EnergyDeviceConfig>
          className="luxury-device-table"
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 'max-content' }}
          showSorterTooltip={false}
          pagination={{
            current: deviceFilters.page || 1,
            pageSize: deviceFilters.page_size || 10,
            total,
            showSizeChanger: true,
            showQuickJumper: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => {
              setDeviceFilters({ page, page_size: pageSize })
            },
          }}
        />
      </div>
    </>
  )
}
