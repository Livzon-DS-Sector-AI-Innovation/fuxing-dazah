'use client'

import { useState } from 'react'
import { App, Button, Empty, Form, Input, Modal, Select, Tag, Typography } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, TeamOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { UserSelect } from '@/components/shared'
import { fetchIdentityPersonnel } from '@/lib/api/identity'
import { fetchProductsClient } from '@/lib/api/production-client'
import {
  fetchLines,
  createLine,
  updateLine,
  deleteLine,
  fetchLineAssignments,
  bindLineAssignment,
  unbindLineAssignment,
  fetchLineProducts,
  bindLineProduct,
  unbindLineProduct,
} from '@/actions/production'
import type { Line } from '@/types/production'

const { Text } = Typography

// ── 产线表单弹窗 ──

function LineFormModal({
  open,
  editItem,
  onClose,
  onSaved,
}: {
  open: boolean
  editItem: Line | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const result = editItem
      ? await updateLine(editItem.id, values)
      : await createLine(values)
    if (result.success) {
      message.success(editItem ? '产线已更新' : '产线已创建')
      onSaved()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={editItem ? '编辑产线' : '新增产线'}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={editItem ?? { name: '', remark: '' }}
      >
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input maxLength={200} placeholder="如：一号线、西区生产线" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="产线说明（可选）" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 人员绑定区（卡片内嵌） ──

function LineBindArea({ lineId, canManage }: { lineId: string; canManage: boolean }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)

  const { data: bindings } = useQuery({
    queryKey: ['production-line-bindings', lineId],
    queryFn: async () => {
      const r = await fetchLineAssignments(lineId)
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data ?? []
    },
  })

  const { data: personnelData } = useQuery({
    queryKey: ['identity-personnel'],
    queryFn: () => fetchIdentityPersonnel({ limit: 9999 }),
    staleTime: 5 * 60 * 1000,
  })
  const getUserName = (userId: string) =>
    personnelData?.items?.find(p => p.id === userId)?.name ?? userId.slice(0, 8)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['production-line-bindings', lineId] })
    queryClient.invalidateQueries({ queryKey: ['production-lines'] })
  }

  const handleAdd = async (userId: string) => {
    const result = await bindLineAssignment({ user_id: userId, line_id: lineId })
    if (result.success) {
      invalidate()
    } else {
      message.error(result.error ?? '绑定失败')
    }
  }

  const handleRemove = async (assignmentId: string) => {
    const result = await unbindLineAssignment(assignmentId)
    if (result.success) {
      invalidate()
    } else {
      message.error(result.error ?? '移除失败')
    }
  }

  const list = bindings ?? []

  return (
    <div style={{ borderTop: '1px solid #ede9e4', paddingTop: 12, marginTop: 14 }}>
      <div style={{ fontSize: 11, color: '#a4a097', letterSpacing: 0.4, marginBottom: 8 }}>
        负责人 / 执行人
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', minHeight: 26 }}>
        {list.map(b => (
          <Tag
            key={b.id}
            closable={canManage}
            onClose={e => {
              e.preventDefault()
              handleRemove(b.id)
            }}
            style={{
              margin: 0,
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 6,
              padding: '0 8px',
              lineHeight: '24px',
              background: '#e6e0f5',
              color: '#391c57',
              border: 'none',
            }}
          >
            {getUserName(b.user_id)}
          </Tag>
        ))}
        {list.length === 0 && (
          <span style={{ fontSize: 12.5, color: '#a4a097' }}>
            {canManage ? '尚未绑定人员' : '暂无人员'}
          </span>
        )}
        {canManage && (
          adding ? (
            <UserSelect
              size="small"
              style={{ width: 160 }}
              placeholder="选择人员"
              excludeIds={list.map(b => b.user_id)}
              onSelect={userId => {
                handleAdd(userId)
                setAdding(false)
              }}
            />
          ) : (
            <span
              onClick={() => setAdding(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 24,
                padding: '0 8px',
                borderRadius: 6,
                cursor: 'pointer',
                color: '#a4a097',
                fontSize: 12,
                border: '1px dashed #d9d6d0',
                transition: 'color 0.15s, border-color 0.15s',
                flexShrink: 0,
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color = '#5645d4'
                e.currentTarget.style.borderColor = '#5645d4'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color = '#a4a097'
                e.currentTarget.style.borderColor = '#d9d6d0'
              }}
            >
              <PlusOutlined style={{ fontSize: 11, marginRight: 4 }} />
              添加
            </span>
          )
        )}
      </div>
    </div>
  )
}

