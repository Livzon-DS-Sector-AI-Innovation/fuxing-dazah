'use client'

// 环境坐标组（V3.0 分期D §3.3）：当前环境徽标 + 切换 + 生产版坐标折叠编辑。
// 切 prod 属上线动作（前置：双跑零差异 + 零回写探针），二次确认文案内置提醒。

import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import {
  getWarehouseBitableEnvConnections,
  getWarehouseBitableEnvMode,
  setWarehouseBitableEnvMode,
  updateWarehouseBitableEnvConnection,
} from '@/actions/warehouse'
import type { WarehouseBitableView } from '@/types/warehouse'

const PROD = 'prod'
const TEST = 'test'

function EnvTag({ mode }: { mode: string }) {
  return mode === PROD ? (
    <Tag color="red" style={{ marginInlineEnd: 0 }}>
      生产版 Base
    </Tag>
  ) : (
    <Tag color="green" style={{ marginInlineEnd: 0 }}>
      测试版 Base
    </Tag>
  )
}

interface EnvRowDraft {
  base_token: string
  table_id: string
}

function ProdEditModal({
  view,
  canUpdate,
  onClose,
  onSaved,
}: {
  view: WarehouseBitableView
  canUpdate: boolean
  onClose: () => void
  onSaved: (view: WarehouseBitableView) => void
}) {
  const [draft, setDraft] = useState<EnvRowDraft>({ base_token: '', table_id: String(view.table_id ?? '') })
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const fresh = await updateWarehouseBitableEnvConnection(PROD, view.table_key, {
        base_token: draft.base_token.trim(),
        table_id: draft.table_id.trim(),
      })
      onSaved(fresh)
      onClose()
    } catch (e) {
      Modal.error({ title: '保存失败', content: e instanceof Error ? e.message : '未知错误' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`生产版坐标 · ${view.name_cn || view.table_key}`}
      open
      onCancel={onClose}
      onOk={() => void save()}
      okText="保存"
      confirmLoading={saving}
      okButtonProps={{ disabled: !canUpdate }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
        <Input.Password
          placeholder={view.base_token === '未配置' ? '生产版 Base app_token' : view.base_token}
          autoComplete="new-password"
          disabled={!canUpdate || saving}
          value={draft.base_token}
          onChange={(e) => setDraft({ ...draft, base_token: e.target.value })}
        />
        <Input
          placeholder="tbl…（生产版 table_id）"
          disabled={!canUpdate || saving}
          value={draft.table_id}
          onChange={(e) => setDraft({ ...draft, table_id: e.target.value })}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          留空提交 = 清空该行覆盖（回退测试版坐标/env/代码快照）。切 prod 前置：双跑比对零差异 + 零回写探针。
        </Typography.Text>
      </div>
    </Modal>
  )
}

export default function BitableEnvBar({
  canUpdate,
  onChanged,
}: {
  canUpdate: boolean
  onChanged?: () => void
}) {
  const [mode, setMode] = useState<string | null>(null)
  const [prodRows, setProdRows] = useState<WarehouseBitableView[] | null>(null)
  const [editing, setEditing] = useState<WarehouseBitableView | null>(null)

  const loadMode = useCallback(async () => {
    try {
      setMode(await getWarehouseBitableEnvMode())
    } catch {
      setMode(TEST)
    }
  }, [])

  const loadProd = useCallback(async () => {
    try {
      const data = await getWarehouseBitableEnvConnections(PROD)
      setProdRows(data.connections ?? [])
    } catch {
      setProdRows([])
    }
  }, [])

  useEffect(() => {
    void loadMode()
  }, [loadMode])

  const handleSwitch = () => {
    const target = mode === PROD ? TEST : PROD
    Modal.confirm({
      title: target === PROD ? '切换到生产版 Base？' : '切回测试版 Base？',
      content:
        target === PROD
          ? '上线前置：① 双跑比对零差异；② 零回写探针 PASS；③ 生产版 Base 结构已同步（建表/建列）。切换即时生效。'
          : '系统将恢复使用测试版 Base 坐标，即时生效。',
      okText: '确认切换',
      cancelText: '取消',
      okButtonProps: { danger: target === PROD },
      onOk: async () => {
        try {
          const applied = await setWarehouseBitableEnvMode(target)
          setMode(applied)
          onChanged?.()
        } catch (e) {
          Modal.error({
            title: '切换失败',
            content: e instanceof Error ? e.message : '未知错误',
          })
        }
      },
    })
  }

  const columns: TableColumnsType<WarehouseBitableView> = [
    { title: '表', dataIndex: 'name_cn', render: (v, r) => v || r.table_key },
    { title: 'table_key', dataIndex: 'table_key', width: 200 },
    { title: 'base_token', dataIndex: 'base_token', width: 140 },
    { title: 'table_id', dataIndex: 'table_id', width: 160 },
    {
      title: '操作',
      width: 80,
      render: (_, record) => (
        <Button size="small" disabled={!canUpdate} onClick={() => setEditing(record)}>
          编辑
        </Button>
      ),
    },
  ]

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 10,
        padding: '10px 14px',
        marginBottom: 14,
        border: '1px solid var(--color-border, #e5e7eb)',
        borderRadius: 10,
      }}
      data-testid="wh-bitable-env-bar"
    >
      <span style={{ fontSize: 13, fontWeight: 600 }}>坐标环境</span>
      <EnvTag mode={mode ?? TEST} />
      <span style={{ fontSize: 12, color: 'var(--color-steel, #6b7280)' }}>
        系统按当前环境解析全部表坐标；测试/生产双组坐标独立维护。
      </span>
      <span style={{ flex: 1 }} />
      <Space size={8}>
        <Button size="small" disabled={!canUpdate} onClick={handleSwitch}>
          切换到{mode === PROD ? '测试版' : '生产版'}
        </Button>
      </Space>
      <Collapse
        ghost
        style={{ width: '100%' }}
        items={[
          {
            key: 'prod',
            label: '生产版坐标配置（prod 组，上线前维护）',
            children: (
              <Table<WarehouseBitableView>
                rowKey="table_key"
                size="small"
                columns={columns}
                dataSource={prodRows ?? []}
                loading={prodRows === null}
                onRow={(record) => ({
                  onClick: () => canUpdate && setEditing(record),
                })}
                pagination={false}
              />
            ),
          },
        ]}
        onChange={(keys) => {
          if (keys.length > 0 && prodRows === null) void loadProd()
        }}
      />
      {editing && (
        <ProdEditModal
          view={editing}
          canUpdate={canUpdate}
          onClose={() => setEditing(null)}
          onSaved={(fresh) => {
            setProdRows((prev) =>
              prev ? prev.map((r) => (r.table_key === fresh.table_key ? fresh : r)) : prev,
            )
            onChanged?.()
          }}
        />
      )}
      {mode === PROD && (
        <Alert
          type="warning"
          showIcon
          style={{ width: '100%' }}
          message="当前处于生产版环境：所有读写均指向生产版 Base，请谨慎操作。"
        />
      )}
    </div>
  )
}
