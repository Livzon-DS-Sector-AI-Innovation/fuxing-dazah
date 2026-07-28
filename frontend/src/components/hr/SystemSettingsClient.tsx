'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Select, Alert, Spin, Table, Checkbox, Popconfirm, Space, Divider } from 'antd'
import { SaveOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { logError } from '@/lib/hr'

/** 安全的 JSON fetch：检查 HTTP 状态码 + 容错非 JSON 响应，返回解析后的 JSON 对象 */
async function safeJsonFetch(url: string, init?: RequestInit): Promise<any> {
  let r: Response
  try { r = await fetch(url, init) }
  catch { throw new Error('无法连接后端服务，请确认后端已启动') }
  const text = await r.text()
  if (!r.ok) {
    let errMsg = `HTTP ${r.status}`
    try {
      const body = JSON.parse(text)
      if (body.message) errMsg = body.message
      if (body.detail) errMsg += `: ${body.detail}`
    } catch { errMsg += `: ${text.slice(0, 200)}` }
    throw new Error(errMsg)
  }
  try { return JSON.parse(text) }
  catch { throw new Error(`服务器返回非JSON响应: ${text.slice(0, 200)}`) }
}

export default function SystemSettingsClient() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const [tables, setTables] = useState<any[]>([])
  const [tablesLoading, setTablesLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])

  const loadTables = () => {
    setTablesLoading(true)
    safeJsonFetch('/api/v1/hr/data-management/tables', { credentials: 'include' })
      .then(d => setTables(d?.data || []))
      .catch((err: any) => { message.error('加载数据管理列表失败: ' + (err.message || '未知错误')) })
      .finally(() => setTablesLoading(false))
  }

  useEffect(() => { loadTables() }, [])
  const toggleSelect = (table: string) => setSelected(prev => prev.includes(table) ? prev.filter(t => t !== table) : [...prev, table])
  const handleClearSelected = () => {
    if (!selected.length) return message.warning('请选择要清空的表')
    safeJsonFetch('/api/v1/hr/data-management/clear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify(selected),
    }).then(d => {
      message.success(d.message || '已清空')
      setSelected([])
      loadTables()
    }).catch((err: any) => { message.error(err.message || '操作失败') })
  }
  const handleClearAll = () => {
    safeJsonFetch('/api/v1/hr/data-management/clear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify(tables.map(t => t.table)),
    }).then(d => {
      message.success(d.message || '已清空')
      loadTables()
    }).catch((err: any) => { message.error(err.message || '操作失败') })
  }

  useEffect(() => {
    safeJsonFetch('/api/v1/hr/system-settings', { credentials: 'include' })
      .then(d => form.setFieldsValue(d.data || {}))
      .catch((err: any) => {
        logError('加载系统设置失败', { error: err?.message })
        message.error('加载系统设置失败，请检查后端服务是否正常运行')
      })
  }, [form])

  const handleSave = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      const d = await safeJsonFetch('/api/v1/hr/system-settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values), credentials: 'include',
      })
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

      <div className="flex gap-6 flex-col lg:flex-row">
        <Card className="flex-1 max-w-xl" title="SMTP 邮件配置">
          <Form form={form} layout="vertical">
            <Form.Item label="快捷选择">
              <Select placeholder="选择常见邮箱自动填入服务器和端口" allowClear
                onChange={(val) => {
                  if (!val) return
                  const [host, port] = val.split('|')
                  form.setFieldsValue({ smtp_host: host, smtp_port: Number(port) })
                }}
                options={[
                  { label: '腾讯企业邮箱', value: 'smtp.exmail.qq.com|587' },
                  { label: 'QQ 邮箱', value: 'smtp.qq.com|587' },
                  { label: '网易 163 邮箱', value: 'smtp.163.com|465' },
                  { label: '网易 126 邮箱', value: 'smtp.126.com|465' },
                  { label: '阿里企业邮箱', value: 'smtp.qiye.aliyun.com|465' },
                  { label: 'Gmail', value: 'smtp.gmail.com|587' },
                  { label: 'Outlook / Hotmail', value: 'smtp-mail.outlook.com|587' },
                ]}
              />
            </Form.Item>
            <Form.Item name="smtp_host" label="SMTP 服务器" rules={[{ required: true, message: '请填写SMTP服务器地址' }]}>
              <Input placeholder="smtp.exmail.qq.com" />
            </Form.Item>
            <Form.Item name="smtp_port" label="端口">
              <Input placeholder="587" />
            </Form.Item>
            <Form.Item name="smtp_from" label="发件邮箱地址" rules={[{ required: true, message: '请填写发件邮箱' }]}>
              <Input placeholder="hr@livzon.cn" />
            </Form.Item>
            <Form.Item name="smtp_from_name" label="发件人名称" initialValue="丽珠集团福州福兴医药有限公司">
              <Input placeholder="丽珠集团福州福兴医药有限公司" />
            </Form.Item>
            <Form.Item name="smtp_user" label="用户名">
              <Input placeholder="通常和发件邮箱地址相同" />
            </Form.Item>
            <Form.Item name="smtp_password" label="密码 / 授权码"
              tooltip="不是邮箱登录密码，需要在邮箱设置中单独生成"
            >
              <Input.Password placeholder="邮箱授权码，非登录密码" />
            </Form.Item>

            <Button type="primary" size="large" icon={<SaveOutlined />} loading={loading} onClick={handleSave} block>
              保存设置
            </Button>
          </Form>
        </Card>

        <Card className="flex-1 max-w-md" title="授权码获取指南">
          <div className="text-sm space-y-4 text-gray-600">
            <div>
              <p className="font-semibold text-gray-700">腾讯企业邮箱 / QQ 邮箱</p>
              <p>登录网页版 → 设置 → 账户 → 开启 SMTP 服务 → 生成授权码</p>
            </div>
            <Divider style={{ margin: '8px 0' }} />
            <div>
              <p className="font-semibold text-gray-700">网易 163 / 126 邮箱</p>
              <p>登录网页版 → 设置 → POP3/SMTP/IMAP → 开启 SMTP → 新增授权码</p>
            </div>
            <Divider style={{ margin: '8px 0' }} />
            <div>
              <p className="font-semibold text-gray-700">阿里企业邮箱</p>
              <p>管理员在后台开启客户端密码 → 生成授权码</p>
            </div>
            <Divider style={{ margin: '8px 0' }} />
            <div>
              <p className="font-semibold text-gray-700">Gmail</p>
              <p>Google 账户 → 安全性 → 应用专用密码 → 生成</p>
            </div>
            <Divider style={{ margin: '8px 0' }} />
            <Alert type="warning" showIcon
              message="重要提示"
              description="「密码」字段填授权码，不是邮箱登录密码。授权码通常是一串16位字母，每个邮箱单独生成。"
              style={{ marginTop: 12 }}
            />
          </div>
        </Card>
      </div>

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
