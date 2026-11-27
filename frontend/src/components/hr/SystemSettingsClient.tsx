'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Select, Alert, Spin, Checkbox, Popconfirm, Space, Divider, Modal } from 'antd'
import { SaveOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { logError } from '@/lib/hr'
import { fetchDataTables, clearDataTables, fetchTestData, clearTestData, getSystemSettings, updateSystemSettings } from '@/actions/hr'

/** 一键清空的输入确认词 */
const CLEAR_CONFIRM_WORD = '清空'

/** 系统配置 →「邮件配置」页签：SMTP 发信设置 + 授权码获取指南 */
export function SmtpSettingsCard() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getSystemSettings()
      .then(d => form.setFieldsValue(d.data || {}))
      .catch((err: any) => {
        logError('加载系统设置失败', { error: err?.message })
        message.error('加载系统设置失败，请检查后端服务是否正常运行')
      })
  }, [form])

  const handleSave = async () => {
    // 校验失败只走表单行内提示
    let values: Record<string, unknown>
    try {
      values = (await form.validateFields()) as Record<string, unknown>
    } catch {
      return
    }
    setLoading(true)
    try {
      const d = await updateSystemSettings(values)
      message.success(d.message || '已保存')
    } catch (err: any) { message.error(err.message || '保存失败') }
    finally { setLoading(false) }
  }

  return (
    <div className="flex gap-6 flex-col lg:flex-row">
      <Card className="flex-1 max-w-xl">
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
            <Input placeholder="smtp.exmail.qq.com" autoComplete="off" />
          </Form.Item>
          <Form.Item name="smtp_port" label="端口">
            <Input placeholder="587" autoComplete="off" />
          </Form.Item>
          <Form.Item name="smtp_from" label="发件邮箱地址" rules={[{ required: true, message: '请填写发件邮箱' }]}>
            <Input placeholder="hr@livzon.cn" autoComplete="off" />
          </Form.Item>
          <Form.Item name="smtp_from_name" label="发件人名称" initialValue="丽珠集团福州福兴医药有限公司">
            <Input placeholder="丽珠集团福州福兴医药有限公司" autoComplete="off" />
          </Form.Item>
          <Form.Item name="smtp_user" label="用户名">
            <Input placeholder="通常和发件邮箱地址相同" autoComplete="off" />
          </Form.Item>
          <Form.Item name="smtp_password" label="密码 / 授权码"
            tooltip="不是邮箱登录密码，需要在邮箱设置中单独生成"
          >
            <Input.Password placeholder="邮箱授权码，非登录密码" autoComplete="off" />
          </Form.Item>

          <Button type="primary" icon={<SaveOutlined />} loading={loading} onClick={handleSave}>
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
            title="重要提示"
            description="「密码」字段填授权码，不是邮箱登录密码。授权码通常是一串16位字母，每个邮箱单独生成。"
            style={{ marginTop: 12 }}
          />
        </div>
      </Card>
    </div>
  )
}

