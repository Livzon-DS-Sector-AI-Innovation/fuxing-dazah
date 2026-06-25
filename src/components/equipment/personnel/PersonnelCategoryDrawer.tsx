'use client'

import { useEffect, useState } from 'react'
import {
  App, Drawer, TreeSelect, Select, Button, Tag, Typography, Tooltip,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, SafetyCertificateOutlined,
  ApartmentOutlined, UserOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchCategories } from '@/lib/api/equipment'
import { assignCategories } from '@/actions/equipment-personnel'
import type {
  EquipmentRole, CategoryAssignItem, PersonnelCategoryInfo,
} from '@/types/equipment-personnel'
import type { EquipmentCategory } from '@/types/equipment'

const { Text } = Typography

interface Props {
  open: boolean
  onClose: () => void
  personnelId: string
  personnelName: string
  roles: EquipmentRole[]
  existingCategories: PersonnelCategoryInfo[]
}

interface TreeOption {
  value: string
  title: string
  children?: TreeOption[]
}

export function PersonnelCategoryDrawer({
  open, onClose, personnelId, personnelName, roles, existingCategories,
}: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [items, setItems] = useState<CategoryAssignItem[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open && existingCategories.length > 0) {
      setItems(existingCategories.map(c => ({
        role_id: c.role_id,
        category_id: c.category_id,
      })))
    } else if (open) {
      setItems([])
    }
  }, [open, existingCategories])

  const { data: categories = [] } = useQuery({
    queryKey: ['equipment-categories-tree'],
    queryFn: fetchCategories,
    enabled: open,
  })

  const addItem = () => {
    setItems(prev => [...prev, { role_id: '', category_id: '' }])
  }

  const removeItem = (index: number) => {
    setItems(prev => prev.filter((_, i) => i !== index))
  }

  const updateItem = (index: number, field: keyof CategoryAssignItem, value: string) => {
    setItems(prev => prev.map((item, i) =>
      i === index ? { ...item, [field]: value } : item,
    ))
  }

  const handleSubmit = async () => {
    const validItems = items.filter(i => i.role_id && i.category_id)
    if (validItems.length === 0) {
      message.warning('请至少添加一条有效的分类绑定')
      return
    }
    setSubmitting(true)
    try {
      await assignCategories(personnelId, { categories: validItems })
      message.success('分类约束已更新')
      queryClient.invalidateQueries({ queryKey: ['equipment-personnel'] })
      setItems([])
      onClose()
    } catch {
      message.error('保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  const buildTree = (list: EquipmentCategory[]): TreeOption[] =>
    list.map(c => ({
      value: c.id,
      title: c.name,
      children: c.children ? buildTree(c.children) : undefined,
    }))

  const validCount = items.filter(i => i.role_id && i.category_id).length
  const hasItems = items.length > 0

  return (
    <Drawer
      title={null}
      open={open}
      onClose={onClose}
      size="large"
      closable={false}
      styles={{
        body: { padding: 0, background: '#f5f3f0' },
        header: { display: 'none' },
      }}
      footer={null}
    >
      {/* ── 自定义 Header Bar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '18px 24px',
        background: '#0a1530',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            background: 'rgba(255,255,255,0.1)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <SafetyCertificateOutlined style={{ fontSize: 18, color: '#d6b6f6' }} />
          </div>
          <div>
            <Text strong style={{ fontSize: 16, color: '#fff', display: 'block', lineHeight: 1.3 }}>
              分类约束
            </Text>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
              <UserOutlined style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }} />
              <Text style={{ fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>
                {personnelName}
              </Text>
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'rgba(255,255,255,0.08)',
            border: 'none', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'rgba(255,255,255,0.7)', fontSize: 18,
            transition: 'background 0.15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.15)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.08)')}
        >✕</button>
      </div>

      {/* ── Body ── */}
      <div style={{ padding: '24px 24px 80px' }}>
        {/* 说明卡片 — 工业蓝调 */}
        <div style={{
          padding: '14px 18px', marginBottom: 24,
          background: '#e8ecf2', borderRadius: 10,
          border: '1px solid #cdd6e3',
          display: 'flex', alignItems: 'flex-start', gap: 12,
        }}>
          <ThunderboltOutlined style={{ fontSize: 16, color: '#5667a3', marginTop: 1, flexShrink: 0 }} />
          <div>
            <Text strong style={{ fontSize: 13, color: '#2d3451', display: 'block', marginBottom: 2 }}>
              约束规则说明
            </Text>
            <Text style={{ fontSize: 12, color: '#5a6380', lineHeight: 1.5 }}>
              将角色与设备分类绑定后，该人员仅在指定分类范围内分配该角色。
              <Text style={{ color: '#a4a5b0' }}>未设置约束的角色默认为全部可分配。</Text>
            </Text>
          </div>
        </div>

        {/* 统计行 */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 16,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <ApartmentOutlined style={{ fontSize: 14, color: '#787671' }} />
            <Text strong style={{ fontSize: 14, color: '#1a1a1a' }}>
              约束条目
            </Text>
            {hasItems && (
              <span style={{
                padding: '1px 8px', borderRadius: 10,
                fontSize: 11, fontWeight: 700,
                color: '#5645d4', background: '#e6e0f5',
              }}>
                {validCount}/{items.length}
              </span>
            )}
          </div>
          <Button
            type="dashed"
            size="small"
            icon={<PlusOutlined />}
            onClick={addItem}
            style={{
              borderRadius: 8, height: 32,
              fontWeight: 600, fontSize: 12,
              borderColor: '#c8c4be', color: '#5d5b54',
            }}
          >
            添加约束
          </Button>
        </div>

        {/* ── 约束条目列表 ── */}
        {!hasItems ? (
          <div style={{
            padding: '48px 24px',
            textAlign: 'center',
            background: '#fff', borderRadius: 12,
            border: '1px dashed #d9d5cf',
          }}>
            <div style={{
              width: 56, height: 56, borderRadius: 16,
              background: '#f5f3f0',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 16px',
            }}>
              <SafetyCertificateOutlined style={{ fontSize: 24, color: '#c8c4be' }} />
            </div>
            <Text strong style={{ fontSize: 15, color: '#37352f', display: 'block', marginBottom: 6 }}>
              未设置分类约束
            </Text>
            <Text style={{ fontSize: 13, color: '#a4a097', lineHeight: 1.6, display: 'block', maxWidth: 320, margin: '0 auto' }}>
              点击上方「添加约束」为该人员指定
              <Text strong style={{ color: '#787671' }}>角色 → 分类</Text>
              的访问范围
            </Text>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {items.map((item, index) => {
              const isComplete = !!(item.role_id && item.category_id)
              const selectedRole = roles.find(r => r.id === item.role_id)
              const isDuplicate = item.role_id && item.category_id
                && items.some((other, oi) =>
                  oi !== index
                  && other.role_id === item.role_id
                  && other.category_id === item.category_id,
                )

              return (
                <div key={index} style={{
                  background: '#fff', borderRadius: 12,
                  border: isComplete
                    ? '1px solid #d9f3e1'
                    : '1px solid #e5e3df',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                  overflow: 'hidden',
                  transition: 'border-color 0.2s, box-shadow 0.2s',
                }}>
                  {/* 条目 Header */}
                  <div style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 16px',
                    background: isComplete ? '#f8fbf8' : '#fafaf9',
                    borderBottom: '1px solid #ede9e4',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 22, height: 22, borderRadius: 6,
                        background: isComplete ? '#1aae39' : '#787671',
                        color: '#fff', fontSize: 11, fontWeight: 700,
                        transition: 'background 0.2s',
                      }}>
                        {index + 1}
                      </span>
                      <Text style={{
                        fontSize: 13, fontWeight: 600, color: '#1a1a1a',
                      }}>
                        约束 #{index + 1}
                      </Text>
                      {isComplete && selectedRole && (
                        <Tag
                          color="purple"
                          style={{ margin: 0, borderRadius: 4, fontSize: 11, lineHeight: '18px' }}
                        >
                          {selectedRole.name}
                        </Tag>
                      )}
                      {isDuplicate && (
                        <Tooltip title="存在重复的角色-分类组合">
                          <span style={{
                            padding: '1px 8px', borderRadius: 4,
                            fontSize: 11, fontWeight: 600,
                            color: '#dd5b00', background: '#ffe8d4',
                          }}>
                            重复
                          </span>
                        </Tooltip>
                      )}
                    </div>
                    <button
                      onClick={() => removeItem(index)}
                      style={{
                        width: 28, height: 28, borderRadius: 6,
                        background: 'transparent', border: 'none',
                        cursor: 'pointer', color: '#a4a097',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 14, transition: 'all 0.15s',
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.background = '#fde0ec'
                        e.currentTarget.style.color = '#e03131'
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.background = 'transparent'
                        e.currentTarget.style.color = '#a4a097'
                      }}
                    >
                      <DeleteOutlined />
                    </button>
                  </div>

                  {/* 条目 Body — 选择器 */}
                  <div style={{
                    display: 'flex', gap: 16, padding: '14px 16px',
                    alignItems: 'flex-start',
                  }}>
                    {/* 角色选择 */}
                    <div style={{ flex: '0 0 152px' }}>
                      <Text style={{
                        fontSize: 11, fontWeight: 600, color: '#a4a097',
                        textTransform: 'uppercase', letterSpacing: 0.5,
                        display: 'block', marginBottom: 6,
                      }}>
                        角色
                      </Text>
                      <Select
                        placeholder="选择角色"
                        value={item.role_id || undefined}
                        onChange={(v: string) => updateItem(index, 'role_id', v)}
                        style={{ width: '100%' }}
                        options={roles.map(r => ({ label: r.name, value: r.id }))}
                      />
                    </div>

                    {/* 箭头 */}
                    <div style={{
                      display: 'flex', alignItems: 'center',
                      paddingTop: 20, flexShrink: 0,
                    }}>
                      <span style={{
                        color: '#c8c4be', fontSize: 16, fontWeight: 700,
                      }}>→</span>
                    </div>

                    {/* 分类选择 */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Text style={{
                        fontSize: 11, fontWeight: 600, color: '#a4a097',
                        textTransform: 'uppercase', letterSpacing: 0.5,
                        display: 'block', marginBottom: 6,
                      }}>
                        设备分类
                      </Text>
                      <TreeSelect
                        placeholder="选择分类范围"
                        value={item.category_id || undefined}
                        onChange={(v: string) => updateItem(index, 'category_id', v)}
                        style={{ width: '100%' }}
                        treeData={buildTree(categories)}
                        treeDefaultExpandAll
                        styles={{ popup: { root: { maxHeight: 360 } } }}
                      />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* ── 底部操作栏 — 悬浮 ── */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        padding: '14px 24px',
        background: '#fff',
        borderTop: '1px solid #e5e3df',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        boxShadow: '0 -2px 8px rgba(0,0,0,0.04)',
      }}>
        <Text style={{ fontSize: 13, color: '#a4a097' }}>
          {hasItems
            ? `${validCount} 条有效约束`
            : '未设置约束 — 全部可分配'}
        </Text>
        <div style={{ display: 'flex', gap: 10 }}>
          <Button onClick={onClose} style={{ borderRadius: 8 }}>
            取消
          </Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={handleSubmit}
            disabled={!hasItems}
            style={{
              borderRadius: 8, fontWeight: 600, height: 36,
              background: '#0a1530', borderColor: '#0a1530',
              boxShadow: 'none',
            }}
          >
            保存约束
          </Button>
        </div>
      </div>
    </Drawer>
  )
}
