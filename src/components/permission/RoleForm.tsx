'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Drawer, Form, Input, Select, Button, App, Divider, Grid, Tag } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { PermissionTree } from './PermissionTree'
import { createRole, updateRole } from '@/actions/permission'
import type { Role, PermissionModuleGroup, DataScope } from '@/types/permission'

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
}

export function RoleForm({ open, onClose, onSuccess, role, permissionGroups }: Props) {
  const { message } = App.useApp()
  const router = useRouter()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [checkedPermIds, setCheckedPermIds] = useState<string[]>([])
  const [scopeOverrides, setScopeOverrides] = useState<{ module: string; scope: DataScope }[]>([])
  const isEdit = !!role
  const screens = useBreakpoint()
  const isMobile = !screens.md

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
    if (open) {
      if (role) {
        form.setFieldsValue({
          name: role.name,
          code: role.code,
          description: role.description,
          data_scope: role.data_scope,
        })
        setCheckedPermIds(role.permission_ids)
        setScopeOverrides(
          Object.entries(role.data_scope_overrides).map(([mod, scope]) => ({
            module: mod,
            scope: scope as DataScope,
          })),
        )
      } else {
        form.resetFields()
        setCheckedPermIds([])
        setScopeOverrides([])
      }
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
        await updateRole(role.id, {
          ...values,
          permission_ids: checkedPermIds,
          data_scope_overrides,
        })
        message.success('角色更新成功')
      } else {
        await createRole({
          ...values,
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
      title={isEdit ? '编辑角色' : '新建角色'}
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
        <Form.Item
          name="name"
          label="角色名称"
          rules={[{ required: true, message: '请输入角色名称' }]}
        >
          <Input placeholder="如：设备巡检员" maxLength={100} />
        </Form.Item>

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

        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} placeholder="可选：描述角色的职责范围" />
        </Form.Item>

        <Form.Item
          name="data_scope"
          label="默认数据范围"
          rules={[{ required: true }]}
        >
          <Select options={DATA_SCOPE_OPTIONS} />
        </Form.Item>

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
          <PermissionTree
            permissionGroups={permissionGroups}
            checkedIds={checkedPermIds}
            onChange={setCheckedPermIds}
          />
        </Form.Item>
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
