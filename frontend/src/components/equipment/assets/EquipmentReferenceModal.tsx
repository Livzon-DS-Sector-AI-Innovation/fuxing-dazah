'use client'

import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import type { Equipment, EquipmentReferenceGrant, EquipmentReferenceTargetModule } from '@/types/equipment'
import {
  fetchEquipmentReferenceGrantsClient,
  fetchEquipmentReferenceTargetsClient,
} from '@/lib/api/equipment-client'
import { grantEquipmentReferences, revokeEquipmentReferences } from '@/actions/equipment'

const { Text } = Typography

interface EquipmentReferenceModalProps {
  open: boolean
  equipments: Equipment[]
  onClose: () => void
}

/** 矩阵单元格：单台设备在某个模块上的授权状态。 */
function ModuleGrantCell({ grant }: { grant?: EquipmentReferenceGrant }) {
  // 无记录 = 从未授权；有记录但 revoked_at 有值 = 被显式撤销（后端保留且不会自动恢复）。
  if (!grant) return <Text type="secondary">—</Text>
  if (grant.revoked_at) return <Tag color="red">已撤销</Tag>
  return <Tag color="green">已授权</Tag>
}

export function EquipmentReferenceModal({ open, equipments, onClose }: EquipmentReferenceModalProps) {
  const { message, modal } = App.useApp()
  const [targets, setTargets] = useState<EquipmentReferenceTargetModule[]>([])
  const [targetModules, setTargetModules] = useState<string[]>([])
  const [grantsByModule, setGrantsByModule] = useState<Record<string, EquipmentReferenceGrant[]>>({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const equipmentIds = useMemo(() => equipments.map(item => item.id), [equipments])
  const moduleCount = targetModules.length

  const moduleNames = useMemo(
    () => new Map(targets.map(target => [target.code, target.name])),
    [targets],
  )
  const labelOf = (code: string) => moduleNames.get(code) ?? code

  // 后端授权按 (设备, 模块) 维度存储，这里按「模块 → 设备」建索引，供矩阵单元格直接取用。
  const grantsOf = useMemo(() => {
    const map = new Map<string, Map<string, EquipmentReferenceGrant>>()
    for (const code of targetModules) {
      const byEquipment = new Map<string, EquipmentReferenceGrant>()
      for (const grant of grantsByModule[code] ?? []) byEquipment.set(grant.equipment_id, grant)
      map.set(code, byEquipment)
    }
    return map
  }, [targetModules, grantsByModule])

  useEffect(() => {
    if (!open || equipmentIds.length === 0) return

    let cancelled = false
    const load = async () => {
      try {
        const availableTargets = await fetchEquipmentReferenceTargetsClient()
        if (cancelled) return
        setTargets(availableTargets)

        const initialTarget = availableTargets[0]?.code
        setTargetModules(initialTarget ? [initialTarget] : [])
        if (!initialTarget) return

        const initialGrants = await fetchEquipmentReferenceGrantsClient(initialTarget, equipmentIds)
        if (!cancelled) setGrantsByModule({ [initialTarget]: initialGrants })
      } catch (error) {
        if (!cancelled) message.error(error instanceof Error ? error.message : '加载引用授权失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => { cancelled = true }
  }, [open, equipmentIds, message])

  const handleModulesChange = async (values: string[]) => {
    setTargetModules(values)
    // 已加载过的模块直接复用，避免「全选」时重复拉取。
    const pending = values.filter(code => !grantsByModule[code])
    if (pending.length === 0) return
    setLoading(true)
    try {
      const results = await Promise.all(
        pending.map(code => fetchEquipmentReferenceGrantsClient(code, equipmentIds)),
      )
      setGrantsByModule(prev => {
        const next = { ...prev }
        pending.forEach((code, index) => { next[code] = results[index] })
        return next
      })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载引用授权失败')
    } finally {
      setLoading(false)
    }
  }

  /** 对每个已选模块并发调用，逐个汇总成功/失败，避免一个模块失败丢掉其余结果。 */
  const runForModules = async (
    action: (code: string, ids: string[]) => Promise<
      { success: true; data: unknown } | { success: false; error: string }
    >,
  ): Promise<{ ok: number; failed: string[] }> => {
    const results = await Promise.allSettled(
      targetModules.map(async code => {
        const result = await action(code, equipmentIds)
        if (!result.success) throw new Error(result.error)
        return (result.data ?? []) as EquipmentReferenceGrant[]
      }),
    )
    const updated: Record<string, EquipmentReferenceGrant[]> = {}
    const failed: string[] = []
    results.forEach((result, index) => {
      const code = targetModules[index]
      if (result.status === 'fulfilled') updated[code] = result.value
      else failed.push(code)
    })
    if (Object.keys(updated).length > 0) {
      setGrantsByModule(prev => ({ ...prev, ...updated }))
    }
    return { ok: Object.keys(updated).length, failed }
  }

  const handleGrant = async () => {
    if (moduleCount === 0) return
    setSubmitting(true)
    try {
      const { ok, failed } = await runForModules(grantEquipmentReferences)
      if (failed.length === 0) {
        message.success(`已授权 ${equipments.length} 台设备到 ${ok} 个模块`)
      } else {
        message.warning(`${failed.map(labelOf).join('、')}授权失败，其余 ${ok} 个模块已成功`)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevoke = () => {
    if (moduleCount === 0) return
    const scope = moduleCount === 1 ? labelOf(targetModules[0]) : `所选 ${moduleCount} 个模块`
    modal.confirm({
      title: '确认撤销引用授权',
      content: `撤销后，${scope}不能再新建或换绑到所选设备；已有业务记录不受影响。`,
      okText: '确认撤销',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        setSubmitting(true)
        try {
          const { ok, failed } = await runForModules(revokeEquipmentReferences)
          if (failed.length === 0) {
            message.success(`已撤销 ${equipments.length} 台设备在 ${ok} 个模块的授权`)
          } else {
            message.warning(`${failed.map(labelOf).join('、')}撤销失败，其余 ${ok} 个模块已成功`)
          }
        } finally {
          setSubmitting(false)
        }
      },
    })
  }

  const counts = equipments.reduce(
    (result, equipment) => {
      if (moduleCount === 0) return result
      let active = 0
      for (const code of targetModules) {
        const grant = grantsOf.get(code)?.get(equipment.id)
        if (grant && !grant.revoked_at) active += 1
      }
      if (active === moduleCount) result.full += 1
      else if (active > 0) result.partial += 1
      else result.none += 1
      return result
    },
    { full: 0, partial: 0, none: 0 },
  )

  return (
    <Modal
      open={open}
      title={`设备引用授权（${equipments.length} 台）`}
      width={960}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="close" onClick={onClose}>关闭</Button>,
        <Button key="revoke" danger disabled={moduleCount === 0 || loading} loading={submitting} onClick={handleRevoke}>
          撤销授权
        </Button>,
        <Button key="grant" type="primary" disabled={moduleCount === 0 || loading} loading={submitting} onClick={() => { void handleGrant() }}>
          授权 / 重新授权
        </Button>,
      ]}
    >
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          title="只开放设备编号、名称和状态等引用摘要，不开放设备详情、供应商或技术参数。可同时选择多个目标模块，授权与撤销会作用于全部已选模块。"
        />
        <div>
          <Space size={4}>
            <Text strong>目标模块</Text>
            <Button
              type="link"
              size="small"
              disabled={targets.length === 0 || moduleCount === targets.length}
              onClick={() => { void handleModulesChange(targets.map(target => target.code)) }}
            >
              全选
            </Button>
            <Button
              type="link"
              size="small"
              disabled={moduleCount === 0}
              onClick={() => { void handleModulesChange([]) }}
            >
              清空
            </Button>
            <Text type="secondary">已选 {moduleCount}/{targets.length}</Text>
          </Space>
          <Select
            mode="multiple"
            style={{ width: '100%', marginTop: 8 }}
            placeholder="请选择目标业务模块"
            value={targetModules}
            loading={loading && targets.length === 0}
            maxTagCount="responsive"
            options={targets.map(target => ({
              value: target.code,
              label: target.name,
            }))}
            onChange={(values: string[]) => { void handleModulesChange(values) }}
          />
        </div>
        <Space wrap>
          <Text type="secondary">当前状态：</Text>
          <Tag color="green">全部授权 {counts.full}</Tag>
          <Tag color="orange">部分授权 {counts.partial}</Tag>
          <Tag>未授权 {counts.none}</Tag>
        </Space>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          pagination={false}
          scroll={{ x: 'max-content', y: 280 }}
          dataSource={equipments}
          columns={[
            { title: '设备编号', dataIndex: 'equipment_no', width: 160, fixed: 'start' as const },
            { title: '设备名称', dataIndex: 'name', width: 160, ellipsis: true, fixed: 'start' as const },
            // 已选模块横向铺成列，授权/未授权/已撤销在一行内直接可比。
            ...(moduleCount === 0
              ? [{ title: '授权状态', key: 'no_module', render: () => <Text type="secondary">未选择模块</Text> }]
              : targetModules.map(code => ({
                  title: labelOf(code),
                  key: `module_${code}`,
                  width: 88,
                  align: 'center' as const,
                  render: (_value: unknown, record: Equipment) => (
                    <ModuleGrantCell grant={grantsOf.get(code)?.get(record.id)} />
                  ),
                }))),
          ]}
        />
      </Space>
    </Modal>
  )
}
