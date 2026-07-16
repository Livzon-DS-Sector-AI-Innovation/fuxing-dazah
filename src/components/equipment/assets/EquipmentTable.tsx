'use client'

import { useCallback, useState, useEffect, useRef } from 'react'
import { App, Table, Space, Input, Select, Button } from 'antd'
import { EditOutlined, DeleteOutlined, SearchOutlined, ToolOutlined, PlusOutlined, ImportOutlined, EyeOutlined } from '@ant-design/icons'
import { Equipment } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteEquipment } from '@/actions/equipment'
import { EQUIP_STATUS_PILL_COLORS, RUNNING_STATUS_PILL_COLORS, statusPill, linkDanger, linkPrimary, linkWarning, pillPurple, pillNeutral } from '@/components/equipment/shared/shared-styles'
import { EquipmentDetailDrawer } from './EquipmentDetailDrawer'
import { usePermission } from '@/hooks/usePermission'

const statusPillMap: Record<string, React.CSSProperties> = Object.fromEntries(
  Object.entries(EQUIP_STATUS_PILL_COLORS).map(([k, v]) => [k, statusPill(v.color, v.bg)])
)

const runningStatusPillMap: Record<string, React.CSSProperties> = Object.fromEntries(
  Object.entries(RUNNING_STATUS_PILL_COLORS).map(([k, v]) => [k, statusPill(v.color, v.bg)])
)

const statusOptions = Object.keys(EQUIP_STATUS_PILL_COLORS).map(value => ({ label: value, value }))

const IMPORTANCE_PILL_MAP: Record<string, React.CSSProperties> = {
  '高': pillPurple, '中': pillNeutral, '低': pillNeutral,
}

interface EquipmentTableProps {
  loading?: boolean
  onPageChange: (page: number, pageSize: number) => void
  onImportClick?: () => void
  /** 变化时重置分页到第一页 */
  resetKey: number
}


