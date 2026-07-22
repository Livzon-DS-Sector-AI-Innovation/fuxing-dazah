'use client'

import { useEffect, useState } from 'react'
import { Drawer, Table, Spin, Empty, App, Button } from 'antd'
import {
  InfoCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import {
  CollectLogDetail,
  CollectLogDeviceDetail,
  CollectStatus,
} from '@/types/energy'
import { fetchCollectLogDetailClient } from '@/lib/api/energy'

// ── 轻奢 Pill ──

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

const statusConfig: Record<CollectStatus, ReturnType<typeof luxuryPill>> = {
  success: luxuryPill('#1aae39', '#d9f3e1'),
  partial: luxuryPill('#dd5b00', '#ffe8d4'),
  failed: luxuryPill('#e03131', '#fde0ec'),
}

const energyTypeConfig: Record<string, ReturnType<typeof luxuryPill>> = {
  electricity:    luxuryPill('#0075de', '#dcecfa'),
  water:          luxuryPill('#1aae39', '#d9f3e1'),
  steam:          luxuryPill('#dd5b00', '#ffe8d4'),
  cooling:        luxuryPill('#722ed1', '#f4ebfa'),
  compressed_air: luxuryPill('#2f54eb', '#e8ecfc'),
  nitrogen:       luxuryPill('#fa541c', '#ffede8'),
  natural_gas:    luxuryPill('#faad14', '#fffbe6'),
}

// ── 表格样式 ──

const detailTableStyles = `
.luxury-detail-table .ant-table-thead > tr > th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #a4a097;
  background: #fafaf9;
  border-bottom: 1px solid #ede9e4;
  padding: 10px 16px;
  font-weight: 600;
}
.luxury-detail-table .ant-table-thead > tr > th::before {
  display: none;
}
.luxury-detail-table .ant-table-tbody > tr > td {
  border-bottom: 1px solid #ede9e4;
  border-inline-end: none;
  padding: 10px 16px;
  font-size: 13px;
  color: #37352f;
}
.luxury-detail-table .ant-table-tbody > tr > td:last-child {
  border-inline-end: none;
}
.luxury-detail-table .ant-table-tbody > tr:hover > td {
  background: #f6f3ff !important;
}
.luxury-detail-table .ant-table-tbody > tr:hover > td:first-child {
  box-shadow: inset 2px 0 0 #5645d4;
}
.luxury-detail-table .ant-table {
  border-inline-start: none !important;
  border-inline-end: none !important;
}
.luxury-detail-table .ant-table-container {
  border-inline-start: none !important;
  border-inline-end: none !important;
}
`

// ── 分组标题 ──

function SectionLabel({
  icon,
  text,
}: {
  icon: React.ReactNode
  text: string
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 16,
        paddingBottom: 10,
        borderBottom: '1px solid #ede9e4',
        color: '#37352f',
        fontSize: 14,
        fontWeight: 600,
        lineHeight: 1.5,
      }}
    >
      <span style={{ color: '#787671', fontSize: 15 }}>{icon}</span>
      {text}
    </div>
  )
}

// ── 信息行 ──

function InfoRow({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        marginBottom: 12,
        lineHeight: 1.5,
      }}
    >
      <span
        style={{
          fontSize: 13,
          color: '#a4a097',
          minWidth: 80,
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 14, color: '#1a1a1a', fontWeight: 500 }}>
        {children}
      </span>
    </div>
  )
}

// ── Props ──

interface CollectLogDetailDrawerProps {
  logId: string
  open: boolean
  onClose: () => void
}

