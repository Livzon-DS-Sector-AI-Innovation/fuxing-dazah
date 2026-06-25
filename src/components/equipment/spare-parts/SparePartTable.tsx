'use client'

import { useCallback } from 'react'
import { App, Table, Button, Space, Input, Badge } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ImportOutlined, WarningOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { SparePart } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteSparePart } from '@/actions/equipment'
import { pillSuccess, pillNeutral, actionLink, linkPrimary, linkDanger, linkPurple } from '@/components/equipment/shared/shared-styles'

interface Props { onRefresh?: () => void }

export function SparePartTable({ onRefresh }: Props) {
  const { message, modal } = App.useApp()
  const {
    spareParts, sparePartTotal, sparePartPage, sparePartPageSize,
    sparePartLoading, sparePartKeyword,
    setSparePartPage, setSparePartPageSize, setSparePartKeyword,
    openSparePartDrawer, openStockInboundDrawer, stockWarnings,
  } = useEquipmentStore()

  const handleDelete = useCallback((record: SparePart) => {
    modal.confirm({
      title: '确认删除', content: '确定要删除此备件吗？',
      okText: '确认', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try { await deleteSparePart(record.id); message.success('删除成功'); onRefresh?.() }
        catch (error: any) { message.error(error?.message || '删除失败') }
      },
    })
  }, [modal, message, onRefresh])

  const columns: ColumnsType<SparePart> = [
    { title: '编码', dataIndex: 'code', key: 'code', width: 120 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
    { title: '规格型号', dataIndex: 'specification', key: 'specification', width: 150, render: (t: string | null) => t || '-' },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 80 },
    { title: '分类', dataIndex: 'category', key: 'category', width: 100, render: (t: string | null) => t || '-' },
    { title: '默认供应商', dataIndex: 'default_supplier', key: 'default_supplier', width: 140, render: (t: string | null) => t || '-' },
    { title: '单价', dataIndex: 'unit_price', key: 'unit_price', width: 100, align: 'right', render: (p: number | null) => p != null ? `¥${p.toFixed(2)}` : '-' },
    {
      title: '库存数量', dataIndex: 'current_qty', key: 'current_qty', width: 100, align: 'right',
      render: (qty: number, r) => (
        <span style={{ color: qty <= r.min_qty ? '#e03131' : '#1a1a1a', fontWeight: qty <= r.min_qty ? 600 : 400 }}>{qty}</span>
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 80,
      render: (v: boolean) => <span style={v ? pillSuccess : pillNeutral}>{v ? '启用' : '停用'}</span>,
    },
    {
      title: '操作', key: 'action', width: 180, fixed: 'end',
      render: (_: unknown, r: SparePart) => (
        <Space size={12}>
          <span role="button" onClick={() => openStockInboundDrawer(r.id)} style={linkPurple}><ImportOutlined />入库</span>
          <span role="button" onClick={() => openSparePartDrawer(r)} style={linkPrimary}><EditOutlined />编辑</span>
          <span role="button" onClick={() => handleDelete(r)} style={linkDanger}><DeleteOutlined />删除</span>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Input.Search placeholder="搜索备件名称/编码" allowClear style={{ width: 240 }}
            value={sparePartKeyword || undefined} onSearch={v => setSparePartKeyword(v)} />
          {stockWarnings.length > 0 && (
            <Badge count={stockWarnings.length} offset={[-4, 0]}>
              <Button icon={<WarningOutlined />} style={{ color: '#dd5b00', borderColor: '#dd5b00' }}>库存预警</Button>
            </Badge>
          )}
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openSparePartDrawer()}>新建备件</Button>
      </div>
      <Table columns={columns} dataSource={spareParts} rowKey="id" size="small" loading={sparePartLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: sparePartPage, pageSize: sparePartPageSize, total: sparePartTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { if (s !== sparePartPageSize) { setSparePartPageSize(s) } else { setSparePartPage(p) } },
        }} />
    </div>
  )
}
