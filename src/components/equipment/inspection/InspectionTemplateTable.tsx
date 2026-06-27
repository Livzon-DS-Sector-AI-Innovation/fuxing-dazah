'use client'

import { useCallback } from 'react'
import { App, Table, Space, Input } from 'antd'
import { EditOutlined, DeleteOutlined, UnorderedListOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { InspectionTemplate } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteInspectionTemplate } from '@/actions/equipment'
import { pillSuccess, pillNeutral, linkPrimary, linkDanger, linkPurple } from '@/components/equipment/shared/shared-styles'
import { usePermission } from '@/hooks/usePermission'

interface Props { onRefresh?: () => void; categories: { id: string; name: string }[] }

export function InspectionTemplateTable({ onRefresh, categories }: Props) {
  const { hasPermission } = usePermission()
  const { message, modal } = App.useApp()
  const {
    inspectionTemplates, inspectionTemplateTotal, inspectionTemplatePage, inspectionTemplatePageSize,
    inspectionTemplateLoading, inspectionTemplateKeyword,
    setInspectionTemplatePage, setInspectionTemplatePageSize, setInspectionTemplateKeyword,
    openInspectionTemplateDrawer, openInspectionItemDrawer,
  } = useEquipmentStore()

  const handleDelete = useCallback((r: InspectionTemplate) => {
    modal.confirm({
      title: '确认删除', content: '确定要删除此巡检模板吗？',
      okText: '确认', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try { await deleteInspectionTemplate(r.id); message.success('删除成功'); onRefresh?.() }
        catch (error: any) { message.error(error?.message || '删除失败') }
      },
    })
  }, [modal, message, onRefresh])

  const columns: ColumnsType<InspectionTemplate> = [
    { title: '模板名称', dataIndex: 'name', key: 'name', width: 180 },
    { title: '设备分类', dataIndex: 'equipment_category_name', key: 'equipment_category_name', width: 140, render: (n: string | undefined) => n || '-' },
    { title: '描述', dataIndex: 'description', key: 'description', width: 200, render: (d: string | null) => d || '-' },
    { title: '检查项数', dataIndex: 'items_count', key: 'items_count', width: 100 },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 80,
      render: (v: boolean) => <span style={v ? pillSuccess : pillNeutral}>{v ? '启用' : '停用'}</span>,
    },
    {
      title: '操作', key: 'action', width: 220, fixed: 'end',
      render: (_: unknown, r: InspectionTemplate) => (
        <Space size={12}>
          {hasPermission('equipment:inspection:update') && (
          <span role="button" onClick={() => openInspectionItemDrawer(r.id)} style={linkPurple}><UnorderedListOutlined />检查项</span>
          )}
          {hasPermission('equipment:inspection:update') && (
          <span role="button" onClick={() => openInspectionTemplateDrawer(r)} style={linkPrimary}><EditOutlined />编辑</span>
          )}
          {hasPermission('equipment:inspection:delete') && (
          <span role="button" onClick={() => handleDelete(r)} style={linkDanger}><DeleteOutlined />删除</span>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-start', alignItems: 'center' }}>
        <Input.Search placeholder="搜索模板名称" allowClear style={{ width: 240 }}
          value={inspectionTemplateKeyword} onSearch={v => setInspectionTemplateKeyword(v)} />
      </div>
      <Table columns={columns} dataSource={inspectionTemplates} rowKey="id" size="small" loading={inspectionTemplateLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: inspectionTemplatePage, pageSize: inspectionTemplatePageSize, total: inspectionTemplateTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { if (s !== inspectionTemplatePageSize) { setInspectionTemplatePageSize(s) } else { setInspectionTemplatePage(p) } },
        }} />
    </div>
  )
}