// ── 产品关联区（卡片内嵌） ──

function LineProductArea({ lineId, canManage }: { lineId: string; canManage: boolean }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)

  const { data: links } = useQuery({
    queryKey: ['production-line-products', lineId],
    queryFn: async () => {
      const r = await fetchLineProducts({ lineId })
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data ?? []
    },
  })

  // 服务端搜索：产品列表按页上限 100 条，本地过滤够不到第 2 页，
  // 关键字下推后端才能选到任意产品。key 挂在 ['production-products'] 前缀下，
  // 产品增删改的既有 invalidateQueries(['production-products']) 会一并刷新此下拉
  const [productKeyword, setProductKeyword] = useState('')
  const { data: products } = useQuery({
    queryKey: ['production-products', 'all', productKeyword],
    queryFn: () => fetchProductsClient(productKeyword || undefined),
    staleTime: 60_000,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['production-line-products', lineId] })
  }

  const handleAdd = async (productId: string) => {
    const result = await bindLineProduct({ product_id: productId, line_id: lineId })
    if (result.success) {
      invalidate()
    } else {
      message.error(result.error ?? '关联失败')
    }
  }

  const handleRemove = async (linkId: string) => {
    const result = await unbindLineProduct(linkId)
    if (result.success) {
      invalidate()
    } else {
      message.error(result.error ?? '移除失败')
    }
  }

  const list = links ?? []

  return (
    <div style={{ borderTop: '1px solid #ede9e4', paddingTop: 12, marginTop: 14 }}>
      <div style={{ fontSize: 11, color: '#a4a097', letterSpacing: 0.4, marginBottom: 8 }}>
        关联产品
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', minHeight: 26 }}>
        {list.map(l => (
          <Tag
            key={l.id}
            closable={canManage}
            onClose={e => {
              e.preventDefault()
              handleRemove(l.id)
            }}
            style={{
              margin: 0,
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 6,
              padding: '0 8px',
              lineHeight: '24px',
              background: '#e3f2ea',
              color: '#175238',
              border: 'none',
            }}
          >
            {l.product_name ?? '—'}
          </Tag>
        ))}
        {list.length === 0 && (
          <span style={{ fontSize: 12.5, color: '#a4a097' }}>
            {canManage ? '尚未关联产品' : '暂无产品'}
          </span>
        )}
        {canManage && (
          adding ? (
            <Select
              size="small"
              style={{ width: 160 }}
              placeholder="选择产品"
              showSearch={{
                filterOption: false,
                onSearch: setProductKeyword,
              }}
              autoFocus
              options={(products ?? [])
                .filter(p => !list.some(l => l.product_id === p.id))
                .map(p => ({ value: p.id, label: p.product_name }))}
              onSelect={productId => {
                handleAdd(productId)
                setAdding(false)
              }}
              onBlur={() => setAdding(false)}
            />
          ) : (
            <Button
              type="dashed"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setAdding(true)}
            >
              添加
            </Button>
          )
        )}
      </div>
    </div>
  )
}

// ── 产线卡片 ──