export function EquipmentTable({ loading = false, onPageChange, onImportClick, resetKey }: EquipmentTableProps) {
  const { message, modal } = App.useApp()
  const {
    equipments, total,
    statusFilter, keyword,
    departments, departmentFilter, setDepartmentFilter,
    setStatusFilter, setKeyword,
    openEquipmentDrawer, openRepairDrawer,
  } = useEquipmentStore()

  const { hasPermission } = usePermission()

  // 本地分页
  const [localPage, setLocalPage] = useState(1)
  const [localPageSize, setLocalPageSize] = useState(20)

  // resetKey 变化 → 重置到第一页
  useEffect(() => {
    setLocalPage(1)
  }, [resetKey])

  const [detailOpen, setDetailOpen] = useState(false)
  const [detailEquipment, setDetailEquipment] = useState<Equipment | null>(null)

  // 动态计算 scroll.y，使表头和筛选栏固定，仅表格数据行滚动
  const rootRef = useRef<HTMLDivElement>(null)
  const filterRef = useRef<HTMLDivElement>(null)
  const tableWrapRef = useRef<HTMLDivElement>(null)
  const [scrollY, setScrollY] = useState<number>(0)

  useEffect(() => {
    const tableWrap = tableWrapRef.current
    if (!tableWrap) return
    const observer = new ResizeObserver(() => {
      const h = tableWrap.clientHeight
      // 减去表头（small size 约 37px）和分页栏（约 56px）
      const y = h - 37 - 56
      setScrollY(y > 80 ? y : 80)
    })
    observer.observe(tableWrap)
    return () => observer.disconnect()
  }, [])


  const handleDelete = useCallback((record: Equipment) => {
    modal.confirm({
      title: '确认删除', content: `确定要删除设备 "${record.name}" 吗？`,
      okText: '确认', cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteEquipment(record.id)
        if (!result.success) {
          message.error(result.error)
          return
        }
        message.success('删除设备成功')
        onPageChange(localPage, localPageSize)
      },
    })
  }, [modal, message, onPageChange, localPage, localPageSize])

  const columns = [
    { title: '设备编号', dataIndex: 'equipment_no', key: 'equipment_no', width: 140, fixed: 'start' as const },
    { title: '设备名称', dataIndex: 'name', key: 'name', width: 180, fixed: 'start' as const, ellipsis: true },
    { title: '设备分类', dataIndex: 'category_names', key: 'category', width: 150, render: (n: string | null) => n || '-' },
    { title: '设备位置', dataIndex: 'location_name', key: 'location', width: 120, render: (n: string | null) => n || '-' },
    { title: '归属部门', dataIndex: 'department_name', key: 'department', width: 120,
      render: (v: string | null) => v || '-' },
    { title: '负责人', dataIndex: 'responsible_person_name', key: 'responsible', width: 100,
      render: (v: string | null) => v || '-' },
    { title: '设备状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => <span style={statusPillMap[s] || pillNeutral}>{s}</span> },
    { title: '运行状态', dataIndex: 'running_status', key: 'running_status', width: 90,
      render: (s: string) => <span style={runningStatusPillMap[s] || pillNeutral}>{s}</span> },
    { title: '重要性', dataIndex: 'importance', key: 'importance', width: 80,
      render: (v: string) => <span style={IMPORTANCE_PILL_MAP[v] || pillNeutral}>{v}</span> },
    { title: '型号', dataIndex: 'model', key: 'model', width: 140, ellipsis: true },
    { title: '供应商', dataIndex: 'supplier', key: 'supplier', width: 150, ellipsis: true },
    { title: '投用日期', dataIndex: 'commissioning_date', key: 'commissioning_date', width: 120 },
    { title: '操作', key: 'action', width: 240, fixed: 'end' as const,
      render: (_: unknown, record: Equipment) => (
        <Space size={8}>
          <span role="button" onClick={() => { setDetailEquipment(record); setDetailOpen(true) }} style={linkPrimary}><EyeOutlined />详情</span>
          {hasPermission('equipment:maintenance:create') && (
            <span role="button" onClick={() => openRepairDrawer(record.id)} style={linkWarning}><ToolOutlined />报修</span>
          )}
          {hasPermission('equipment:asset:update') && (
            <span role="button" onClick={() => openEquipmentDrawer(record)} style={linkPrimary}><EditOutlined />编辑</span>
          )}
          {hasPermission('equipment:asset:delete') && (
            <span role="button" onClick={() => handleDelete(record)} style={linkDanger}><DeleteOutlined />删除</span>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div ref={rootRef} style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div ref={filterRef} style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center', flexShrink: 0 }}>
        <Select placeholder="设备状态" allowClear style={{ width: 120 }}
          value={statusFilter || undefined} onChange={(v) => setStatusFilter(v || '')} options={statusOptions} />
        <Select
          placeholder="归属部门"
          allowClear
          style={{ width: 140 }}
          value={departmentFilter || undefined}
          onChange={(v) => setDepartmentFilter(v || null)}
          options={departments.map(d => ({ label: d.name, value: d.id }))}
        />
        <Input placeholder="搜索设备编号或名称" prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
          style={{ width: 240 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} allowClear />
        <div style={{ flex: 1 }} />
        {hasPermission('equipment:asset:import') && (
          <Button icon={<ImportOutlined />} onClick={onImportClick}>导入</Button>
        )}
        {hasPermission('equipment:asset:create') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEquipmentDrawer()}>新增设备</Button>
        )}
      </div>
      <div ref={tableWrapRef} style={{ flex: 1, minHeight: 0 }}>
        <Table
          columns={columns} dataSource={equipments} rowKey="id" size="small"
          loading={loading} scroll={{ x: 'max-content', y: scrollY || undefined }}
          pagination={{
            current: localPage,
            pageSize: localPageSize,
            total: total,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setLocalPage(p)
              if (ps !== localPageSize) setLocalPageSize(ps)
              onPageChange(p, ps)
            },
          }}
        />
      </div>
      <EquipmentDetailDrawer
        open={detailOpen} equipment={detailEquipment}
        categoryName={detailEquipment?.category_names || ''}
        locationName={detailEquipment?.location_name || ''}
        onClose={() => { setDetailOpen(false); setDetailEquipment(null) }}
      />
    </div>
  )
}
