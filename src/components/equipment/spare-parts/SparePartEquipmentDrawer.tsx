'use client'

import { useEffect, useState, useCallback } from 'react'
import { App, Drawer, Select, InputNumber, Button, Table, Popconfirm } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { useEquipmentStore } from '@/stores/equipment'
import { linkEquipmentToSparePart, unlinkEquipmentFromSparePart } from '@/actions/equipment'
import { EquipmentSparePartLink } from '@/types/equipment'
import { fetchSparePartEquipmentsClient, fetchEquipmentsClient } from '@/lib/api/equipment-client'

interface Props { onRefresh?: () => void }

export function SparePartEquipmentDrawer({ onRefresh }: Props) {
  const { message } = App.useApp()
  const { sparePartEquipmentDrawerOpen, equipmentManagingSparePart, closeSparePartEquipmentDrawer } = useEquipmentStore()

  const [linkedEquipments, setLinkedEquipments] = useState<EquipmentSparePartLink[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [linkingQuantity, setLinkingQuantity] = useState(1)
  const [linkingLoading, setLinkingLoading] = useState(false)
  const [options, setOptions] = useState<{ value: string; label: string }[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')

  useEffect(() => {
    if (sparePartEquipmentDrawerOpen && equipmentManagingSparePart) {
      fetchSparePartEquipmentsClient(equipmentManagingSparePart.id)
        .then(setLinkedEquipments)
        .catch(() => setLinkedEquipments([]))
      fetchEquipmentsClient({ page: 1, page_size: 20 })
        .then(res => setOptions(res.items.map(e => ({
          value: e.id,
          label: `${e.equipment_no} - ${e.name}`,
        }))))
        .catch(() => setOptions([]))
      setSelectedIds([])
      setLinkingQuantity(1)
      setSearchKeyword('')
    }
  }, [sparePartEquipmentDrawerOpen, equipmentManagingSparePart])

  const handleSearch = useCallback(async (keyword: string) => {
    setSearchKeyword(keyword)
    setSearchLoading(true)
    try {
      const result = await fetchEquipmentsClient({ keyword: keyword || undefined, page: 1, page_size: 20 })
      setOptions(result.items.map(e => ({
        value: e.id,
        label: `${e.equipment_no} - ${e.name}`,
      })))
    } catch {
      setOptions([])
    } finally {
      setSearchLoading(false)
    }
  }, [])

  const handleLink = async () => {
    if (selectedIds.length === 0 || !equipmentManagingSparePart) return
    setLinkingLoading(true)
    const results = await Promise.allSettled(
      selectedIds.map(id =>
        linkEquipmentToSparePart(equipmentManagingSparePart.id, {
          equipment_id: id,
          quantity: linkingQuantity,
        })
      )
    )
    setLinkingLoading(false)
    // 先清除选择状态，避免刷新期间重复提交
    setSelectedIds([])
    setLinkingQuantity(1)
    setSearchKeyword('')
    // 刷新已关联列表（即使部分失败也刷新，展示已成功关联的设备）
    try {
      const links = await fetchSparePartEquipmentsClient(equipmentManagingSparePart.id)
      setLinkedEquipments(links)
    } catch { /* ignore */ }
    // 报告失败项
    const failures = results
      .map((r, i) => (r.status === 'rejected' || !r.value.success ? selectedIds[i] : null))
      .filter(Boolean)
    if (failures.length > 0) {
      message.warning(`${failures.length} 台设备关联失败，其余已成功`)
    }
    onRefresh?.()
  }

  const handleUnlink = async (linkId: string) => {
    if (!equipmentManagingSparePart) return
    const result = await unlinkEquipmentFromSparePart(equipmentManagingSparePart.id, linkId)
    if (result.success) {
      setLinkedEquipments(prev => prev.filter(l => l.id !== linkId))
      onRefresh?.()
    }
  }

  return (
    <Drawer
      title={`关联设备 — ${equipmentManagingSparePart?.name || ''}`}
      size={560}
      open={sparePartEquipmentDrawerOpen}
      onClose={closeSparePartEquipmentDrawer}
      destroyOnHidden
      styles={{ body: { padding: '16px 24px' } }}
    >
      <div style={{
        background: '#f6f5f4',
        borderRadius: 12,
        padding: 16,
        marginBottom: 20,
      }}>
        <div style={{
          fontSize: 11, fontWeight: 600, color: '#a4a097',
          textTransform: 'uppercase', letterSpacing: 1,
          marginBottom: 12,
        }}>
          添加关联设备
        </div>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6 }}>设备（可多选）</div>
          <Select
            mode="multiple"
            placeholder="搜索设备编号或名称"
            allowClear
            showSearch
            style={{ width: '100%' }}
            value={selectedIds}
            onChange={(v) => setSelectedIds(v)}
            onClear={() => setSearchKeyword('')}
            onSearch={(v) => handleSearch(v)}
            filterOption={false}
            loading={searchLoading}
            notFoundContent={searchLoading ? '搜索中...' : searchKeyword ? '无匹配设备' : '输入关键词搜索'}
            options={options.filter(
              opt => !linkedEquipments.some(link => link.equipment_id === opt.value)
            )}
          />
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <div style={{ width: 88 }}>
            <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6 }}>数量</div>
            <InputNumber
              min={1}
              value={linkingQuantity}
              onChange={(v) => setLinkingQuantity(v || 1)}
              style={{ width: '100%' }}
              placeholder="数量"
            />
          </div>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            loading={linkingLoading}
            onClick={handleLink}
            disabled={selectedIds.length === 0}
          >
            添加
          </Button>
        </div>
      </div>

      <div style={{
        fontSize: 11, fontWeight: 600, color: '#a4a097',
        textTransform: 'uppercase', letterSpacing: 1,
        marginBottom: 12,
      }}>
        已关联设备 · {linkedEquipments.length}
      </div>
      <Table
        columns={[
          { title: '设备编号', dataIndex: 'equipment_no', key: 'equipment_no', width: 140,
            render: (v: string | null) => v ? (
              <span style={{ fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, color: '#5d5b54' }}>{v}</span>
            ) : '-',
          },
          { title: '设备名称', dataIndex: 'equipment_name', key: 'equipment_name', ellipsis: true,
            render: (v: string | null) => v || '-',
          },
          { title: '数量', dataIndex: 'quantity', key: 'quantity', width: 80, align: 'center' },
          {
            title: '', key: 'action', width: 60,
            render: (_: unknown, link: EquipmentSparePartLink) => (
              <Popconfirm title="确定解绑此设备？" onConfirm={() => handleUnlink(link.id)}>
                <Button type="link" danger size="small" icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
        dataSource={linkedEquipments}
        rowKey="id"
        size="small"
        pagination={false}
        locale={{ emptyText: '暂无关联设备，请在上方搜索并添加' }}
      />
    </Drawer>
  )
}
