'use client'

import { useEffect, useCallback } from 'react'
import { App, Button, Space, Table, Input } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ApartmentOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useInspectionStore } from '@/stores/inspection'
import { deleteInspectionRoute } from '@/actions/inspection'
import { fetchInspectionRoutes } from '@/lib/api/inspection'
import { statusPill, pillSuccess, pillNeutral, linkPurple, linkPrimary, linkDanger } from '@/components/equipment/shared-styles'
import type { InspectionRoute } from '@/types/inspection'
import type { InspectionTemplate } from '@/types/equipment'

interface Props {
  templates: InspectionTemplate[]
  equipments: { id: string; name: string; equipment_no: string }[]
}

export function InspectionRoutesTab({ templates, equipments }: Props) {
  const { message, modal } = App.useApp()
  const {
    routes, routesTotal, routesPage, routesPageSize, routesLoading, routesKeyword, routesRefreshKey,
    setRoutes, setRoutesTotal, setRoutesLoading, setRoutesPage, setRoutesPageSize, setRoutesKeyword,
    openRouteDrawer, openRouteEquipmentDrawer,
  } = useInspectionStore()

  const load = useCallback(async () => {
    setRoutesLoading(true)
    try {
      const res = await fetchInspectionRoutes({
        keyword: routesKeyword || undefined,
        page: routesPage, page_size: routesPageSize,
      })
      setRoutes(res.items); setRoutesTotal(res.total)
    } catch (err: unknown) {
      message.error((err as Error).message || '加载失败')
    } finally { setRoutesLoading(false) }
  }, [routesKeyword, routesPage, routesPageSize, routesRefreshKey, setRoutes, setRoutesTotal, setRoutesLoading, message])

  useEffect(() => { load() }, [load])

  const handleDelete = useCallback((r: InspectionRoute) => {
    modal.confirm({
      title: '删除路线',
      content: `确定要删除路线「${r.name}」吗？`,
      okText: '确认删除', cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try { await deleteInspectionRoute(r.id); message.success('已删除'); load() }
        catch (err: unknown) { message.error((err as Error).message || '删除失败') }
      },
    })
  }, [modal, message, load])

  const columns: ColumnsType<InspectionRoute> = [
    {
      title: '路线名称', dataIndex: 'name', width: 220,
      render: (n: string) => <span style={{ fontWeight: 600, fontSize: 14 }}>{n}</span>,
    },
    {
      title: '地点数', dataIndex: 'location_count', width: 80, align: 'center',
      render: (c: number) => <span style={{ fontWeight: 600, fontSize: 15, color: '#1a1a1a' }}>{c || 0}</span>,
    },
    {
      title: '周期', key: 'period', width: 120,
      render: (_: unknown, r: InspectionRoute) => {
        const v = r.period_value ? `每${r.period_value}` : ''
        return (
          <span style={{
            padding: '2px 10px', borderRadius: 4,
            fontSize: 12, fontWeight: 600, lineHeight: '20px',
            color: '#5645d4', background: '#e6e0f5',
          }}>
            {v}{r.period_type}
          </span>
        )
      },
    },
    {
      title: '设备数', dataIndex: 'equipment_count', width: 80, align: 'center',
      render: (c: number) => <span style={{ fontWeight: 600, fontSize: 15, color: '#1a1a1a' }}>{c || 0}</span>,
    },
    {
      title: '状态', dataIndex: 'is_active', width: 75,
      render: (v: boolean) => (
        <span style={v ? pillSuccess : pillNeutral}>{v ? '启用' : '停用'}</span>
      ),
    },
    {
      title: '操作', key: 'action', width: 190, fixed: 'end' as const,
      render: (_: unknown, r: InspectionRoute) => (
        <Space size={16}>
          <span role="button" onClick={() => openRouteEquipmentDrawer(r.id)} style={linkPurple}>
            <ApartmentOutlined />设备
          </span>
          <span role="button" onClick={() => openRouteDrawer(r)} style={linkPrimary}>
            <EditOutlined />编辑
          </span>
          <span role="button" onClick={() => handleDelete(r)} style={linkDanger}>
            <DeleteOutlined />删除
          </span>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Input.Search
          placeholder="搜索路线名称"
          allowClear
          style={{ width: 260 }}
          value={routesKeyword}
          onChange={e => setRoutesKeyword(e.target.value)}
          onSearch={v => setRoutesKeyword(v)}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => openRouteDrawer()}
          style={{
            borderRadius: 8, height: 36,
            background: '#5645d4', borderColor: '#5645d4',
            fontWeight: 600, fontSize: 13,
            boxShadow: 'none',
          }}
        >
          新建路线
        </Button>
      </div>

      <Table
        columns={columns} dataSource={routes} rowKey="id"
        size="small" loading={routesLoading} scroll={{ x: 'max-content' }}
        pagination={{
          current: routesPage, pageSize: routesPageSize, total: routesTotal,
          showSizeChanger: true, showQuickJumper: true,
          showTotal: t => <span style={{ color: '#a4a097', fontSize: 13 }}>共 {t} 条</span>,
          onChange: (p, s) => { setRoutesPage(p); setRoutesPageSize(s) },
        }}
        style={{ borderRadius: 0 }}
      />
    </div>
  )
}
