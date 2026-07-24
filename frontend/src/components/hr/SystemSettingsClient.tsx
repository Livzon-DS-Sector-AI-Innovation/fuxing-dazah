'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Alert, Modal, Spin, Table, Checkbox, Popconfirm, Space } from 'antd'
import { SaveOutlined, CheckCircleOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { API_BASE } from '@/lib/hr'
import { logError } from '@/lib/hr'

export default function SystemSettingsClient() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  // 授权引导弹窗
  const [authModal, setAuthModal] = useState(false)
  const [authUrl, setAuthUrl] = useState('')
  const [deviceCode, setDeviceCode] = useState('')
  const [authLoading, setAuthLoading] = useState(false)
  const [tables, setTables] = useState<any[]>([])
  const [selected, setSelected] = useState<string[]>([])

  useEffect(() => { loadTables() }, [])

  const loadTables = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/v1/hr/data-management/tables`, { credentials: 'include' })
      const d = await r.json()
      setTables(d.data || [])
    } catch { /* ignore */ }
  }
  const toggleSelect = (table: string) => setSelected(prev => prev.includes(table) ? prev.filter(t => t !== table) : [...prev, table])
  const handleClearSelected = async () => {
    if (!selected.length) return message.warning('请选择要清空的表')
    try {
      const r = await fetch(`${API_BASE}/api/v1/hr/data-management/clear`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify(selected),
      })
      const d = await r.json()
      message.success(d.message)
      setSelected([])
      loadTables()
    } catch (err: any) { message.error(err.message || '操作失败') }
  }
  const handleClearAll = async () => {
    const all = tables.map(t => t.table)
    try {
      const r = await fetch(`${API_BASE}/api/v1/hr/data-management/clear`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify(all),
      })
      const d = await r.json()
      message.success(d.message)
      loadTables()
    } catch (err: any) { message.error(err.message || '操作失败') }
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/system-settings`, { credentials: 'include' })
      .then(r => r.json()).then(d => form.setFieldsValue(d.data || {}))
      .catch((err: any) => { logError('加载系统设置失败', { error: err?.message }) })
  }, [form])

  const handleSave = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      const r = await fetch(`${API_BASE}/api/v1/hr/system-settings`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values), credentials: 'include',
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.message || '保存失败')
      message.success(d.message || '已保存')
      // 邮箱变更 → 弹授权引导
      if (d.data?.auth_url) {
        setAuthUrl(d.data.auth_url)
        setDeviceCode(d.data.device_code || '')
        setAuthModal(true)
      }
    } catch (err: any) { message.error(err.message || '保存失败') }
    finally { setLoading(false) }
  }

  const handleCompleteAuth = async () => {
    if (!deviceCode) return
    setAuthLoading(true)
    try {
      const fd = new FormData(); fd.append('device_code', deviceCode)
      const r = await fetch(`${API_BASE}/api/v1/hr/system-settings/complete-auth`, {
        method: 'POST', body: fd, credentials: 'include',
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.message || '授权失败')
      message.success('授权完成，邮件发送已就绪')
      setAuthModal(false)
    } catch (err: any) { message.error(err.message || '授权失败') }
    finally { setAuthLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">HR 系统设置</h1>
        <p className="text-[14px] text-[var(--color-steel)]">系统基础配置</p>
      </div>

      <Alert type="success" showIcon className="max-w-xl"
        message="邮件发送方式"
        description="通过飞书邮箱发送 Offer，换人时在此页面修改邮箱并扫码授权即可，无需进后台。"
      />

      <Card className="max-w-xl">
        <Form form={form} layout="vertical">
          <Form.Item name="mail_sender" label="发件邮箱"
            tooltip="Offer 邮件的发件人地址"
            extra="填写飞书邮箱地址。修改后保存会自动弹出授权引导。"
          >
            <Input placeholder="chenshengting@livzon.cn" />
          </Form.Item>

          <Button type="primary" size="large" icon={<SaveOutlined />} loading={loading} onClick={handleSave} block>
            保存设置
          </Button>
        </Form>
      </Card>

      {/* 授权引导弹窗 */}
      <Modal
        title="邮箱授权"
        open={authModal}
        onCancel={() => setAuthModal(false)}
        footer={[
          <Button key="cancel" onClick={() => setAuthModal(false)}>稍后处理</Button>,
          <Button key="done" type="primary" icon={<CheckCircleOutlined />} loading={authLoading} onClick={handleCompleteAuth}>
            我已扫码授权
          </Button>,
        ]}
      >
        <div className="space-y-4">
          <p>发件邮箱已变更。请用飞书扫描下方二维码，或在浏览器打开链接完成授权：</p>
          <div className="text-center">
            {authUrl ? (
              <Spin spinning={!authUrl}>
                <Button type="link" href={authUrl} target="_blank" size="large">
                  点击打开授权页面
                </Button>
              </Spin>
            ) : (
              <Spin />
            )}
          </div>
          <p className="text-gray-400 text-sm">
            打开链接后点击「确认授权」，然后回到本页面点击「我已扫码授权」完成。
          </p>
        </div>
      </Modal>

      {/* ─── 数据管理 ─── */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--color-charcoal)]">数据管理</h2>
            <p className="text-sm text-gray-400 mt-1">管理 HR 模块所有数据表，支持选择性或一键清空（岗位管理除外）</p>
          </div>
          <Space>
            <Button size="small" onClick={() => setSelected(tables.map(t => t.table))}>全选</Button>
            <Button size="small" onClick={() => setSelected([])}>取消全选</Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={loadTables} />
          </Space>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          {tables.map(t => (
            <div key={t.table}
              onClick={() => toggleSelect(t.table)}
              className={`cursor-pointer rounded-lg border p-3 transition-all hover:shadow-sm ${
                selected.includes(t.table)
                  ? 'border-red-400 bg-red-50 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-blue-300'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">{t.label}</span>
                <Checkbox checked={selected.includes(t.table)} />
              </div>
              <div className="mt-1 text-2xl font-bold text-gray-900">{t.count}</div>
              <div className="text-xs text-gray-400">条记录</div>
            </div>
          ))}
        </div>

        <div className="flex gap-2 pt-2 border-t border-gray-100">
          <Popconfirm title={`确认删除选中的 ${selected.length} 张表？不可恢复！`} onConfirm={handleClearSelected}>
            <Button danger icon={<DeleteOutlined />} disabled={!selected.length}>
              删除选中 ({selected.length})
            </Button>
          </Popconfirm>
          <Popconfirm title="⚠️ 确认清空全部 HR 数据表？此操作完全不可恢复！" onConfirm={handleClearAll}>
            <Button danger type="primary">一键清空全部</Button>
          </Popconfirm>
        </div>
      </Card>
    </div>
  )
}
