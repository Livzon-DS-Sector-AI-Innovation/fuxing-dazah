'use client'

import { useState } from 'react'
import { Table, Tag, Space, Button, Popconfirm, Modal, Input, App } from 'antd'
import { CheckOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { TableColumnsType } from 'antd'
import { AlertRecord, EnergyTypeMeta } from '@/types/energy'
import { usePermission } from '@/hooks/usePermission'
import { fillAlertReason, approveAlertRecord, rejectAlertRecord } from '@/actions/energy'

interface AlertProcessTableProps {
  data: AlertRecord[]
  loading?: boolean
  total?: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onRefresh: () => void
  typeMetadata: EnergyTypeMeta[]
}

const statusLabels: Record<string, { text: string; color: string }> = {
  pending: { text: '待处理', color: 'orange' },
  rejected: { text: '已驳回', color: 'red' },
  processed: { text: '已处理', color: 'green' },
  ignored: { text: '已忽略', color: 'default' },
}

export function AlertProcessTable({
  data,
  loading = false,
  total = 0,
  page,
  pageSize,
  onPageChange,
  onRefresh,
  typeMetadata,
}: AlertProcessTableProps) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [reasonModalOpen, setReasonModalOpen] = useState(false)
  const [reasonRecordId, setReasonRecordId] = useState<string | null>(null)
  const [reasonText, setReasonText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const canApprove = hasPermission('energy:alert:process:approve')
  const canReject = hasPermission('energy:alert:process:reject')

  const handleFillReason = async () => {
    if (!reasonRecordId || !reasonText.trim()) {
      message.warning('请输入原因')
      return
    }
    setSubmitting(true)
    try {
      await fillAlertReason(reasonRecordId, { reason: reasonText.trim() })
      message.success('原因已填写')
      setReasonModalOpen(false)
      setReasonRecordId(null)
      setReasonText('')
      onRefresh()
    } catch {
      message.error('填写失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleApprove = async (id: string) => {
    try {
      await approveAlertRecord(id)
      message.success('已通过')
      onRefresh()
    } catch {
      message.error('操作失败')
    }
  }

  const handleReject = async (id: string) => {
    try {
      await rejectAlertRecord(id)
      message.success('已驳回并重新通知')
      onRefresh()
    } catch {
      message.error('操作失败')
    }
  }

  const openReasonModal = (record: AlertRecord) => {
    setReasonRecordId(record.id)
    setReasonText(record.reason || '')
    setReasonModalOpen(true)
  }

  const columns: TableColumnsType<AlertRecord> = [
    {
      title: '预警时间',
      dataIndex: 'alert_time',
      key: 'alert_time',
      width: 170,
      render: (t: string) => t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '—',
    },
    {
      title: '能源类型',
      dataIndex: 'energy_type',
      key: 'energy_type',
      width: 100,
      render: (type: string) => {
        const meta = typeMetadata.find(m => m.type_code === type)
        if (!meta) return <Tag>{type}</Tag>
        return <Tag color={meta.color || 'blue'}>{meta.display_name}</Tag>
      },
    },
    {
      title: '车间位置',
      dataIndex: 'workshop',
      key: 'workshop',
      width: 120,
      render: (w: string | null) => w || '—',
    },
    {
      title: '负责人',
      dataIndex: 'heads',
      key: 'heads',
      width: 140,
      render: (heads: { name: string; feishu_open_id: string }[] | undefined) => {
        if (!heads || heads.length === 0) return <span style={{ color: '#a4a097' }}>—</span>
        return (
          <Space size={4} wrap>
            {heads.map((h, i) => (
              <Tag key={i} color="geekblue">{h.name}</Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '超出阈值',
      key: 'excess',
      width: 160,
      render: (_, record) => {
        const diff = record.trigger_value - record.threshold_value
        const pct = record.threshold_value > 0
          ? ((diff / record.threshold_value) * 100).toFixed(1)
          : '0.0'
        const sign = diff >= 0 ? '+' : ''
        const color = diff >= 0 ? '#cf1322' : '#1677ff'
        return (
          <span style={{ color }}>
            {sign}{diff.toLocaleString(undefined, { maximumFractionDigits: 2 })} {record.unit}（{sign}{pct}%）
          </span>
        )
      },
    },
    {
      title: '原因',
      dataIndex: 'reason',
      key: 'reason',
      width: 200,
      render: (reason: string | null, record) => {
        if (reason) {
          return (
            <Space size={4}>
              <span style={{ color: '#37352f' }}>{reason}</span>
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={() => openReasonModal(record)}
                style={{ padding: 0, height: 20 }}
              />
            </Space>
          )
        }
        return (
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openReasonModal(record)}
          >
            填写原因
          </Button>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (s: string) => {
        const { text, color } = statusLabels[s] || { text: s, color: 'default' }
        return <Tag color={color}>{text}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) => {
        if (record.status === 'processed' || record.status === 'ignored') {
          return <span style={{ color: '#a4a097' }}>—</span>
        }
        return (
          <Space>
            {canApprove && (
              <Popconfirm
                title="确定通过此预警？通过后将不再显示。"
                onConfirm={() => handleApprove(record.id)}
                okText="通过"
                cancelText="取消"
              >
                <Button type="link" icon={<CheckOutlined />} style={{ color: '#1aae39' }}>
                  通过
                </Button>
              </Popconfirm>
            )}
            {canReject && (
              <Popconfirm
                title="确定驳回？将重新飞书通知负责人。"
                onConfirm={() => handleReject(record.id)}
                okText="驳回"
                cancelText="取消"
              >
                <Button type="link" danger icon={<CloseOutlined />}>
                  驳回
                </Button>
              </Popconfirm>
            )}
          </Space>
        )
      },
    },
  ]

  return (
    <>
      <Table
        columns={columns}
        dataSource={data}
        loading={loading}
        rowKey="id"
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, s) => {
            if (s !== pageSize) {
              onPageChange(1, s)
            } else {
              onPageChange(p, s)
            }
          },
        }}
      />
      <Modal
        title="填写异常原因"
        open={reasonModalOpen}
        onOk={handleFillReason}
        onCancel={() => {
          setReasonModalOpen(false)
          setReasonRecordId(null)
          setReasonText('')
        }}
        confirmLoading={submitting}
        okText="提交"
        cancelText="取消"
        destroyOnHidden
      >
        <Input.TextArea
          value={reasonText}
          onChange={(e) => setReasonText(e.target.value)}
          placeholder="请输入能源异常消耗的原因..."
          rows={4}
          maxLength={500}
          showCount
        />
      </Modal>
    </>
  )
}
