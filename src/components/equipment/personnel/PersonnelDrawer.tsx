'use client'

import { useState } from 'react'
import { App, Button, Drawer, Select, Typography, Avatar, Space } from 'antd'
import { UserOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { addPersonnel } from '@/actions/equipment-personnel'
import type { EquipmentRole } from '@/types/equipment-personnel'

const { Text } = Typography

interface Props {
  open: boolean
  onClose: () => void
  roles: EquipmentRole[]
}

interface UserOption {
  value: string
  label: string
  dept: string
  eno: string
  avatar: string | null
}

function avatarColor(name: string): string {
  const colors = ['#5645d4', '#7b3ff2', '#dd5b00', '#0075de', '#1aae39', '#e03131']
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

export function PersonnelDrawer({ open, onClose, roles: _roles }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [keyword, setKeyword] = useState('')

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['identity-users-search', keyword],
    queryFn: async () => {
      const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
      const params = new URLSearchParams({ limit: '500' })
      if (keyword) params.set('keyword', keyword)
      const resp = await fetch(`${API_BASE}/api/v1/identity/personnel?${params}`)
      if (!resp.ok) return []
      const json = await resp.json()
      const items = json.data?.items ?? []
      return items.map((u: Record<string, unknown>) => ({
        value: String(u.id),
        label: String(u.name ?? ''),
        dept: String(u.department ?? ''),
        eno: String(u.employee_no ?? ''),
        avatar: u.avatar_url ? String(u.avatar_url) : null,
      })) as UserOption[]
    },
    enabled: open,
  })

  const handleSubmit = async () => {
    if (selectedIds.length === 0) {
      message.warning('请选择要添加的人员')
      return
    }
    setSubmitting(true)
    try {
      await addPersonnel({ user_ids: selectedIds })
      message.success('人员添加成功')
      queryClient.invalidateQueries({ queryKey: ['equipment-personnel'] })
      setSelectedIds([])
      setKeyword('')
      onClose()
    } catch {
      message.error('添加失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    setSelectedIds([])
    setKeyword('')
    onClose()
  }

  return (
    <Drawer
      title={null}
      open={open}
      onClose={handleClose}
      size="large"
      closable={false}
      styles={{
        body: { padding: 0, background: '#f6f5f4' },
        header: { display: 'none' },
      }}
      footer={null}
    >
      {/* Header Bar */}
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
            <UserOutlined style={{ fontSize: 18, color: '#d6b6f6' }} />
          </div>
          <div>
            <Text strong style={{ fontSize: 16, color: '#fff', display: 'block', lineHeight: 1.3 }}>
              添加人员
            </Text>
            <Text style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>
              从身份系统中搜索并添加人员
            </Text>
          </div>
        </div>
        <button
          onClick={handleClose}
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

      {/* Body */}
      <div style={{ padding: '24px 24px 80px' }}>
        {/* 搜索提示卡片 */}
        <div style={{
          padding: '14px 18px', marginBottom: 20,
          background: '#e8ecf2', borderRadius: 10,
          border: '1px solid #cdd6e3',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <SearchOutlined style={{ fontSize: 15, color: '#5667a3', flexShrink: 0 }} />
          <Text style={{ fontSize: 13, color: '#5a6380', lineHeight: 1.5 }}>
            输入姓名搜索人员，支持多选添加。已存在于设备人员池中的人员将被跳过。
          </Text>
        </div>

        <Select
          mode="multiple"
          value={selectedIds}
          onChange={(v) => setSelectedIds(v)}
          onSearch={(v) => setKeyword(v)}
          onClear={() => setKeyword('')}
          filterOption={false}
          notFoundContent={
            isLoading ? '搜索中...' : keyword ? '无匹配人员' : '请输入姓名搜索'
          }
          placeholder="输入姓名搜索人员"
          style={{ width: '100%' }}
          options={users}
          loading={isLoading}
          optionRender={(option) => (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
              <Avatar
                size={32}
                src={option.data.avatar || undefined}
                style={{
                  backgroundColor: option.data.avatar ? 'transparent' : avatarColor(option.data.label),
                  flexShrink: 0,
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                {option.data.label.charAt(0)}
              </Avatar>
              <div style={{ lineHeight: 1.3 }}>
                <Text style={{ fontSize: 14, fontWeight: 500, color: '#1a1a1a', display: 'block' }}>
                  {option.data.label}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {option.data.eno} · {option.data.dept}
                </Text>
              </div>
            </div>
          )}
        />
      </div>

      {/* Footer */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        padding: '14px 24px',
        background: '#ffffff',
        borderTop: '1px solid #e5e3df',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        boxShadow: '0 -2px 8px rgba(0,0,0,0.04)',
      }}>
        <Text style={{ fontSize: 13, color: '#a4a097' }}>
          {selectedIds.length > 0 ? `已选 ${selectedIds.length} 人` : '请搜索并选择人员'}
        </Text>
        <div style={{ display: 'flex', gap: 10 }}>
          <Button onClick={handleClose} style={{ borderRadius: 8 }}>
            取消
          </Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={handleSubmit}
            disabled={selectedIds.length === 0}
            style={{
              borderRadius: 8, fontWeight: 600, height: 36,
              background: '#0a1530', borderColor: '#0a1530',
              boxShadow: 'none',
            }}
          >
            确认添加
          </Button>
        </div>
      </div>
    </Drawer>
  )
}
