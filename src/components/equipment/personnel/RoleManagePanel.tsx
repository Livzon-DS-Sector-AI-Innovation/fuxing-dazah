'use client'

import { useEffect, useState } from 'react'
import {
  App, Button, Modal, Form, Input, Select, Switch, Popconfirm, Tag, Empty, Typography,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { createRole, updateRole, deleteRole } from '@/actions/equipment-personnel'
import type { EquipmentRole, CreateRoleInput, UpdateRoleInput } from '@/types/equipment-personnel'

const { Text } = Typography

interface Props {
  roles: EquipmentRole[]
}

const SCOPE_COLORS: Record<string, { color: string; bg: string; label: string }> = {
  global: { color: '#0075de', bg: '#dcecfa', label: '全局' },
  inspection: { color: '#7b3ff2', bg: '#e6e0f5', label: '巡检' },
  calibration: { color: '#dd5b00', bg: '#ffe8d4', label: '校准' },
  maintenance: { color: '#1aae39', bg: '#d9f3e1', label: '维修' },
}

const PASTEL_TINTS = [
  '#f8f5e8', '#dcecfa', '#d9f3e1', '#ffe8d4', '#fde0ec', '#e6e0f5',
]

function tintForIndex(i: number): string {
  return PASTEL_TINTS[i % PASTEL_TINTS.length]
}

export function RoleManagePanel({ roles }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<EquipmentRole | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const openCreate = () => {
    setEditingRole(null)
    setModalOpen(true)
  }

  const openEdit = (role: EquipmentRole) => {
    setEditingRole(role)
    setModalOpen(true)
  }

  useEffect(() => {
    if (modalOpen) {
      if (editingRole) {
        form.setFieldsValue(editingRole)
      } else {
        form.resetFields()
        form.setFieldsValue({ scope: 'global', is_active: true })
      }
    }
  }, [modalOpen, editingRole, form])

  const handleDelete = async (id: string) => {
    try {
      await deleteRole(id)
      message.success('角色已删除')
      queryClient.invalidateQueries({ queryKey: ['equipment-roles'] })
    } catch {
      message.error('删除失败')
    }
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    try {
      const values = await form.validateFields()
      if (editingRole) {
        const data: UpdateRoleInput = {}
        if (values.name !== editingRole.name) data.name = values.name
        if (values.description !== editingRole.description) data.description = values.description
        if (values.scope !== editingRole.scope) data.scope = values.scope
        if (values.is_active !== editingRole.is_active) data.is_active = values.is_active
        await updateRole(editingRole.id, data)
        message.success('角色已更新')
      } else {
        await createRole(values as CreateRoleInput)
        message.success('角色已创建')
      }
      queryClient.invalidateQueries({ queryKey: ['equipment-roles'] })
      setModalOpen(false)
    } catch (e) {
      if (e instanceof Error && e.message) {
        message.error(e.message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      {/* Header row */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 24,
      }}>
        <div>
          <Text strong style={{ fontSize: 16, color: '#1a1a1a' }}>
            角色列表
          </Text>
          <Text type="secondary" style={{ fontSize: 13, marginLeft: 10 }}>
            {roles.length} 个角色
          </Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreate}
          style={{
            borderRadius: 8, height: 36, fontWeight: 600, fontSize: 13,
            background: '#5645d4', borderColor: '#5645d4',
            boxShadow: 'none',
          }}
        >
          新增角色
        </Button>
      </div>

      {roles.length === 0 ? (
        <div style={{
          padding: '64px 24px', textAlign: 'center',
          background: '#fafaf9', borderRadius: 12,
          border: '1px dashed #d9d5cf',
        }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16,
            background: '#f0eeec',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px',
          }}>
            <SafetyCertificateOutlined style={{ fontSize: 24, color: '#a4a097' }} />
          </div>
          <Text strong style={{ fontSize: 15, color: '#37352f', display: 'block', marginBottom: 6 }}>
            暂无角色
          </Text>
          <Text style={{ fontSize: 13, color: '#a4a097' }}>
            点击「新增角色」创建第一个角色定义
          </Text>
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 16,
        }}>
          {roles.map((role, i) => {
            const scope = SCOPE_COLORS[role.scope] || SCOPE_COLORS.global
            return (
              <div key={role.id} style={{
                background: '#ffffff',
                borderRadius: 12,
                border: '1px solid #e5e3df',
                overflow: 'hidden',
                transition: 'box-shadow 0.15s ease, border-color 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = '#d6b6f6'
                e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = '#e5e3df'
                e.currentTarget.style.boxShadow = 'none'
              }}
              >
                {/* Card header — pastel tint */}
                <div style={{
                  padding: '16px 20px',
                  background: tintForIndex(i),
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: 32, height: 32, borderRadius: 8,
                      background: role.is_active ? '#5645d4' : '#a4a097',
                      color: '#fff', fontSize: 14, fontWeight: 700,
                    }}>
                      {role.name.charAt(0)}
                    </span>
                    <div>
                      <Text strong style={{ fontSize: 15, color: '#1a1a1a', display: 'block', lineHeight: 1.3 }}>
                        {role.name}
                      </Text>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center',
                        padding: '1px 8px', borderRadius: 4,
                        fontSize: 11, fontWeight: 600, lineHeight: '18px',
                        color: scope.color, background: scope.bg,
                        marginTop: 2,
                      }}>
                        {scope.label}
                      </span>
                    </div>
                  </div>
                  {!role.is_active && (
                    <Tag style={{ borderRadius: 4, color: '#787671', background: '#f0eeec', border: 'none', margin: 0 }}>
                      停用
                    </Tag>
                  )}
                </div>

                {/* Card body */}
                <div style={{ padding: '14px 20px' }}>
                  <Text style={{ fontSize: 13, color: '#5d5b54', lineHeight: 1.5 }}>
                    {role.description || '暂无描述'}
                  </Text>
                  <div style={{ marginTop: 10 }}>
                    <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      编码
                    </Text>
                    <Text code style={{ fontSize: 12, marginLeft: 8, color: '#37352f' }}>
                      {role.code}
                    </Text>
                  </div>
                </div>

                {/* Card footer — actions */}
                <div style={{
                  display: 'flex', gap: 0,
                  borderTop: '1px solid #ede9e4',
                }}>
                  <button
                    onClick={() => openEdit(role)}
                    style={{
                      flex: 1, padding: '10px 0',
                      background: 'transparent', border: 'none',
                      cursor: 'pointer',
                      color: '#5d5b54', fontSize: 13, fontWeight: 500,
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                      transition: 'color 0.15s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = '#5645d4')}
                    onMouseLeave={e => (e.currentTarget.style.color = '#5d5b54')}
                  >
                    <EditOutlined />编辑
                  </button>
                  <div style={{ width: 1, background: '#ede9e4' }} />
                  <Popconfirm
                    title="确认删除此角色？"
                    onConfirm={() => handleDelete(role.id)}
                  >
                    <button
                      style={{
                        flex: 1, padding: '10px 0',
                        background: 'transparent', border: 'none',
                        cursor: 'pointer',
                        color: '#5d5b54', fontSize: 13, fontWeight: 500,
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                        transition: 'color 0.15s',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.color = '#e03131')}
                      onMouseLeave={e => (e.currentTarget.style.color = '#5d5b54')}
                    >
                      <DeleteOutlined />删除
                    </button>
                  </Popconfirm>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create/Edit Modal */}
      <Modal
        key={String(modalOpen)}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        okText={editingRole ? '保存' : '创建'}
        cancelText="取消"
        okButtonProps={{
          style: { borderRadius: 8, fontWeight: 600 },
        }}
        styles={{
          header: { padding: '18px 24px', borderBottom: '1px solid #ede9e4' },
          body: { padding: 24 },
        }}
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <SafetyCertificateOutlined style={{ fontSize: 16, color: '#5645d4' }} />
            <span>{editingRole ? '编辑角色' : '新增角色'}</span>
          </div>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="角色名称"
            rules={[{ required: true, message: '请输入角色名称' }]}
          >
            <Input maxLength={100} placeholder="如：维修工" style={{ borderRadius: 8 }} />
          </Form.Item>
          <Form.Item
            name="code"
            label="角色编码"
            rules={[{ required: true, message: '请输入角色编码' }]}
          >
            <Input
              maxLength={50}
              placeholder="如：maintenance_tech"
              disabled={!!editingRole}
              style={{ borderRadius: 8 }}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea maxLength={200} placeholder="角色职责说明" style={{ borderRadius: 8 }} />
          </Form.Item>
          <Form.Item name="scope" label="作用域">
            <Select
              style={{ borderRadius: 8 }}
              options={[
                { label: '全局 (global)', value: 'global' },
                { label: '巡检 (inspection)', value: 'inspection' },
                { label: '校准 (calibration)', value: 'calibration' },
                { label: '维修 (maintenance)', value: 'maintenance' },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
