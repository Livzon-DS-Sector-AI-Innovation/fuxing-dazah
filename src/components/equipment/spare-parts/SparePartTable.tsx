'use client'

import { useCallback } from 'react'
import { App, Table, Button, Space, Input, Tag } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined, ImportOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { SparePart } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteSparePart } from '@/actions/equipment'
import { linkPrimary, linkDanger, linkPurple } from '@/components/equipment/shared/shared-styles'
import { usePermission } from '@/hooks/usePermission'

interface Props { onRefresh?: () => void }

export function SparePartTable({ onRefresh }: Props) {
  const { message, modal } = App.useApp()
  const {
    spareParts, sparePartTotal, sparePartPage, sparePartPageSize,
    sparePartLoading, sparePartKeyword,
    setSparePartPage, setSparePartPageSize, setSparePartKeyword,
    openSparePartDrawer, openSparePartEquipmentDrawer, openStockInboundDrawer,
  } = useEquipmentStore()
  const { hasPermission } = usePermission()

  const handleDelete = useCallback((record: SparePart) => {
    modal.confirm({
      title: '确认删除', content: '确定要删除此备件吗？',
      okText: '确认', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteSparePart(record.id)
        if (!result.success) { message.error(result.error); return }
        message.success('删除成功')
        onRefresh?.()
      },
    })
  }, [modal, message, onRefresh])

  const columns: ColumnsType<SparePart> = [
    { title: '编码', dataIndex: 'code', key: 'code', width: 120,
      render: (v: string) => (
        <span style={{ fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, color: '#5d5b54' }}>{v}</span>
      ),
    },
    { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
    { title: '规格型号', dataIndex: 'specification', key: 'specification', width: 150, render: (t: string | null) => t || '-' },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 60 },
    { title: '分类', dataIndex: 'category', key: 'category', width: 80, render: (t: string | null) => t || '-' },
    { title: '默认供应商', dataIndex: 'default_supplier', key: 'default_supplier', width: 140, render: (t: string | null) => t || '-' },
    { title: '单价', dataIndex: 'unit_price', key: 'unit_price', width: 80, align: 'right', render: (p: number | null) => p != null ? `¥${p.toFixed(2)}` : '-' },
    {
      title: '库存数量', dataIndex: 'current_qty', key: 'current_qty', width: 80, align: 'right',
      render: (qty: number | undefined) => (
        <span style={{ fontWeight: 500, color: qty != null && qty > 0 ? '#1a1a1a' : '#a4a097' }}>
          {qty != null ? qty : '-'}
        </span>
      ),
    },
    {
      title: '适用范围', dataIndex: 'equipment_count', key: 'equipment_count', width: 110,
      render: (count: number) =>
        count === 0
          ? <Tag color="blue">全部设备</Tag>
          : <Tag color="orange">{count} 台设备</Tag>,
    },
    {
      title: '操作', key: 'action', width: 220, fixed: 'end',
      render: (_: unknown, r: SparePart) => (
        <Space size={12}>
          {hasPermission('equipment:spare_part:update') && (
            <span role="button" onClick={() => openStockInboundDrawer(r.id)} style={linkPurple}><ImportOutlined /> 入库</span>
          )}
          {hasPermission('equipment:spare_part:update') && (
            <span role="button" onClick={() => openSparePartEquipmentDrawer(r)} style={linkPurple}><SettingOutlined /> 关联设备</span>
          )}
          {hasPermission('equipment:spare_part:update') && (
            <span role="button" onClick={() => openSparePartDrawer(r)} style={linkPrimary}><EditOutlined /> 编辑</span>
          )}
          {hasPermission('equipment:spare_part:delete') && (
            <span role="button" onClick={() => handleDelete(r)} style={linkDanger}><DeleteOutlined />删除</span>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* ── 工具栏：搜索 + 新建 ── */}
      <div style={{
        marginBottom: 16, display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', gap: 12,
      }}>
        <Input.Search
          placeholder="搜索备件名称或编码"
          allowClear
          style={{ width: 280 }}
          value={sparePartKeyword || undefined}
          onSearch={v => setSparePartKeyword(v)}
        />
        {hasPermission('equipment:spare_part:create') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openSparePartDrawer()}>
            新建备件
          </Button>
        )}
      </div>

      {/* ── 表格 ── */}
      <Table
        columns={columns}
        dataSource={spareParts}
        rowKey="id"
        size="small"
        loading={sparePartLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: sparePartPage,
          pageSize: sparePartPageSize,
          total: sparePartTotal,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => {
            if (s !== sparePartPageSize) { setSparePartPageSize(s) } else { setSparePartPage(p) }
          },
        }}
      />
    </div>
  )
}
