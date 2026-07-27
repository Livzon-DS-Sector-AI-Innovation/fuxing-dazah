'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Alert, Spin, Table, Checkbox, Popconfirm, Space } from 'antd'
import { SaveOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { logError } from '@/lib/hr'

export default function SystemSettingsClient() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const [tables, setTables] = useState<any[]>([])
  const [tablesLoading, setTablesLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])

  const loadTables = () => {
    setTablesLoading(true)
    fetch('/api/v1/hr/data-management/tables', { credentials: 'include' })
      .then(r => r.json()).then(d => setTables(d?.data || []))
      .catch(() => {})
      .finally(() => setTablesLoading(false))
  }

  useEffect(() => { loadTables() }, [])
  const toggleSelect = (table: string) => setSelected(prev => prev.includes(table) ? prev.filter(t => t !== table) : [...prev, table])
  const handleClearSelected = () => {
    if (!selected.length) return message.warning('请选择要清空的表')
    fetch('/api/v1/hr/data-management/clear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify(selected),
    }).then(r => r.json()).then(d => {
      message.success(d.message)
      setSelected([])
      loadTables()
    }).catch((err: any) => { message.error(err.message || '操作失败') })
  }
  const handleClearAll = () => {
    fetch('/api/v1/hr/data-management/clear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify(tables.map(t => t.table)),
    }).then(r => r.json()).then(d => {
      message.success(d.message)
      loadTables()
    }).catch((err: any) => { message.error(err.message || '操作失败') })
  }

  useEffect(() => {
    fetch(`/api/v1/hr/system-settings`, { credentials: 'include' })
      .then(r => r.json()).then(d => form.setFieldsValue(d.data || {}))
      .catch((err: any) => { logError('加载系统设置失败', { error: err?.message }) })
  }, [form])

  const handleSave = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      const r = await fetch(`/api/v1/hr/system-settings`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values), credentials: 'include',
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.message || '保存失败')
      message.success(d.message || '已保存')
    } catch (err: any) { message.error(err.message || '保存失败') }
    finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">HR 系统设置</h1>
        <p className="text-[14px] text-[var(--color-steel)]">系统基础配置</p>
      </div>

      <Alert type="info" showIcon className="max-w-xl"
        message="邮件发送方式"
        description="通过 SMTP 直发邮件。填写邮箱服务器信息后保存即可，无需额外工具。"
      />

      <Card className="max-w-xl">
        <Form form={form} layout="vertical">
          <Form.Item name="smtp_host" label="SMTP 服务器" rules={[{ required: true, message: '请填写SMTP服务器地址' }]}>
            <Input placeholder="smtp.livzon.cn" />
          </Form.Item>
          <Form.Item name="smtp_port" label="端口" initialValue={587}>
            <Input placeholder="587" />
          </Form.Item>
          <Form.Item name="smtp_user" label="用户名">
            <Input placeholder="发件邮箱账号" />
          </Form.Item>
          <Form.Item name="smtp_password" label="密码">
            <Input.Password placeholder="邮箱密码或授权码" />
          </Form.Item>
          <Form.Item name="smtp_from" label="发件邮箱地址" rules={[{ required: true, message: '请填写发件邮箱' }]}>
            <Input placeholder="hr@livzon.cn" />
          </Form.Item>
          <Form.Item name="smtp_from_name" label="发件人名称" initialValue="丽珠集团福州福兴医药有限公司">
            <Input placeholder="丽珠集团福州福兴医药有限公司" />
          </Form.Item>

          <Button type="primary" size="large" icon={<SaveOutlined />} loading={loading} onClick={handleSave} block>
            保存设置
          </Button>
        </Form>
      </Card>

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

        <Spin spinning={tablesLoading}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 min-h-[80px]">
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
        </Spin>

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
