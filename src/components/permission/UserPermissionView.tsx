'use client'

import { useState, useEffect, useMemo } from 'react'
import {
  Input, Tag, Spin, Empty, App, Button, Modal, Select, Avatar,
} from 'antd'
import {
  SearchOutlined, UserOutlined, PlusOutlined,
  SafetyCertificateOutlined, KeyOutlined, CloseOutlined, SwapOutlined,
} from '@ant-design/icons'
import { startImpersonate } from '@/actions/auth'
import { fetchPersonnel, fetchDepartments, fetchUserPermissions } from '@/lib/api/permission'
import { assignRoleToUser, removeRoleFromUser } from '@/actions/permission'
import type {
  PersonnelItem, DepartmentItem, UserPermissionDetail,
  Role,
} from '@/types/permission'

const SCOPE_LABELS: Record<string, string> = {
  all: '全部数据',
  department_and_children: '本部门及下级',
  department: '本部门',
  self_only: '仅自己',
}

interface Props {
  apiToken: string
  availableRoles: Role[]
}

export function UserPermissionView({ apiToken, availableRoles }: Props) {
  const { message, modal } = App.useApp()

  // ── User list state ──
  const [allUsers, setAllUsers] = useState<PersonnelItem[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [departmentId, setDepartmentId] = useState<string | undefined>()
  const [departments, setDepartments] = useState<DepartmentItem[]>([])

  // ── Client-side filtered users ──
  const users = useMemo(() => {
    let result = allUsers
    if (departmentId) {
      const dept = departments.find((d) => d.feishu_department_id === departmentId)
      if (dept) {
        result = result.filter((u) => u.department === dept.name)
      }
    }
    if (search) {
      const kw = search.toLowerCase()
      result = result.filter(
        (u) => u.name.toLowerCase().includes(kw) || (u.employee_no || '').toLowerCase().includes(kw),
      )
    }
    return result
  }, [allUsers, search, departmentId, departments])
  // ── Selected user state ──
  const [selectedUser, setSelectedUser] = useState<PersonnelItem | null>(null)
  const [userDetail, setUserDetail] = useState<UserPermissionDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // ── Assign role state ──
  const [assignOpen, setAssignOpen] = useState(false)
  const [selectedRoleId, setSelectedRoleId] = useState<string | undefined>()
  const [assigning, setAssigning] = useState(false)

  // ── Mobile: show detail vs list ──
  const [showDetail, setShowDetail] = useState(false)

  // ── Load departments on mount ──
  useEffect(() => {
    fetchDepartments().then(setDepartments).catch(() => {})
  }, [])

  // ── Load all personnel once ──
  useEffect(() => {
    setLoading(true)
    fetchPersonnel({ offset: 0, limit: 9999 })
      .then((result) => setAllUsers(result.items))
      .catch(() => message.error('获取人员列表失败'))
      .finally(() => setLoading(false))
  }, [])

  const handleSearch = () => {
    // Client-side filtering via useMemo — no-op, just trigger re-render
    setSearch((s) => s)
  }

  const handleDeptChange = (v: string | undefined) => {
    setDepartmentId(v)
  }

  // ── Select user → load detail ──
  const handleSelectUser = async (user: PersonnelItem) => {
    setSelectedUser(user)
    setShowDetail(true)
    setDetailLoading(true)
    try {
      const detail = await fetchUserPermissions(apiToken, user.id)
      setUserDetail(detail)
    } catch {
      message.error('获取用户权限失败')
      setUserDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }

  // ── Assign role ──
  const handleAssign = async () => {
    if (!userDetail || !selectedRoleId) return
    setAssigning(true)
    try {
      await assignRoleToUser(userDetail.user_id, { role_id: selectedRoleId })
      message.success('角色分配成功')
      setAssignOpen(false)
      setSelectedRoleId(undefined)
      const detail = await fetchUserPermissions(apiToken, userDetail.user_id)
      setUserDetail(detail)
    } catch {
      message.error('分配角色失败')
    } finally {
      setAssigning(false)
    }
  }

  // ── Remove role ──
  const handleRemove = async (roleId: string) => {
    if (!userDetail) return
    try {
      await removeRoleFromUser(userDetail.user_id, roleId)
      message.success('角色已移除')
      const detail = await fetchUserPermissions(apiToken, userDetail.user_id)
      setUserDetail(detail)
    } catch {
      message.error('移除角色失败')
    }
  }

  // ── Impersonate ──
  const handleImpersonate = (user: PersonnelItem) => {
    modal.confirm({
      title: '切换用户身份',
      content: (
        <p>
          即将以 <strong>{user.name}</strong>
          （{user.department || '—'} · {user.position || '—'}）
          的身份浏览系统，菜单和权限将按该用户展示。确认开始？
        </p>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        await startImpersonate(user.id)
        window.location.reload()
      },
    })
  }

  const assignableRoles = availableRoles.filter(
    (r) => !userDetail?.roles.some((ur) => ur.role_id === r.id),
  )

  // ── Detail panel content (reused in desktop + mobile) ──
  const renderDetail = () => {
    if (!selectedUser) return null
    if (detailLoading) return <Spin className="flex justify-center pt-16" />
    if (!userDetail) return null

    return (
      <div className="flex flex-col gap-4">
        {/* User info header */}
        <div
          className="flex items-center gap-3 pb-4"
          style={{ borderBottom: '1px solid var(--color-hairline)' }}
        >
          <Avatar
            src={selectedUser.avatar_url}
            size={48}
            style={{ flexShrink: 0, backgroundColor: 'var(--color-primary)', fontSize: 16, fontWeight: 600 }}
          >
            {selectedUser.name.charAt(0)}
          </Avatar>
          <div>
            <div className="text-[18px] font-semibold text-[var(--color-ink)]">
              {selectedUser.name}
            </div>
            <div className="text-[12px] text-[var(--color-steel)] flex flex-wrap gap-x-3 gap-y-0.5">
              {selectedUser.employee_no && <span>工号 {selectedUser.employee_no}</span>}
              {selectedUser.department && <span>{selectedUser.department}</span>}
              {selectedUser.position && <span>{selectedUser.position}</span>}
            </div>
          </div>
        </div>

        {/* Roles */}
        <div
          className="p-4 rounded-[12px] border"
          style={{ borderColor: 'var(--color-hairline)' }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-[13px] font-medium text-[var(--color-charcoal)]">
              已分配角色
            </span>
            <Button
              type="link"
              icon={<PlusOutlined />}
              size="small"
              onClick={() => setAssignOpen(true)}
            >
              分配角色
            </Button>
          </div>
          {userDetail.roles.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {userDetail.roles.map((r) => (
                <Tag
                  key={r.role_id}
                  closable
                  closeIcon={<CloseOutlined style={{ fontSize: 10 }} />}
                  onClose={() => handleRemove(r.role_id)}
                  style={{ borderRadius: 6, fontSize: 12, margin: 0 }}
                >
                  <SafetyCertificateOutlined
                    style={{ fontSize: 12, marginRight: 4, color: 'var(--color-primary)' }}
                  />
                  {r.role_name}
                  <code className="text-[10px] text-[var(--color-stone)] ml-1">
                    {r.role_code}
                  </code>
                </Tag>
              ))}
            </div>
          ) : (
            <p className="text-[13px] text-[var(--color-muted)]">
              暂无角色，点击「分配角色」开始配置
            </p>
          )}
        </div>

        {/* Data Scopes */}
        <div
          className="p-4 rounded-[12px] border"
          style={{ borderColor: 'var(--color-hairline)' }}
        >
          <span className="text-[13px] font-medium text-[var(--color-charcoal)] mb-3 block">
            数据范围
          </span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(userDetail.data_scopes).map(([mod, scope]) => (
              <Tag key={mod} style={{ borderRadius: 6, fontSize: 12, margin: 0 }}>
                <span className="font-medium">{mod}</span>
                : {SCOPE_LABELS[scope] || scope}
              </Tag>
            ))}
          </div>
        </div>

        {/* Permissions */}
        <div
          className="p-4 rounded-[12px] border"
          style={{ borderColor: 'var(--color-hairline)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <KeyOutlined style={{ fontSize: 14, color: 'var(--color-steel)' }} />
            <span className="text-[13px] font-medium text-[var(--color-charcoal)]">
              有效权限 ({userDetail.permissions.length})
            </span>
          </div>
          {userDetail.permissions.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {userDetail.permissions.map((p) => (
                <Tag key={p} style={{ borderRadius: 6, fontSize: 11, margin: 0 }}>
                  <code>{p}</code>
                </Tag>
              ))}
            </div>
          ) : (
            <p className="text-[13px] text-[var(--color-muted)]">该用户暂无权限</p>
          )}
        </div>
      </div>
    )
  }

  // ── User list panel (reused in both layouts) ──
  const renderUserList = () => (
    <>
      {/* Toolbar */}
      <div className="flex flex-col gap-2 mb-3">
        <Input.Search
          placeholder="搜索姓名或工号…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={handleSearch}
          enterButton={<SearchOutlined />}
          size="middle"
          style={{ borderRadius: 10 }}
        />
        <Select
          placeholder="全部部门"
          allowClear
          value={departmentId}
          onChange={handleDeptChange}
          options={departments.map((d) => ({ label: d.name, value: d.feishu_department_id }))}
          showSearch
          style={{ borderRadius: 10 }}
        />
      </div>

      {/* List */}
      <div
        className="flex-1 overflow-auto min-h-0"
      >
        {!loading && users.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span className="text-[13px] text-[var(--color-steel)]">
                {search ? `没有匹配「${search}」的用户` : '暂无用户数据'}
              </span>
            }
          />
        ) : (
          <div className="flex flex-col gap-0.5">
            {users.map((user) => (
              <div
                key={user.id}
                onClick={() => handleSelectUser(user)}
                className="flex items-center gap-3 px-3 py-2.5 rounded-[8px] cursor-pointer transition-colors"
                style={{
                  backgroundColor:
                    selectedUser?.id === user.id
                      ? 'rgba(86, 69, 212, 0.08)'
                      : 'transparent',
                  borderLeft:
                    selectedUser?.id === user.id
                      ? '3px solid var(--color-primary)'
                      : '3px solid transparent',
                }}
              >
                <Avatar
                  src={user.avatar_url}
                  size={36}
                  style={{ flexShrink: 0, backgroundColor: 'var(--color-primary)', fontSize: 13 }}
                >
                  {user.name.charAt(0)}
                </Avatar>
                <div className="min-w-0">
                  <div className="text-[14px] font-medium text-[var(--color-ink)] truncate">
                    {user.name}
                  </div>
                  <div className="text-[11px] text-[var(--color-steel)] truncate">
                    {user.department || '—'} · {user.employee_no || '—'}
                  </div>
                </div>
                <Button
                  type="text"
                  size="small"
                  icon={<SwapOutlined />}
                  title="以此用户身份浏览"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleImpersonate(user)
                  }}
                  style={{
                    marginLeft: 'auto',
                    flexShrink: 0,
                    color: 'var(--color-steel)',
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )

  return (
    <div
      className="h-full flex flex-col gap-4 sm:gap-6 p-4 sm:p-6 overflow-hidden"
      style={{ backgroundColor: 'var(--color-surface)' }}
    >
      {/* ═══ Layer 1: Header Card ═══ */}
      <div
        className="rounded-[16px] border p-5 sm:p-6"
        style={{
          backgroundColor: 'var(--color-canvas)',
          borderColor: 'var(--color-hairline)',
          borderTop: '3px solid var(--color-primary)',
        }}
      >
        <div className="flex items-center gap-3.5">
          <div
            className="w-10 h-10 rounded-[10px] flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            <UserOutlined style={{ fontSize: 20, color: '#fff' }} />
          </div>
          <div>
            <h1 className="text-[20px] sm:text-[22px] font-semibold text-[var(--color-ink)] tracking-tight leading-tight">
              用户权限
            </h1>
            <p className="text-[13px] text-[var(--color-steel)] mt-0.5">
              管理系统用户角色分配与权限查看
            </p>
          </div>
        </div>
      </div>

      {/* ═══ Layer 2: Content Panel ═══ */}
      <div
        className="rounded-[16px] border p-4 sm:p-6 flex-1 flex flex-col overflow-hidden"
        style={{
          backgroundColor: 'var(--color-canvas)',
          borderColor: 'var(--color-hairline)',
        }}
      >
        {/* ── Desktop: dual panel ── */}
        <div className="hidden md:flex gap-5 flex-1 min-h-0 overflow-hidden">
          {/* Left: user list */}
          <div className="w-[340px] flex-shrink-0 flex flex-col min-h-0">
            {renderUserList()}
          </div>

          {/* Right: permission detail */}
          <div className="flex-1 min-w-0 overflow-auto">
            {!selectedUser ? (
              <div className="flex items-center justify-center h-full">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    <span className="text-[13px] text-[var(--color-steel)]">
                      👈 从左侧列表选择用户以查看权限详情
                    </span>
                  }
                />
              </div>
            ) : (
              renderDetail()
            )}
          </div>
        </div>

        {/* ── Mobile: toggle list / detail ── */}
        <div className="md:hidden flex-1 flex flex-col min-h-0">
          {!showDetail ? (
            <div className="flex flex-col flex-1 min-h-0">
              {renderUserList()}
            </div>
          ) : (
            <div className="flex-1 flex flex-col min-h-0 overflow-auto">
              <Button
                type="text"
                onClick={() => setShowDetail(false)}
                style={{ padding: 0, marginBottom: 16, fontSize: 14, color: 'var(--color-steel)' }}
              >
                ← 用户权限
              </Button>
              {renderDetail()}
            </div>
          )}
        </div>
      </div>

      {/* ── Assign role modal ── */}
      <Modal
        title="分配角色"
        open={assignOpen}
        onCancel={() => { setAssignOpen(false); setSelectedRoleId(undefined) }}
        onOk={handleAssign}
        confirmLoading={assigning}
        okText="确认分配"
        cancelText="取消"
        okButtonProps={{ disabled: !selectedRoleId }}
      >
        <p className="text-[13px] text-[var(--color-steel)] mb-3">
          为用户 <strong>{selectedUser?.name}</strong> 选择要分配的角色：
        </p>
        <Select
          placeholder="选择角色"
          style={{ width: '100%' }}
          value={selectedRoleId}
          onChange={setSelectedRoleId}
          options={assignableRoles.map((r) => ({
            label: `${r.name} (${r.code})`,
            value: r.id,
          }))}
          showSearch
        />
        {assignableRoles.length === 0 && (
          <p className="text-[13px] text-[var(--color-muted)] mt-3">
            所有角色已分配给该用户
          </p>
        )}
      </Modal>
    </div>
  )
}
