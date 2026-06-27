'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button, Popconfirm, App, Empty, Input } from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  SafetyCertificateOutlined, TeamOutlined, KeyOutlined,
  SearchOutlined, UserAddOutlined,
} from '@ant-design/icons'
import { RoleForm } from './RoleForm'
import { deleteRole } from '@/actions/permission'
import type { Role, PermissionModuleGroup, DataScope } from '@/types/permission'

const SCOPE_LABELS: Record<DataScope, string> = {
  all: '全部数据',
  department_and_children: '本部门及下级',
  department: '本部门',
  self_only: '仅自己',
}

const SCOPE_TAG_STYLES: Record<DataScope, { bg: string; color: string }> = {
  all:                       { bg: '#d9f3e1', color: '#1a7a2e' },
  department_and_children:   { bg: '#dcecfa', color: '#0056a6' },
  department:                { bg: '#dcecfa', color: '#0056a6' },
  self_only:                 { bg: '#f0eeec', color: '#5d5b54' },
}

/** Card background tint rotation — matches DESIGN.md pastel tints */
const CARD_TINTS = [
  { bg: '#e6e0f5', border: '#d4c8ed' }, // lavender
  { bg: '#dcecfa', border: '#c4daf2' }, // sky
  { bg: '#d9f3e1', border: '#bce8cc' }, // mint
  { bg: '#ffe8d4', border: '#f5d5b8' }, // peach
  { bg: '#fde0ec', border: '#f5c8db' }, // rose
]

function getCardTint(index: number) {
  return CARD_TINTS[index % CARD_TINTS.length]
}

interface Props {
  initialRoles: Role[]
  permissionGroups: PermissionModuleGroup[]
}