/** 系统配置 →「数据管理」页签：测试数据分类 + 各数据表（选择性清空 / 一键清空） */
export default function SystemSettingsClient() {
  const { message } = App.useApp()

  const [tables, setTables] = useState<any[]>([])
  const [tablesLoading, setTablesLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [testData, setTestData] = useState<{ total: number; tables: { table: string; label: string; count: number }[] }>({ total: 0, tables: [] })

  // 一键清空：不可恢复的物理删除，须输入确认词（Popconfirm 点两下就清空全部 HR 数据，误触代价过大）
  const [clearAllOpen, setClearAllOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [clearing, setClearing] = useState(false)
  const [clearingSelected, setClearingSelected] = useState(false)
  const [clearingTest, setClearingTest] = useState(false)

  const loadTables = () => {
    setTablesLoading(true)
    fetchDataTables()
      .then(d => setTables(d?.data || []))
      .catch((err: any) => { message.error('加载数据管理列表失败: ' + (err.message || '未知错误')) })
      .finally(() => setTablesLoading(false))
  }

  const loadTestData = () => {
    fetchTestData()
      .then(d => setTestData(d?.data || { total: 0, tables: [] }))
      .catch((err: any) => { message.error('加载测试数据分类失败: ' + (err.message || '未知错误')) })
  }

  useEffect(() => { loadTables(); loadTestData() }, [])
  const toggleSelect = (table: string) => setSelected(prev => prev.includes(table) ? prev.filter(t => t !== table) : [...prev, table])
  const handleClearSelected = async () => {
    if (!selected.length) { message.warning('请选择要清空的表'); return }
    setClearingSelected(true)
    try {
      const d = await clearDataTables(selected)
      message.success(d.message || '已清空')
      setSelected([])
      loadTables()
    } catch (err: any) { message.error(err.message || '操作失败') }
    finally { setClearingSelected(false) }
  }
  const handleClearAll = async () => {
    setClearing(true)
    try {
      const d = await clearDataTables(tables.map(t => t.table))
      message.success(d.message || '已清空')
      setClearAllOpen(false)
      setConfirmText('')
      loadTables()
    } catch (err: any) { message.error(err.message || '操作失败') }
    finally { setClearing(false) }
  }
  const handleClearTestData = async () => {
    setClearingTest(true)
    try {
      const d = await clearTestData()
      message.success(d.message || '已清空测试数据')
      loadTestData()
      loadTables()
    } catch (err: any) { message.error(err.message || '操作失败') }
    finally { setClearingTest(false) }
  }

  // 一键清空影响面：表数与总行数在确认弹窗里写明
  const totalRows = tables.reduce((s, t) => s + (Number(t.count) || 0), 0)

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--color-charcoal)]">测试数据</h2>
            <p className="text-sm text-gray-400 mt-1">测试过程中实际产生的数据收纳于此，一键清理（识别规则在后端登记，可按需扩展）</p>
          </div>
          <Space>
            <Button aria-label="刷新测试数据" title="刷新" size="small" icon={<ReloadOutlined />} onClick={loadTestData} />
            <Popconfirm title="确认清空全部测试数据？" onConfirm={handleClearTestData}>
              <Button danger type="primary" icon={<DeleteOutlined />} loading={clearingTest} disabled={!testData.total}>
                清空测试数据（{testData.total} 条）
              </Button>
            </Popconfirm>
          </Space>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 min-h-[40px]">
          {testData.tables.map(t => (
            <div key={t.table}
              className="rounded-lg border border-amber-200 bg-amber-50 p-3"
            >
              <div className="text-sm font-medium text-gray-700">{t.label}</div>
              <div className="mt-1 text-2xl font-bold text-gray-900">{t.count}</div>
              <div className="text-xs text-gray-400">条测试数据</div>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--color-charcoal)]">数据管理</h2>
            <p className="text-sm text-gray-400 mt-1">管理 HR 模块所有数据表，支持选择性或一键清空（岗位管理除外）</p>
          </div>
          <Space>
            <Button size="small" onClick={() => setSelected(tables.map(t => t.table))}>全选</Button>
            <Button size="small" onClick={() => setSelected([])}>取消全选</Button>
            <Button aria-label="刷新数据表" title="刷新" size="small" icon={<ReloadOutlined />} onClick={loadTables} />
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
          <Popconfirm
            title={`确认删除选中的 ${selected.length} 张表？不可恢复！`}
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={handleClearSelected}
          >
            <Button danger icon={<DeleteOutlined />} loading={clearingSelected} disabled={!selected.length}>
              删除选中 ({selected.length})
            </Button>
          </Popconfirm>
          <Button danger type="primary" onClick={() => { setConfirmText(''); setClearAllOpen(true) }}>
            一键清空全部
          </Button>
        </div>
      </Card>

      <Modal
        title="一键清空全部 HR 数据表"
        open={clearAllOpen}
        onOk={handleClearAll}
        okText="确认清空"
        okButtonProps={{ danger: true, disabled: confirmText !== CLEAR_CONFIRM_WORD }}
        confirmLoading={clearing}
        onCancel={() => { setClearAllOpen(false); setConfirmText('') }}
        destroyOnHidden
      >
        <Alert
          type="error" showIcon className="mb-4"
          title="此操作完全不可恢复"
          description={`将清空 ${tables.length} 张表的全部数据（共 ${totalRows} 条记录），生产环境同样生效。`}
        />
        <div className="text-sm mb-2">
          请输入 <b>{CLEAR_CONFIRM_WORD}</b> 以确认：
        </div>
        <Input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={`请输入「${CLEAR_CONFIRM_WORD}」`}
          autoComplete="off"
          onPressEnter={() => { if (confirmText === CLEAR_CONFIRM_WORD && !clearing) void handleClearAll() }}
        />
      </Modal>
    </div>
  )
}
