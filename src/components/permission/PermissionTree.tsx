'use client'

import { Tree } from 'antd'
import type { PermissionModuleGroup, Permission } from '@/types/permission'
import { useMemo } from 'react'

interface Props {
  permissionGroups: PermissionModuleGroup[]
  checkedIds: string[]
  onChange: (ids: string[]) => void
}

/** 简单 UUID 格式校验 */
function isUUID(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)
}

export function PermissionTree({ permissionGroups, checkedIds, onChange }: Props) {
  const treeData = useMemo(() => {
    return permissionGroups.map((group) => ({
      title: group.module_name,
      key: `module:${group.module}`,
      children: Object.entries(
        group.permissions.reduce<Record<string, Permission[]>>((acc, p) => {
          (acc[p.resource] ??= []).push(p)
          return acc
        }, {}),
      ).map(([resource, perms]) => ({
        title: resource,
        key: `resource:${group.module}:${resource}`,
        children: perms.map((p) => ({
          title: p.name,
          key: p.id,
        })),
      })),
    }))
  }, [permissionGroups])

  /** 收集所有叶子节点的 permission id */
  const allPermIds = useMemo(() => {
    return new Set(
      permissionGroups.flatMap((g) => g.permissions.map((p) => p.id))
    )
  }, [permissionGroups])

  return (
    <Tree
      checkable
      checkedKeys={checkedIds}
      onCheck={(keys) => {
        const allKeys = keys as string[]
        // 只保留叶子权限节点的 UUID key
        const permIds = allKeys.filter((k) => allPermIds.has(k) || isUUID(k))
        onChange(permIds)
      }}
      treeData={treeData}
      defaultExpandAll
      blockNode
      style={{ fontSize: 14 }}
      className="permission-tree"
    />
  )
}
