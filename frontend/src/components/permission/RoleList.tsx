'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button, Popconfirm, App, Empty, Input, Modal, Tag, Avatar, Spin, Select } from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  SafetyCertificateOutlined, TeamOutlined, KeyOutlined,
  SearchOutlined, UserAddOutlined, CloseOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import { RoleForm } from './RoleForm'
import { deleteRole, assignRoleToUser, removeRoleFromUser, assignRoleToDepartment, removeRoleFromDepartment } from '@/actions/permission'
import { fetchRoles, fetchRoleUsers, fetchRoleDepartments, fetchDepartments } from '@/lib/api/permission'
import { UserSelect } from '@/components/shared'
import type { Role, PermissionModuleGroup, DataScope, RoleUser, DepartmentRole, DepartmentItem } from '@/types/permission'

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
  apiToken: string
}

export function RoleList({ initialRoles, permissionGroups, apiToken }: Props) {
  const { message, modal } = App.useApp()
  const router = useRouter()
  const [roles, setRoles] = useState(initialRoles)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [search, setSearch] = useState('')

  // ── Assign user to role state ──
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignRole, setAssignRole] = useState<Role | null>(null)
  const [assignUsers, setAssignUsers] = useState<RoleUser[]>([])
  const [assignUsersLoading, setAssignUsersLoading] = useState(false)
  const [assignUserId, setAssignUserId] = useState<string | undefined>()
  const [assigning, setAssigning] = useState(false)

  // ── Department assign state ──
  const [deptAssignRole, setDeptAssignRole] = useState<Role | null>(null)
  const [assignedDepts, setAssignedDepts] = useState<DepartmentRole[]>([])
  const [assignedDeptsLoading, setAssignedDeptsLoading] = useState(false)
  const [selectedDeptIds, setSelectedDeptIds] = useState<string[]>([])
  const [deptAssigning, setDeptAssigning] = useState(false)
  const [departments, setDepartments] = useState<DepartmentItem[]>([])

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

  // 新建/编辑成功后重取角色列表并写入本地 state，让新角色（或改动）立即出现在卡片网格中。
  // router.refresh() 只刷新服务端 props，不会更新这里 useState 初始化的 roles，所以需要单独重取。
  const refreshRoles = async () => {
    try {
      setRoles(await fetchRoles(apiToken))
    } catch {
      message.error('刷新角色列表失败')
    }
  }

  const refreshAssignUsers = async (roleId: string) => {
    setAssignUsers(await fetchRoleUsers(apiToken, roleId))
  }

  const handleAssignOpen = async (role: Role) => {
    setAssignRole(role)
    setAssignUserId(undefined)
    setAssignOpen(true)
    setAssignUsersLoading(true)
    try {
      setAssignUsers(await fetchRoleUsers(apiToken, role.id))
    } catch {
      message.error('获取已分配用户失败')
    } finally {
      setAssignUsersLoading(false)
    }
  }

  const handleAssignConfirm = async () => {
    if (!assignRole || !assignUserId) return
    const roleId = assignRole.id
    const userId = assignUserId
    setAssigning(true)
    try {
      await assignRoleToUser(userId, { role_id: roleId })
      message.success('分配成功')
      setAssignUserId(undefined)
      await refreshAssignUsers(roleId)
      // 本地更新 user_count（router.refresh 只刷新 props，state 不跟随）
      setRoles((prev) =>
        prev.map((r) => (r.id === roleId ? { ...r, user_count: r.user_count + 1 } : r))
      )
    } catch {
      message.error('分配失败')
    } finally {
      setAssigning(false)
    }
  }

  const handleRemoveAssign = (userId: string) => {
    if (!assignRole) return
    const roleId = assignRole.id
    const userName = assignUsers.find((u) => u.id === userId)?.name ?? ''
    modal.confirm({
      title: '移除用户',
      content: `确定移除「${userName}」的「${assignRole.name}」角色？移除后该用户将失去此角色的权限。`,
      okText: '移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await removeRoleFromUser(userId, roleId)
          message.success('已移除')
          await refreshAssignUsers(roleId)
          setRoles((prev) =>
            prev.map((r) => (r.id === roleId ? { ...r, user_count: r.user_count - 1 } : r))
          )
        } catch {
          message.error('移除失败')
        }
      },
    })
  }

  // ── Department assign handlers ──
  const refreshAssignedDepts = async (roleId: string) => {
    setAssignedDepts(await fetchRoleDepartments(apiToken, roleId))
  }

  const handleDeptAssignOpen = async (role: Role) => {
    setDeptAssignRole(role)
    setSelectedDeptIds([])
    setAssignedDeptsLoading(true)
    try {
      const [depts, allDepts] = await Promise.all([
        fetchRoleDepartments(apiToken, role.id),
        fetchDepartments(),
      ])
      setAssignedDepts(depts)
      setDepartments(allDepts)
    } catch {
      message.error('获取部门数据失败')
    } finally {
      setAssignedDeptsLoading(false)
    }
  }

  const handleDeptAssignConfirm = async () => {
    if (!deptAssignRole || selectedDeptIds.length === 0) return
    const roleId = deptAssignRole.id
    setDeptAssigning(true)
    try {
      await assignRoleToDepartment(roleId, { feishu_department_ids: selectedDeptIds })
      message.success(`已为 ${selectedDeptIds.length} 个部门分配角色`)
      setSelectedDeptIds([])
      await refreshAssignedDepts(roleId)
    } catch {
      message.error('分配部门角色失败')
    } finally {
      setDeptAssigning(false)
    }
  }

  const handleRemoveDeptAssign = (feishuDepartmentId: string) => {
    if (!deptAssignRole) return
    const roleId = deptAssignRole.id
    const deptName = assignedDepts.find((d) => d.feishu_department_id === feishuDepartmentId)?.department_name ?? ''
    modal.confirm({
      title: '移除部门角色',
      content: `确定移除「${deptName || feishuDepartmentId}」的「${deptAssignRole.name}」角色？移除后该部门成员将失去此角色的权限。`,
      okText: '移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await removeRoleFromDepartment(roleId, feishuDepartmentId)
          message.success('已移除')
          await refreshAssignedDepts(roleId)
        } catch {
          message.error('移除失败')
        }
      },
    })
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
                      <ApartmentOutlined style={{ fontSize: 12, color: 'var(--color-stone)' }} />
                      <span className="font-medium text-[var(--color-charcoal)]">{role.department_count}</span>
                      <span>部门</span>
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
                      onClick={() => handleAssignOpen(role)}
                    >
                      分配
                    </Button>
                    <Button
                      type="text"
                      size="small"
                      icon={<ApartmentOutlined />}
                      style={{ borderRadius: 6, color: 'var(--color-steel)', fontSize: 13 }}
                      onClick={() => handleDeptAssignOpen(role)}
                    >
                      部门
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
        onSuccess={() => { void refreshRoles() }}
        role={editingRole}
        permissionGroups={permissionGroups}
      />

      {/* Assign user to role modal */}
      <Modal
        title={`分配用户 · ${assignRole?.name ?? ''}`}
        open={assignOpen}
        onCancel={() => setAssignOpen(false)}
        onOk={handleAssignConfirm}
        confirmLoading={assigning}
        okText="确认分配"
        cancelText="取消"
        okButtonProps={{ disabled: !assignUserId }}
      >
        {/* 已分配用户 */}
        <div className="mb-4">
          <div className="text-[13px] font-medium text-[var(--color-charcoal)] mb-2">
            已分配用户（{assignUsers.length}）
          </div>
          {assignUsersLoading ? (
            <Spin />
          ) : assignUsers.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {assignUsers.map((u) => (
                <Tag
                  key={u.id}
                  closable
                  closeIcon={<CloseOutlined style={{ fontSize: 10 }} />}
                  onClose={(e) => {
                    e.preventDefault() // 阻止 Tag 自动移除，等确认后才真正移除
                    handleRemoveAssign(u.id)
                  }}
                  style={{ borderRadius: 6, fontSize: 12, margin: 0, padding: '2px 6px 2px 2px' }}
                >
                  <Avatar
                    src={u.avatar_url}
                    size={18}
                    style={{
                      backgroundColor: 'var(--color-primary)',
                      fontSize: 10,
                      marginRight: 4,
                    }}
                  >
                    {u.name.charAt(0)}
                  </Avatar>
                  {u.name}
                  {u.employee_no && (
                    <code className="text-[10px] text-[var(--color-stone)] ml-1">
                      {u.employee_no}
                    </code>
                  )}
                </Tag>
              ))}
            </div>
          ) : (
            <p className="text-[13px] text-[var(--color-muted)]">暂无用户分配该角色</p>
          )}
        </div>

        <p className="text-[13px] text-[var(--color-steel)] mb-3">
          选择要分配「{assignRole?.name}」角色的用户：
        </p>
        <UserSelect
          value={assignUserId}
          onChange={(v) => setAssignUserId(v as string)}
          excludeIds={assignUsers.map((u) => u.id)}
          placeholder="搜索姓名或工号…"
          style={{ width: '100%' }}
        />
      </Modal>

      {/* Assign department to role modal */}
      <Modal
        title={`分配给部门 · ${deptAssignRole?.name ?? ''}`}
        open={deptAssignRole !== null}
        onCancel={() => setDeptAssignRole(null)}
        onOk={handleDeptAssignConfirm}
        confirmLoading={deptAssigning}
        okText="确认分配"
        cancelText="取消"
        okButtonProps={{ disabled: selectedDeptIds.length === 0 }}
      >
        {/* 已分配部门 */}
        <div className="mb-4">
          <div className="text-[13px] font-medium text-[var(--color-charcoal)] mb-2">
            已分配部门（{assignedDepts.length}）
          </div>
          {assignedDeptsLoading ? (
            <Spin />
          ) : assignedDepts.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {assignedDepts.map((d) => (
                <Tag
                  key={d.feishu_department_id}
                  closable
                  closeIcon={<CloseOutlined style={{ fontSize: 10 }} />}
                  onClose={(e) => {
                    e.preventDefault()
                    handleRemoveDeptAssign(d.feishu_department_id)
                  }}
                  style={{ borderRadius: 6, fontSize: 12, margin: 0, padding: '2px 6px' }}
                >
                  <ApartmentOutlined style={{ fontSize: 12, marginRight: 4, color: 'var(--color-primary)' }} />
                  {d.department_name || d.feishu_department_id}
                  <span className="text-[10px] text-[var(--color-stone)] ml-1">
                    ({d.member_count}人)
                  </span>
                </Tag>
              ))}
            </div>
          ) : (
            <p className="text-[13px] text-[var(--color-muted)]">暂未分配给部门</p>
          )}
        </div>

        <p className="text-[13px] text-[var(--color-steel)] mb-3">
          选择要分配「{deptAssignRole?.name}」角色的部门（可多选，父部门分配将对所有子部门成员生效）：
        </p>
        <Select
          mode="multiple"
          placeholder="搜索部门名称…"
          value={selectedDeptIds}
          onChange={(v) => setSelectedDeptIds(v)}
          options={departments
            .filter((d) => !assignedDepts.some((ad) => ad.feishu_department_id === d.feishu_department_id))
            .map((d) => ({
              label: `${d.name}（${d.member_count ?? 0}人）`,
              value: d.feishu_department_id,
            }))}
          showSearch
          style={{ width: '100%' }}
        />
      </Modal>
    </div>
  )
}