export function RoleList({ initialRoles, permissionGroups }: Props) {
  const { message } = App.useApp()
  const router = useRouter()
  const [roles, setRoles] = useState(initialRoles)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [search, setSearch] = useState('')

  const filteredRoles = roles.filter(
    (r) =>
      r.name.toLowerCase().includes(search.toLowerCase()) ||
      r.code.toLowerCase().includes(search.toLowerCase())
  )

  const totalPermissions = new Set(
    permissionGroups.flatMap((g) => g.permissions.map((p) => p.id))
  ).size
  const totalUserCount = roles.reduce((sum, r) => sum + r.user_count, 0)

  const handleDelete = async (roleId: string) => {
    try {
      await deleteRole(roleId)
      setRoles((prev) => prev.filter((r) => r.id !== roleId))
      message.success('删除成功')
      router.refresh()
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <div
      className="h-full flex flex-col gap-4 sm:gap-6 p-4 sm:p-6 overflow-hidden"
      style={{ backgroundColor: 'var(--color-surface)' }}
    >
      {/* ═══════════════════════════════════════════════
          Layer 1: Header Card
          ═══════════════════════════════════════════════ */}
      <div
        className="rounded-[16px] border p-5 sm:p-6"
        style={{
          backgroundColor: 'var(--color-canvas)',
          borderColor: 'var(--color-hairline)',
          borderTop: '3px solid var(--color-primary)',
        }}
      >
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          {/* Title */}
          <div className="flex items-center gap-3.5">
            <div
              className="w-10 h-10 rounded-[10px] flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              <SafetyCertificateOutlined style={{ fontSize: 20, color: '#fff' }} />
            </div>
            <div>
              <h1 className="text-[20px] sm:text-[22px] font-semibold text-[var(--color-ink)] tracking-tight leading-tight">
                角色管理
              </h1>
              <p className="text-[13px] text-[var(--color-steel)] mt-0.5">
                管理系统角色与权限配置
              </p>
            </div>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-4 sm:gap-6">
            {[
              { value: roles.length, label: '角色' },
              { value: totalPermissions, label: '权限' },
              { value: totalUserCount, label: '已分配' },
            ].map((stat) => (
              <div key={stat.label} className="text-center">
                <div className="text-[18px] sm:text-[20px] font-semibold text-[var(--color-ink)] leading-tight">
                  {stat.value}
                </div>
                <div className="text-[11px] sm:text-[12px] text-[var(--color-steel)] mt-0.5">
                  {stat.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════
          Layer 2: Content Panel
          ═══════════════════════════════════════════════ */}
      <div
        className="rounded-[16px] border p-4 sm:p-6 flex-1 flex flex-col overflow-hidden"
        style={{
          backgroundColor: 'var(--color-canvas)',
          borderColor: 'var(--color-hairline)',
        }}
      >
        {/* Toolbar */}
        <div className="flex flex-col sm:flex-row gap-3 mb-5">
          <Input
            prefix={<SearchOutlined style={{ color: 'var(--color-stone)' }} />}
            placeholder="搜索角色名称或编码…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            allowClear
            size="large"
            style={{ borderRadius: 12, height: 44, fontSize: 14, flex: 1 }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            size="large"
            onClick={() => { setEditingRole(null); setDrawerOpen(true) }}
            style={{
              backgroundColor: 'var(--color-primary)',
              borderColor: 'var(--color-primary)',
              borderRadius: 12,
              height: 44,
              fontWeight: 500,
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            新建角色
          </Button>
        </div>

        {/* Card Grid or Empty State */}
        {filteredRoles.length === 0 && roles.length === 0 ? (
          <div
            className="rounded-[12px] border border-dashed py-20 flex flex-col items-center flex-1"
            style={{ borderColor: 'var(--color-hairline)' }}
          >
            <div
              className="w-16 h-16 rounded-[16px] flex items-center justify-center mb-4"
              style={{ backgroundColor: 'var(--color-surface)' }}
            >
              <SafetyCertificateOutlined style={{ fontSize: 28, color: 'var(--color-stone)' }} />
            </div>
            <p className="text-[15px] font-medium text-[var(--color-charcoal)] mb-1">
              暂无角色
            </p>
            <p className="text-[13px] text-[var(--color-steel)] mb-5">
              创建第一个系统角色来开始权限管理
            </p>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => { setEditingRole(null); setDrawerOpen(true) }}
              style={{
                backgroundColor: 'var(--color-primary)',
                borderColor: 'var(--color-primary)',
                borderRadius: 8,
                fontWeight: 500,
              }}
            >
              新建角色
            </Button>
          </div>
        ) : filteredRoles.length === 0 ? (
          <div
            className="rounded-[12px] border py-16 flex-1"
            style={{ borderColor: 'var(--color-hairline)', backgroundColor: 'var(--color-canvas)' }}
          >
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span className="text-[13px] text-[var(--color-steel)]">
                  没有匹配「{search}」的角色
                </span>
              }
            />
          </div>
        ) : (
          <div
            className="grid gap-3 sm:gap-4 overflow-auto content-start"
            style={{
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            }}
          >
            {filteredRoles.map((role, index) => {
              const tint = getCardTint(index)
              const scopeStyle = SCOPE_TAG_STYLES[role.data_scope]
              return (
                <div
                  key={role.id}
                  className="rounded-[16px] border p-5 flex flex-col transition-shadow duration-150 group"
                  style={{
                    backgroundColor: tint.bg,
                    borderColor: tint.border,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.boxShadow =
                      'rgba(15, 15, 15, 0.06) 0px 4px 12px 0px'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.boxShadow = 'none'
                  }}
                >
                  {/* Top row: icon + system badge */}
                  <div className="flex items-center justify-between mb-3">
                    <div
                      className="w-9 h-9 rounded-[8px] flex items-center justify-center flex-shrink-0"
                      style={{
                        backgroundColor: role.is_system
                          ? 'var(--color-primary)'
                          : 'rgba(255,255,255,0.7)',
                        color: role.is_system ? '#fff' : 'var(--color-steel)',
                      }}
                    >
                      <SafetyCertificateOutlined style={{ fontSize: 16 }} />
                    </div>
                    {role.is_system && (
                      <span
                        className="inline-flex items-center px-2 py-0.5 rounded-[4px] text-[11px] font-medium"
                        style={{ backgroundColor: 'rgba(86, 69, 212, 0.12)', color: '#391c57' }}
                      >
                        系统内置
                      </span>
                    )}
                  </div>

                  {/* Name + code */}
                  <h3 className="text-[15px] font-semibold text-[var(--color-ink)] truncate mb-0.5">
                    {role.name}
                  </h3>
                  <code className="text-[11px] text-[var(--color-stone)] font-mono mb-2">
                    {role.code}
                  </code>

                  {/* Description */}
                  {role.description ? (
                    <p className="text-[13px] text-[var(--color-steel)] leading-relaxed mb-3 line-clamp-2">
                      {role.description}
                    </p>
                  ) : null}

                  {/* Data scope tag */}
                  <div className="mb-3">
                    <span
                      className="inline-flex items-center px-2.5 py-0.5 rounded-[4px] text-[11px] font-medium"
                      style={{ backgroundColor: scopeStyle.bg, color: scopeStyle.color }}
                    >
                      {SCOPE_LABELS[role.data_scope] || role.data_scope}
                    </span>
                  </div>

                  {/* Stats row */}
                  <div className="flex items-center gap-4 text-[12px] text-[var(--color-steel)] mb-3">
                    <span className="flex items-center gap-1">
                      <TeamOutlined style={{ fontSize: 12, color: 'var(--color-stone)' }} />
                      <span className="font-medium text-[var(--color-charcoal)]">{role.user_count}</span>
                      <span>用户</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <KeyOutlined style={{ fontSize: 12, color: 'var(--color-stone)' }} />
                      <span className="font-medium text-[var(--color-charcoal)]">{role.permission_ids.length}</span>
                      <span>权限</span>
                    </span>
                  </div>

                  {/* Actions row */}
                  <div
                    className="flex items-center gap-1 pt-2 border-t transition-opacity duration-150"
                    style={{
                      borderColor: 'rgba(0,0,0,0.06)',
                    }}
                  >
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => { setEditingRole(role); setDrawerOpen(true) }}
                      style={{ borderRadius: 6, color: 'var(--color-steel)', fontSize: 13 }}
                    >
                      编辑
                    </Button>
                    <Button
                      type="text"
                      size="small"
                      icon={<UserAddOutlined />}
                      style={{ borderRadius: 6, color: 'var(--color-steel)', fontSize: 13 }}
                      onClick={() => router.push('/permission/users')}
                    >
                      分配
                    </Button>
                    <div className="flex-1" />
                    {!role.is_system && (
                      <Popconfirm
                        title="确定删除此角色？"
                        description="删除后不可恢复，已关联用户将失去此角色权限。"
                        onConfirm={() => handleDelete(role.id)}
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                      >
                        <Button
                          type="text"
                          size="small"
                          icon={<DeleteOutlined />}
                          danger
                          style={{ borderRadius: 6 }}
                        />
                      </Popconfirm>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <RoleForm
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSuccess={() => {}}
        role={editingRole}
        permissionGroups={permissionGroups}
      />
    </div>
  )
}
