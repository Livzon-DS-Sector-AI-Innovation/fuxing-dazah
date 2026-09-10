'use client'

// 连接配置编辑/新增抽屉（design.md §2.1 / §5.1）
// - kind：编辑时只读展示；新增（行「配置」）固定当前行；新增（页头「+新增」）下拉选择未配置 kind
// - app_token / table_id 必填 + trim（粘贴常带空格）；不做正则强校验
// - 抽屉内「测试连接」用表单当前值；「保存」→ Modal.confirm（保存即生效+自动重订阅）→ PUT
// - 保存失败保持编辑态不关闭（草稿不丢）

import { useEffect, useMemo, useState } from 'react'
import { App, Button, Drawer, Form, Input, Modal, Select, Space, Switch } from 'antd'
import { LinkOutlined } from '@ant-design/icons'

import { updateBitableConnection } from '@/actions/safety'
import type { BitableConnection, BitableDomainOverview } from '@/types/safety'
import { MONO_FONT, UI } from './bitableConfigConstants'
import BitableTestConnectionModal from './BitableTestConnectionModal'

interface BitableConnectionEditDrawerProps {
  open: boolean
  mode: 'new' | 'edit'
  domain: BitableDomainOverview | null
  /** 固定 kind（行「配置」/ 编辑）；为空时新增模式用 Select 选未配置 kind */
  kind?: string | null
  record?: BitableConnection | null
  onClose: () => void
  onSaved: () => void
}

interface FormValues {
  kind?: string
  app_token: string
  table_id: string
  enabled: boolean
  note?: string
}

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: UI.slate,
  marginBottom: 6,
}

export default function BitableConnectionEditDrawer({
  open,
  mode,
  domain,
  kind,
  record,
  onClose,
  onSaved,
}: BitableConnectionEditDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)
  const [testOpen, setTestOpen] = useState(false)

  /** 新增模式可选 kind：该域注册表中「未配置」的表类型 */
  const missingKinds = useMemo(
    () => (domain?.kinds ?? []).filter((k) => k.status === 'missing'),
    [domain],
  )

  /** 新增模式预填 app_token：同域其他 kind 已存 token（体验增强，非逻辑依赖，design.md §2.3） */
  const prefillToken = useMemo(() => {
    const first = (domain?.kinds ?? []).find((k) => k.app_token)
    return first?.app_token ?? ''
  }, [domain])

  const fixedKind = mode === 'edit' ? (record?.kind ?? null) : (kind ?? null)

  useEffect(() => {
    if (!open) return
    setSaving(false)
    setTestOpen(false)
    form.resetFields()
    if (mode === 'edit' && record) {
      form.setFieldsValue({
        kind: record.kind,
        app_token: record.app_token,
        table_id: record.table_id,
        enabled: record.enabled,
        note: record.note ?? undefined,
      })
    } else {
      form.setFieldsValue({
        kind: fixedKind ?? undefined,
        app_token: fixedKind ? prefillToken : '',
        table_id: '',
        enabled: true,
        note: undefined,
      })
    }
  }, [open, mode, record, fixedKind, prefillToken, form])

  /** 抽屉内测试连接：用表单当前值预填测试 Modal */
  const handleTest = () => {
    setTestOpen(true)
  }

  const handleSubmit = async () => {
    if (!domain) return
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return // 校验不通过停在原地
    }
    const targetKind = fixedKind ?? values.kind
    if (!targetKind) {
      message.error('请选择表类型（kind）')
      return
    }
    Modal.confirm({
      title: '保存连接',
      content: '保存后立即清除缓存并重新订阅该域事件（无需重启），确认保存？',
      okText: '确认保存',
      cancelText: '取消',
      onOk: async () => {
        setSaving(true)
        try {
          const res = await updateBitableConnection(domain.key, targetKind, {
            app_token: values.app_token.trim(),
            table_id: values.table_id.trim(),
            enabled: values.enabled,
            note: values.note?.trim() || null,
          })
          if (res.code === 200 && res.data) {
            message.success('连接配置已保存，实时生效')
            onSaved()
            onClose()
          } else {
            message.error(res.message || '保存失败')
          }
        } catch (e) {
          message.error(e instanceof Error ? e.message : '保存失败')
        } finally {
          setSaving(false)
        }
      },
    })
  }

  const kindLabel = domain?.kinds.find((k) => k.kind === fixedKind)?.label

  return (
    <Drawer
      title={
        <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>
          {mode === 'edit' ? `编辑连接 · ${kindLabel ?? fixedKind}` : '新增连接'}
        </span>
      }
      width={520}
      open={open}
      onClose={onClose}
      destroyOnHidden
      closable={!saving}
      maskClosable={!saving}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Button icon={<LinkOutlined />} onClick={handleTest} disabled={saving}>
            测试连接
          </Button>
          <Space>
            <Button onClick={onClose} disabled={saving}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={() => void handleSubmit()}>
              保存
            </Button>
          </Space>
        </div>
      }
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        {/* kind：编辑 / 行「配置」→ 只读；页头「+新增」→ 下拉未配置 kind */}
        {fixedKind ? (
          <div style={{ marginBottom: 20 }}>
            <div style={fieldLabelStyle}>表类型（kind）</div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: UI.ink,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              {kindLabel ?? fixedKind}
              <span style={{ fontSize: 12, color: UI.steel, fontFamily: MONO_FONT, fontWeight: 400 }}>{fixedKind}</span>
            </div>
          </div>
        ) : (
          <Form.Item
            name="kind"
            label="表类型（kind）"
            rules={[{ required: true, message: '请选择要配置的表类型' }]}
            style={{ marginBottom: 20 }}
          >
            <Select
              placeholder={missingKinds.length > 0 ? '选择该域未配置的表类型' : '该域所有表类型均已配置'}
              options={missingKinds.map((k) => ({ value: k.kind, label: `${k.label}（${k.kind}）` }))}
              disabled={missingKinds.length === 0}
            />
          </Form.Item>
        )}

        <Form.Item
          name="app_token"
          label="app_token"
          rules={[{ required: true, whitespace: true, message: '请输入 app_token（复制分享链接中的 bascn… 前缀）' }]}
        >
          <Input placeholder="bascn…" style={{ fontFamily: MONO_FONT }} />
        </Form.Item>

        <Form.Item
          name="table_id"
          label="table_id"
          rules={[{ required: true, whitespace: true, message: '请输入 table_id（复制分享链接中的 tbl… 前缀）' }]}
        >
          <Input placeholder="tbl…" style={{ fontFamily: MONO_FONT }} />
        </Form.Item>

        <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ marginBottom: 20 }}>
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>

        <Form.Item name="note" label="备注（可选）" style={{ marginBottom: 8 }}>
          <Input.TextArea rows={3} placeholder="用途说明、数据源备注等" />
        </Form.Item>

        <div style={{ fontSize: 12, color: UI.muted }}>
          保存即生效：后端将清除该域缓存并自动重新订阅事件；若自动重订阅失败，可在域详情页头点击「手动重订阅」兜底。
        </div>
      </Form>

      <BitableTestConnectionModal
        open={testOpen}
        title={`测试连接 · ${kindLabel ?? fixedKind ?? '新增表'}`}
        initialAppToken={form.getFieldValue('app_token')}
        initialTableId={form.getFieldValue('table_id')}
        onClose={() => setTestOpen(false)}
      />
    </Drawer>
  )
}