export function CollectLogDetailDrawer({
  logId,
  open,
  onClose,
}: CollectLogDetailDrawerProps) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<CollectLogDetail | null>(null)

  useEffect(() => {
    if (!open || !logId) return

    let cancelled = false
    setLoading(true)
    setDetail(null)
    fetchCollectLogDetailClient(logId)
      .then((data) => {
        if (!cancelled) setDetail(data)
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('获取采集日志详情失败:', err)
          message.error('获取采集日志详情失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, logId])

  const deviceColumns: TableColumnsType<CollectLogDeviceDetail> = [
    {
      title: '设备名称',
      dataIndex: 'device_name',
      key: 'device_name',
      width: 160,
      ellipsis: true,
    },
    {
      title: '平台编码',
      dataIndex: 'platform_device_code',
      key: 'platform_device_code',
      width: 160,
      ellipsis: true,
      render: (code: string) => (
        <span
          style={{
            fontFamily: 'SF Mono, ui-monospace, monospace',
            fontSize: 12,
            color: '#5d5b54',
          }}
        >
          {code}
        </span>
      ),
    },
    {
      title: '能源类型',
      dataIndex: 'energy_type',
      key: 'energy_type',
      width: 70,
      render: (type: string) => {
        const s = energyTypeConfig[type]
        const labelMap: Record<string, string> = {
          electricity: '电耗', water: '水耗', steam: '蒸汽',
          cooling: '冷量', compressed_air: '压缩空气', nitrogen: '氮气',
          natural_gas: '天然气',
        }
        const label = labelMap[type] ?? type
        return s ? <span style={s}>{label}</span> : label
      },
    },
    {
      title: '采集值',
      dataIndex: 'value',
      key: 'value',
      width: 120,
      align: 'right',
      render: (v: number) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
          {v?.toFixed(4) ?? '-'}
        </span>
      ),
    },
    {
      title: '单位',
      dataIndex: 'unit',
      key: 'unit',
      width: 60,
      render: (u: string) => (
        <span style={{ color: '#787671' }}>{u}</span>
      ),
    },
    {
      title: '数据时间',
      dataIndex: 'data_timestamp',
      key: 'data_timestamp',
      width: 210,
      render: (text: string, record: CollectLogDeviceDetail) => {
        if (!text) return '-'
        const start = new Date(text)
        const end = record.data_time_range_end
          ? new Date(record.data_time_range_end)
          : new Date(start.getTime() + 60 * 60 * 1000)
        const timeOpts: Intl.DateTimeFormatOptions = {
          hour: '2-digit',
          minute: '2-digit',
        }
        return (
          <span style={{ fontVariantNumeric: 'tabular-nums', color: '#5d5b54' }}>
            {start.toLocaleDateString('zh-CN')}{' '}
            {start.toLocaleTimeString('zh-CN', timeOpts)}
            {' ～ '}
            {end.toLocaleTimeString('zh-CN', timeOpts)}
          </span>
        )
      },
    },
  ]

  const statusStyle = detail
    ? statusConfig[detail.status as CollectStatus]
    : null
  const statusLabel =
    detail?.status === 'success'
      ? '成功'
      : detail?.status === 'partial'
        ? '部分成功'
        : detail?.status === 'failed'
          ? '失败'
          : '-'

  return (
    <Drawer
      title="采集日志详情"
      size={640}
      open={open}
      onClose={onClose}
      destroyOnHidden
      styles={{
        header: {
          borderBottom: '1px solid #e5e3df',
          padding: '16px 24px',
        },
        body: { padding: '24px' },
      }}
      extra={
        <Button
          onClick={onClose}
          style={{
            color: '#37352f',
            borderColor: '#c8c4be',
            borderRadius: 8,
            height: 36,
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          关闭
        </Button>
      }
    >
      <style>{detailTableStyles}</style>
      <Spin spinning={loading}>
        {detail ? (
          <>
            {/* ── 基本信息 ── */}
            <SectionLabel icon={<InfoCircleOutlined />} text="基本信息" />

            <InfoRow label="平台编码">
              <span
                style={{
                  fontFamily: 'SF Mono, ui-monospace, monospace',
                  fontSize: 13,
                  color: '#5d5b54',
                }}
              >
                {detail.platform_code}
              </span>
            </InfoRow>

            <InfoRow label="采集状态">
              {statusStyle && <span style={statusStyle}>{statusLabel}</span>}
            </InfoRow>

            <InfoRow label="采集时间">
              {new Date(detail.collect_time).toLocaleString('zh-CN')}
            </InfoRow>

            {/* 水务时间间隔告警：采集时间与数据时间 > 60 分钟时显示 */}
            {detail.time_range_start &&
              (() => {
                const collectTime = new Date(detail.collect_time).getTime()
                const dataTime = new Date(detail.time_range_start).getTime()
                const gapMinutes = Math.abs(collectTime - dataTime) / 1000 / 60
                if (gapMinutes > 60) {
                  return (
                    <div
                      style={{
                        marginTop: 8,
                        marginBottom: 12,
                        padding: '10px 12px',
                        borderRadius: 8,
                        background: '#fff8e6',
                        fontSize: 13,
                        lineHeight: 1.5,
                        color: '#dd5b00',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 6,
                      }}
                    >
                      <span style={{ flexShrink: 0 }}>⚠️</span>
                      <span>
                        采集执行时间与数据归属时间相差 {Math.round(gapMinutes)}{' '}
                        分钟，可能由定时采集延迟或补采历史数据导致，请关注数据时效性
                      </span>
                    </div>
                  )
                }
                return null
              })()}

            <InfoRow label="应采 / 成功">
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                <span
                  style={{
                    color:
                      detail.success_count === detail.device_count
                        ? '#1aae39'
                        : detail.success_count === 0
                          ? '#e03131'
                          : '#dd5b00',
                  }}
                >
                  {detail.success_count}
                </span>
                {' / '}
                {detail.device_count}
              </span>
            </InfoRow>

            <InfoRow label="数据时间范围">
              {detail.time_range_start && detail.time_range_end ? (
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {new Date(detail.time_range_start).toLocaleString('zh-CN')}
                  {' ～ '}
                  {new Date(detail.time_range_end).toLocaleString('zh-CN')}
                </span>
              ) : (
                <span style={{ color: '#a4a097' }}>—</span>
              )}
            </InfoRow>

            {detail.error_message && (
              <div
                style={{
                  marginTop: 8,
                  marginBottom: 12,
                  padding: '10px 12px',
                  borderRadius: 8,
                  background: '#fde0ec',
                  fontSize: 13,
                  lineHeight: 1.5,
                  color: '#e03131',
                }}
              >
                {detail.error_message}
              </div>
            )}

            {/* ── 设备采集详情 ── */}
            <SectionLabel
              icon={<ThunderboltOutlined />}
              text={`设备采集详情${detail.devices.length > 0 ? `（${detail.devices.length}）` : ''}`}
            />

            {detail.devices.length > 0 ? (
              <div
                style={{
                  borderRadius: 12,
                  border: '1px solid #ede9e4',
                  overflow: 'hidden',
                }}
              >
                <Table<CollectLogDeviceDetail>
                  className="luxury-detail-table"
                  columns={deviceColumns}
                  dataSource={detail.devices}
                  rowKey={(r) =>
                    `${r.platform_device_code}-${r.data_timestamp}`
                  }
                  size="small"
                  pagination={false}
                  scroll={{ x: 750 }}
                />
              </div>
            ) : (
              <Empty
                description="未找到关联的设备采集数据"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            )}
          </>
        ) : (
          !loading && (
            <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )
        )}
      </Spin>
    </Drawer>
  )
}
