'use client'

// 测试连接 Modal：双入口（卡片行快捷测试=预填已存值 / 编辑抽屉内测试=预填表单当前值）
// 只读操作：不写 Bitable、不写审计、不触发重订阅；结果仅本地提示（design.md §2.5 / §5.4）

import { useEffect, useState } from 'react'
import { Alert, App, Button, Form, Input, Modal, Space } from 'antd'

import { testBitableConnection } from '@/actions/safety'
import { MONO_FONT, UI } from './bitableConfigConstants'

interface BitableTestConnectionModalProps {
  open: boolean
  title?: string
  initialAppToken?: string
  initialTableId?: string
  onClose: () => void
}

interface TestFormValues {
  app_token: string
  table_id: string
}

/** 失败排查建议（design.md §5.4 固定文案） */
const TROUBLESHOOTING =
  '1. 确认 app_token / table_id 已从多维表格分享链接复制完整；' +
  '2. 确认应用已在飞书开放平台申请 Bitable 权限并开启设置；' +
  '3. 若近期切换过数据源，先保存连接再测试。'

export default function BitableTestConnectionModal({
  open,
  title,
  initialAppToken,
  initialTableId,
  onClose,
}: BitableTestConnectionModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<TestFormValues>()
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  // 打开时重置结果并预填初始值（已存值 / 表单当前值由调用方传入）
  useEffect(() => {
    if (!open) return
    setResult(null)
    form.setFieldsValue({
      app_token: initialAppToken ?? '',
      table_id: initialTableId ?? '',
    })
  }, [open, initialAppToken, initialTableId, form])

  const handleTest = async () => {
    let values: TestFormValues
    try {
      values = await form.validateFields()
    } catch {
      return // 必填未过，antd 已标红
    }
    setTesting(true)
    setResult(null)
    try {
      const res = await testBitableConnection(values.app_token.trim(), values.table_id.trim())
      if (res.code === 200 && res.data?.ok) {
        const meta = res.data.meta as { table_name?: string; field_count?: number } | null | undefined
        if (meta?.table_name != null && meta.field_count != null) {
          setResult({
            ok: true,
            text: `连接成功：已拉取「${meta.table_name}」表 / ${meta.field_count} 个字段`,
          })
        } else {
          setResult({ ok: true, text: '连接成功：app_token / table_id 校验通过' })
        }
      } else {
        setResult({ ok: false, text: res.message || '连接失败' })
      }
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : '连接失败' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      title={<span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>{title ?? '测试连接'}</span>}
      open={open}
      onCancel={onClose}
      footer={null}
      width={520}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="app_token"
          label="app_token"
          rules={[{ required: true, whitespace: true, message: '请输入 app_token' }]}
          style={{ marginBottom: 12 }}
        >
          <Input placeholder="bascn…" style={{ fontFamily: MONO_FONT }} />
        </Form.Item>
        <Form.Item
          name="table_id"
          label="table_id"
          rules={[{ required: true, whitespace: true, message: '请输入 table_id' }]}
          style={{ marginBottom: 12 }}
        >
          <Input placeholder="tbl…" style={{ fontFamily: MONO_FONT }} />
        </Form.Item>
      </Form>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <span style={{ fontSize: 12, color: UI.muted }}>测试为只读校验，不写入配置、不触发订阅</span>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={testing} onClick={() => void handleTest()}>
            {testing ? '连接测试中…' : '开始测试'}
          </Button>
        </Space>
      </div>

      {result &&
        (result.ok ? (
          <Alert
            type="success"
            showIcon
            message={<span style={{ fontSize: 13 }}>{result.text}</span>}
            description={
              <span style={{ fontSize: 12, color: UI.slate }}>
                测试通过不代表已保存，请返回保存连接后生效
              </span>
            }
          />
        ) : (
          <Alert
            type="error"
            showIcon
            message={<span style={{ fontSize: 13 }}>{`连接失败：${result.text}`}</span>}
            description={<span style={{ fontSize: 13, color: UI.muted }}>{TROUBLESHOOTING}</span>}
          />
        ))}
    </Modal>
  )
}
