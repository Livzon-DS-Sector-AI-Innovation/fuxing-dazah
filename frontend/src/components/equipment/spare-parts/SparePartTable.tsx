'use client'

import { useCallback } from 'react'
import { App, Table, Button, Space, Input, Tag, Select, Dropdown, Progress } from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined, ImportOutlined,
  ExportOutlined, AuditOutlined, MoreOutlined, StopOutlined, PlayCircleOutlined,
  FileSearchOutlined, ControlOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { MenuProps } from 'antd'
import { SparePart } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteSparePart, updateSparePart } from '@/actions/equipment'
import { linkPrimary, linkDanger, linkPurple } from '@/components/equipment/shared/shared-styles'
import { usePermission } from '@/hooks/usePermission'

interface Props {
  onRefresh?: () => void
  onImportClick?: () => void
  onViewTransactions?: (sparePartId: string) => void
}

export function SparePartTable({ onRefresh, onImportClick, onViewTransactions }: Props) {
  const { message, modal } = App.useApp()
  const {
    spareParts, sparePartTotal, sparePartPage, sparePartPageSize,
    sparePartLoading, sparePartKeyword,
    sparePartStatusFilter, sparePartLowStockFilter,
    setSparePartPage, setSparePartPageSize, setSparePartKeyword,
    setSparePartStatusFilter, setSparePartLowStockFilter,
    openSparePartDrawer, openSparePartEquipmentDrawer, openStockInboundDrawer,
    openStockOutboundDrawer, openStockAdjustDrawer, openStockSettingsDrawer,
  } = useEquipmentStore()
  const { hasPermission } = usePermission()
  const canUpdate = hasPermission('equipment:spare_part:update')

  const handleDelete = useCallback((record: SparePart) => {
    modal.confirm({
      title: '确认删除',
      content: '确定要删除此备件吗？库存需先盘点归零，关联设备将一并解除。',
      okText: '确认', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteSparePart(record.id)
        if (!result.success) { message.error(result.error); return }
        message.success('删除成功')
        onRefresh?.()
      },
    })
  }, [modal, message, onRefresh])

  const handleToggleActive = useCallback(async (record: SparePart) => {
    const next = !record.is_active
    const result = await updateSparePart(record.id, { is_active: next })
    if (!result.success) { message.error(result.error); return }
    message.success(next ? '已启用' : '已停用')
    onRefresh?.()
  }, [message, onRefresh])

  const columns: ColumnsType<SparePart> = [
    { title: '编码', dataIndex: 'code', key: 'code', width: 120,
      render: (v: string) => (
        <span style={{ fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, color: '#5d5b54' }}>{v}</span>
      ),
    },
    { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
    { title: '规格型号', dataIndex: 'specification', key: 'specification', width: 140, render: (t: string | null) => t || '-' },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 55 },
    { title: '分类', dataIndex: 'category', key: 'category', width: 80, render: (t: string | null) => t || '-' },
    { title: '供应商', dataIndex: 'default_supplier', key: 'default_supplier', width: 120, ellipsis: true, render: (t: string | null) => t || '-' },
    { title: '单价', dataIndex: 'unit_price', key: 'unit_price', width: 80, align: 'right', render: (p: number | null) => p != null ? `¥${p.toFixed(2)}` : '-' },
    {
      title: '库存（当前/安全）', key: 'stock', width: 150,
      render: (_: unknown, r: SparePart) => {
        const available = r.current_qty - (r.reserved_qty || 0)
        const low = r.is_low_stock
        return (
          <div style={{ minWidth: 110 }}>
            <Space size={4}>
              <span style={{ fontWeight: 600, color: low ? '#e03131' : (r.current_qty > 0 ? '#1a1a1a' : '#a4a097') }}>
                {r.current_qty}
              </span>
              <span style={{ color: '#a4a097', fontSize: 12 }}>/ {r.safety_qty || 0}</span>
              {r.reserved_qty > 0 && (
                <Tag style={{ fontSize: 11, lineHeight: '16px', marginInlineEnd: 0 }} title={`待验收工单占用 ${r.reserved_qty}，可用 ${available}`}>
                  占 {r.reserved_qty}
                </Tag>
              )}
            </Space>
            {r.safety_qty > 0 && (
              <Progress
                percent={Math.min(100, Math.round((r.current_qty / r.safety_qty) * 100))}
                showInfo={false}
                size={[104, 4]}
                strokeColor={low ? '#e03131' : '#4096ff'}
                style={{ marginBottom: 0 }}
              />
            )}
          </div>
        )
      },
    },
    { title: '库位', dataIndex: 'warehouse_location', key: 'warehouse_location', width: 80, render: (t: string | null) => t || '-' },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 70,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '适用范围', dataIndex: 'equipment_count', key: 'equipment_count', width: 100,
      render: (count: number) =>
        count === 0
          ? <Tag color="blue">全部设备</Tag>
          : <Tag color="orange">{count} 台设备</Tag>,
    },
    {
      title: '操作', key: 'action', width: 250, fixed: 'end',
      render: (_: unknown, r: SparePart) => {
        const moreItems: MenuProps['items'] = [
          canUpdate && {
            key: 'link', icon: <SettingOutlined />, label: '关联设备',
            onClick: () => openSparePartEquipmentDrawer(r),
          },
          canUpdate && {
            key: 'settings', icon: <ControlOutlined />, label: '库存设置',
            onClick: () => openStockSettingsDrawer(r),
          },
          {
            key: 'transactions', icon: <FileSearchOutlined />, label: '查看流水',
            onClick: () => onViewTransactions?.(r.id),
          },
          canUpdate && { type: 'divider' } as const,
          canUpdate && {
            key: 'edit', icon: <EditOutlined />, label: '编辑',
            onClick: () => openSparePartDrawer(r),
          },
          canUpdate && {
            key: 'toggle', icon: r.is_active ? <StopOutlined /> : <PlayCircleOutlined />,
            label: r.is_active ? '停用' : '启用',
            onClick: () => handleToggleActive(r),
          },
          hasPermission('equipment:spare_part:delete') && { type: 'divider' } as const,
          hasPermission('equipment:spare_part:delete') && {
            key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除',
            onClick: () => handleDelete(r),
          },
        ].filter((item): item is Exclude<typeof item, false> => Boolean(item))
        return (
          <Space size={12}>
            {canUpdate && (
              <span role="button" onClick={() => openStockInboundDrawer(r.id)} style={linkPurple}><ImportOutlined /> 入库</span>
            )}
            {canUpdate && (
              <span role="button" onClick={() => openStockOutboundDrawer(r.id)} style={linkDanger}><ExportOutlined /> 出库</span>
            )}
            {canUpdate && (
              <span role="button" onClick={() => openStockAdjustDrawer(r.id)} style={linkPrimary}><AuditOutlined /> 盘点</span>
            )}
            <Dropdown menu={{ items: moreItems }} trigger={['click']}>
              <span role="button" style={linkPrimary}>更多 <MoreOutlined /></span>
            </Dropdown>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      {/* ── 工具栏：筛选 + 新建 ── */}
      <div style={{
        marginBottom: 16, display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索备件名称或编码"
            allowClear
            style={{ width: 240 }}
            value={sparePartKeyword || undefined}
            onSearch={v => setSparePartKeyword(v)}
          />
          <Select
            placeholder="全部状态"
            allowClear
            style={{ width: 100 }}
            value={sparePartStatusFilter}
            onChange={v => setSparePartStatusFilter(v)}
            options={[
              { label: '启用', value: 'active' },
              { label: '停用', value: 'inactive' },
            ]}
          />
          <Select
            placeholder="全部库存"
            allowClear
            style={{ width: 110 }}
            value={sparePartLowStockFilter}
            onChange={v => setSparePartLowStockFilter(v)}
            options={[{ label: '低于安全线', value: 'low' }]}
          />
        </Space>
        <Space>
          {onImportClick && hasPermission('equipment:spare_part:update') && hasPermission('equipment:spare_part:create') && (
            <Button icon={<ImportOutlined />} onClick={onImportClick}>导入</Button>
          )}
          {hasPermission('equipment:spare_part:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openSparePartDrawer()}>
              新建备件
            </Button>
          )}
        </Space>
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
