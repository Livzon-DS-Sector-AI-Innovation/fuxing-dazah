'use client'

import { useEffect, useState } from 'react'
import { Modal, Table, Input, Select, Button, Space, Tag, App } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { getHazardRiskOptions } from '@/actions/safety'
import type { HazardRiskOption } from '@/types/safety'
import { RISK_LEVEL_OPTIONS } from '@/types/safety'

interface HazardSelectModalProps {
  open: boolean
  onSelect: (hazard: HazardRiskOption) => void
  onClose: () => void
}

export default function HazardSelectModal({ open, onSelect, onClose }: HazardSelectModalProps) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<HazardRiskOption[]>([])
  const [total, setTotal] = useState(0)
  const [keyword, setKeyword] = useState('')
  const [department, setDepartment] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const { message } = App.useApp()

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await getHazardRiskOptions({ keyword: keyword || undefined, department, page, page_size: 20 })
      if (res.code === 200) {
        setData(res.data as HazardRiskOption[])
        setTotal(res.meta?.total || 0)
      }
    } catch {
      message.error('加载危险源列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) loadData()
  }, [open, page])

  const handleSearch = () => {
    setPage(1)
    loadData()
  }

  const columns: ColumnsType<HazardRiskOption> = [
    { title: '编号', dataIndex: 'hazard_id_no', key: 'hazard_id_no', width: 130 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 90, ellipsis: true },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 90, ellipsis: true },
    {
      title: '作业活动', dataIndex: 'specific_activity', key: 'specific_activity', width: 160, ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '风险等级', dataIndex: 'inherent_risk_label', key: 'inherent_risk_label', width: 100,
      render: (label: string, record) => {
        const opt = RISK_LEVEL_OPTIONS.find(o => o.value === record.inherent_risk_level)
        return <Tag color={opt?.color}>{label || record.inherent_risk_level || '-'}</Tag>
      },
    },
    {
      title: '', key: 'action', width: 60,
      render: (_, record) => (
        <Button type="primary" size="small" onClick={() => onSelect(record)}>选择</Button>
      ),
    },
  ]

  return (
    <Modal
      title="选择关联危险源"
      open={open}
      onCancel={onClose}
      footer={null}
      width={780}
      destroyOnHidden
    >
      <div style={{ marginBottom: 16 }}>
        <Space>
          <Input
            placeholder="搜索编号/部门/岗位/生产步骤"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 280 }}
            allowClear
          />
          <Input
            placeholder="部门"
            value={department}
            onChange={e => setDepartment(e.target.value || undefined)}
            onPressEnter={handleSearch}
            style={{ width: 140 }}
            allowClear
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
        </Space>
      </div>

      <div style={{ color: '#787671', fontSize: 13, marginBottom: 12 }}>
        仅列出风险等级为"重大风险(level_1)"和"较大风险(level_2)"的已完成危险源辨识项
      </div>

      <Table
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{
          current: page,
          pageSize: 20,
          total,
          showTotal: t => `共 ${t} 条`,
          showSizeChanger: false,
          onChange: p => setPage(p),
        }}
      />
    </Modal>
  )
}