function LineCard({
  line,
  canManage,
  onEdit,
  onDelete,
}: {
  line: Line
  canManage: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  const { data: bindings } = useQuery({
    queryKey: ['production-line-bindings', line.id],
    queryFn: async () => {
      const r = await fetchLineAssignments(line.id)
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data ?? []
    },
  })

  return (
    <div
      style={{
        background: '#fff',
        borderRadius: 14,
        border: '1px solid #e5e3df',
        padding: '18px 18px 0',
        display: 'flex',
        flexDirection: 'column',
        transition: 'border-color .15s, box-shadow .15s, transform .15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = 'rgba(86,69,212,0.35)'
        e.currentTarget.style.boxShadow = '0 6px 16px rgba(0,0,0,0.06)'
        e.currentTarget.style.transform = 'translateY(-1px)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = '#e5e3df'
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'none'
      }}
    >
      {/* 头部：名称 + 人员计数 */}
      <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            width: 34,
            height: 34,
            borderRadius: 10,
            background: '#e6e0f5',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 14,
            fontWeight: 600,
            color: '#5645d4',
            flexShrink: 0,
          }}
        >
          {line.name.charAt(0)}
        </span>
        <span style={{ fontWeight: 600, fontSize: 16, color: '#1a1a1a', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {line.name}
        </span>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 11,
            fontWeight: 500,
            color: '#5d5b54',
            background: '#f6f5f4',
            borderRadius: 9999,
            padding: '2px 8px',
            flexShrink: 0,
          }}
        >
          <TeamOutlined style={{ fontSize: 11 }} />
          {(bindings ?? []).length} 人
        </span>
      </div>

      {/* 备注 */}
      {line.remark ? (
        <div
          style={{
            fontSize: 12.5,
            color: '#787671',
            lineHeight: 1.6,
            marginBottom: 14,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {line.remark}
        </div>
      ) : (
        <div style={{ marginBottom: 14 }} />
      )}

      {/* 人员绑定区 */}
      <LineBindArea lineId={line.id} canManage={canManage} />

      {/* 产品关联区 */}
      <LineProductArea lineId={line.id} canManage={canManage} />

      {/* 底部操作区 */}
      {canManage && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, borderTop: '1px solid #ede9e4', padding: '8px 0 12px', marginTop: 12 }}>
          <Button size="small" type="text" icon={<EditOutlined style={{ fontSize: 13 }} />} onClick={onEdit}>编辑</Button>
          <Button size="small" type="text" danger icon={<DeleteOutlined style={{ fontSize: 13 }} />} onClick={onDelete}>删除</Button>
        </div>
      )}
      {!canManage && <div style={{ paddingBottom: 14 }} />}
    </div>
  )
}

// ── 主面板 ──

export function LinesTab({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient()
  const { message, modal } = App.useApp()
  const [modalOpen, setModalOpen] = useState(false)
  const [editItem, setEditItem] = useState<Line | null>(null)

  const { data: lines } = useQuery({
    queryKey: ['production-lines'],
    queryFn: async () => {
      const r = await fetchLines()
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data ?? []
    },
  })

  const handleDelete = (line: Line) => {
    modal.confirm({
      title: `删除产线「${line.name}」?`,
      content: '删除后其名下人员绑定与产品关联将同步解除，历史流水仍会显示该产线名称。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const result = await deleteLine(line.id)
        if (result.success) {
          message.success('已删除')
          queryClient.invalidateQueries({ queryKey: ['production-lines'] })
        } else {
          message.error(result.error)
        }
      },
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <Text style={{ color: '#787671', fontSize: 13, flex: 1 }}>
          工序结束填产出时，产线按操作人的绑定自动确定；消耗中间体也只在本产线范围内选择
        </Text>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditItem(null); setModalOpen(true) }}>
            新增产线
          </Button>
        )}
      </div>

      {(lines ?? []).length === 0 ? (
        <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #e5e3df', padding: '64px 0', textAlign: 'center' }}>
          <Empty
            description={canManage ? '暂无产线，点击「新增产线」创建' : '暂无产线'}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
          {(lines ?? []).map(line => (
            <LineCard
              key={line.id}
              line={line}
              canManage={canManage}
              onEdit={() => { setEditItem(line); setModalOpen(true) }}
              onDelete={() => handleDelete(line)}
            />
          ))}
        </div>
      )}

      <LineFormModal
        key={editItem?.id ?? 'line-new'}
        open={modalOpen || !!editItem}
        editItem={editItem}
        onClose={() => { setModalOpen(false); setEditItem(null) }}
        onSaved={() => {
          setModalOpen(false)
          setEditItem(null)
          queryClient.invalidateQueries({ queryKey: ['production-lines'] })
        }}
      />
    </div>
  )
}
