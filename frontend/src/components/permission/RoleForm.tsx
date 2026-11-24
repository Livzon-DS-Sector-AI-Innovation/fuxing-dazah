'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Drawer, Form, Input, Select, Button, App, Divider, Grid } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { PermissionTree } from './PermissionTree'
import { createRole, updateRole } from '@/actions/permission'
import { usePermission } from '@/hooks/usePermission'
import type { Role, PermissionModuleGroup, DataScope, DepartmentItem } from '@/types/permission'

const { useBreakpoint } = Grid

const DATA_SCOPE_OPTIONS: { label: string; value: DataScope }[] = [
  { label: '全部数据', value: 'all' },
  { label: '本部门及下级', value: 'department_and_children' },
  { label: '仅本部门', value: 'department' },
  { label: '仅自己', value: 'self_only' },
]

interface Props {
  open: boolean
  onClose: () => void
  onSuccess?: () => void
  role?: Role | null
  permissionGroups: PermissionModuleGroup[]
  departments: DepartmentItem[]
}

export function RoleForm({ open, onClose, onSuccess, role, permissionGroups, departments }: Props) {
  const { message } = App.useApp()
  const router = useRouter()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  // 打开时由父组件以 key 重挂载（见 RoleList），状态直接从 props 初始化，
  // 避免在 effect 里同步 setState 的 cascading render
  const [checkedPermIds, setCheckedPermIds] = useState<string[]>(
    () => role?.permission_ids ?? [],
  )
  const [scopeOverrides, setScopeOverrides] = useState<{ module: string; scope: DataScope }[]>(
    () =>
      Object.entries(role?.data_scope_overrides ?? {}).map(([mod, scope]) => ({
        module: mod,
        scope: scope as DataScope,
      })),
  )
  const isEdit = !!role
  const isSystemEdit = isEdit && !!role?.is_system
  const screens = useBreakpoint()
  const isMobile = !screens.md

  const { permissions, hasPermission } = usePermission()
  const canManageAll = hasPermission('permission:role:manage')
  // 委派管理员只能勾选自己已有的权限码（数据范围由后端校验）
  const allowedIds = useMemo(
    () =>
      canManageAll
        ? undefined
        : new Set(
            permissionGroups.flatMap((g) =>
              g.permissions
                .filter((p) => permissions.has(p.code))
                .map((p) => p.id),
            ),
          ),
    [canManageAll, permissionGroups, permissions],
  )

  const groupOptions = departments.map((d) => ({
    label: d.name,
    value: d.feishu_department_id,
  }))

  // 可用模块列表（从 permissionGroups 提取）
  const moduleOptions = useMemo(
    () =>
      permissionGroups.map((g) => ({
        value: g.module,
        label: `${g.module_name} (${g.module})`,
      })),
    [permissionGroups],
  )

  useEffect(() => {
    if (!open) return
    if (role) {
      form.setFieldsValue({
        name: role.name,
        code: role.code,
        description: role.description,
        data_scope: role.data_scope,
        group_feishu_department_id: role.group_feishu_department_id ?? undefined,
      })
    } else {
      form.resetFields()
    }
  }, [open, role, form])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)

    // 构建 data_scope_overrides dict
    const data_scope_overrides: Record<string, DataScope> = {}
    for (const ov of scopeOverrides) {
      if (ov.module) data_scope_overrides[ov.module] = ov.scope
    }

    try {
      if (isEdit && role) {
        if (role.is_system) {
          // 系统内置角色后端仅放行分组字段，其余字段一并提交会被 403
          await updateRole(role.id, {
            group_feishu_department_id: values.group_feishu_department_id ?? null,
          })
        } else {
          await updateRole(role.id, {
            ...values,
            // 显式传 null 以支持清空分组（后端按字段是否显式提供区分「不改」与「清空」）
            group_feishu_department_id: values.group_feishu_department_id ?? null,
            permission_ids: checkedPermIds,
            data_scope_overrides,
          })
        }
        message.success('角色更新成功')
      } else {
        await createRole({
          ...values,
          group_feishu_department_id: values.group_feishu_department_id ?? null,
          permission_ids: checkedPermIds,
          data_scope_overrides,
        })
        message.success('角色创建成功')
      }
      onSuccess?.()
      router.refresh()
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '操作失败'
      message.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Drawer
      title={isSystemEdit ? `调整分组 · ${role?.name ?? ''}` : isEdit ? '编辑角色' : '新建角色'}
      open={open}
      onClose={onClose}
      styles={{
        wrapper: { width: isMobile ? '100%' : 640, maxWidth: '100vw' },
        body: { paddingBottom: isMobile ? 80 : 24 },
      }}
      extra={
        !isMobile ? (
          <Button type="primary" loading={loading} onClick={handleSubmit}>
            保存
          </Button>
        ) : undefined
      }
    >
      <Form
        form={form}
        layout="vertical"
        size="large"
        initialValues={{ data_scope: 'department' }}
      >
        {isSystemEdit && (
          <p
            style={{
              fontSize: 13,
              color: 'var(--color-steel)',
              background: 'rgba(86, 69, 212, 0.06)',
              borderRadius: 8,
              padding: '10px 12px',
              marginBottom: 16,
            }}
          >
            系统内置角色仅支持调整分组，其余配置不可修改。
          </p>
        )}

        {!isSystemEdit && (
          <Form.Item
            name="name"
            label="角色名称"
            rules={[{ required: true, message: '请输入角色名称' }]}
          >
            <Input placeholder="如：设备巡检员" maxLength={100} />
          </Form.Item>
        )}

        {!isSystemEdit && (
          <Form.Item
            name="code"
            label="角色编码"
            rules={[
              { required: true, message: '请输入角色编码' },
              { pattern: /^[a-z][a-z0-9_]*$/, message: '小写字母开头，仅含小写字母、数字、下划线' },
            ]}
            help={!isEdit ? '创建后不可修改' : undefined}
          >
            <Input disabled={isEdit} placeholder="如：equipment_inspector" maxLength={50} />
          </Form.Item>
        )}

        {!isSystemEdit && (
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="可选：描述角色的职责范围" />
          </Form.Item>
        )}

        <Form.Item
          name="group_feishu_department_id"
          label="分组（飞书部门）"
          help="按部门分区展示角色看板，可不选（归入「未分组」）"
        >
          <Select
            options={groupOptions}
            placeholder="搜索部门名称…"
            allowClear
            showSearch
            optionFilterProp="label"
          />
        </Form.Item>

        {!isSystemEdit && (
          <Form.Item
            name="data_scope"
            label="默认数据范围"
            rules={[{ required: true }]}
          >
            <Select options={DATA_SCOPE_OPTIONS} />
          </Form.Item>
        )}

        {!isSystemEdit && (
        <>
        {/* 按模块覆盖数据范围 */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>按模块覆盖数据范围</span>
            <Button
              type="link"
              icon={<PlusOutlined />}
              size="small"
              onClick={() => setScopeOverrides([...scopeOverrides, { module: '', scope: 'department' }])}
            >
              添加覆盖
            </Button>
          </div>
          {scopeOverrides.length === 0 && (
            <p style={{ color: 'var(--color-muted)', fontSize: 13 }}>
              不覆盖则使用默认数据范围。可为特定模块设置不同的数据访问级别。
            </p>
          )}
          {scopeOverrides.map((ov, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                marginBottom: 8,
              }}
            >
              <Select
                placeholder="选择模块"
                value={ov.module || undefined}
                onChange={(v) => {
                  const next = [...scopeOverrides]
                  next[idx] = { ...next[idx], module: v }
                  setScopeOverrides(next)
                }}
                options={moduleOptions.filter(
                  (m) => !scopeOverrides.some((o, i) => i !== idx && o.module === m.value),
                )}
                style={{ flex: 1 }}
                showSearch
              />
              <Select
                value={ov.scope}
                onChange={(v) => {
                  const next = [...scopeOverrides]
                  next[idx] = { ...next[idx], scope: v }
                  setScopeOverrides(next)
                }}
                options={DATA_SCOPE_OPTIONS}
                style={{ width: 140 }}
              />
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => setScopeOverrides(scopeOverrides.filter((_, i) => i !== idx))}
              />
            </div>
          ))}
        </div>

        <Divider />

        <Form.Item
          label={
            <span>
              权限配置
              <span style={{ color: 'var(--color-steel)', fontSize: 13, marginLeft: 8, fontWeight: 400 }}>
                (已选 {checkedPermIds.length})
              </span>
            </span>
          }
        >
          {!canManageAll && (
            <p style={{ color: 'var(--color-steel)', fontSize: 12, margin: '0 0 8px' }}>
              只能勾选自己已有的权限；数据范围不能超过你自身的范围。
            </p>
          )}
          <PermissionTree
            permissionGroups={permissionGroups}
            checkedIds={checkedPermIds}
            onChange={setCheckedPermIds}
            allowedIds={allowedIds}
          />
        </Form.Item>
        </>
        )}
      </Form>

      {isMobile && (
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            background: '#fff',
            padding: '12px 16px',
            borderTop: '1px solid var(--color-hairline)',
            marginTop: -24,
            marginLeft: -24,
            marginRight: -24,
            zIndex: 10,
          }}
        >
          <Button
            type="primary"
            loading={loading}
            onClick={handleSubmit}
            block
            size="large"
            style={{ height: 48, borderRadius: 10, fontWeight: 500, fontSize: 16 }}
          >
            保存
          </Button>
        </div>
      )}
    </Drawer>
  )
}
