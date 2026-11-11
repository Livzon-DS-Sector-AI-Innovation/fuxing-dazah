'use client'

import { useCallback, useState } from 'react'
import { App, Alert, Button, Collapse, Form, Input, Space, Switch, Tag, Typography } from 'antd'
import { CloudSyncOutlined, LinkOutlined, ReloadOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons'
import {
  fetchEmployeeSyncConfig,
  saveEmployeeSyncConfig,
  triggerEmployeeSync,
} from '@/actions/hr'
import { usePermission } from '@/hooks/usePermission'
import type { EmployeeSyncConfig } from '@/types/hr'

const { Text, Paragraph } = Typography

function formatSyncTime(iso: string | null): string {
  if (!iso) return '从未同步'
  return iso.replace('T', ' ')
}

/** 从 unknown 错误中提取可展示文案 */
function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

interface EmployeeSyncSettingsProps {
  /** 服务端直取的初始配置（避免客户端 effect 拉取） */
  initialConfig: EmployeeSyncConfig | null
}

/**
 * 员工档案页顶部的「多维表格同步」折叠面板（默认收起）。
 * 仅对拥有 hr:settings:manage 权限的用户渲染；保存/同步由后端同一权限把关。
 */
export default function EmployeeSyncSettings({ initialConfig }: EmployeeSyncSettingsProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [cfg, setCfg] = useState<EmployeeSyncConfig | null>(initialConfig)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const { hasPermission } = usePermission()

  // 手动刷新（按钮触发）；初次数据由服务端 props 提供
  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const d = await fetchEmployeeSyncConfig()
      setCfg(d.data)
      form.setFieldsValue({
        enabled: d.data?.enabled ?? false,
        app_token: d.data?.app_token ?? '',
        source_table_id: d.data?.source_table_id ?? '',
      })
    } catch (err) {
      message.error(errMsg(err, '加载同步配置失败'))
    } finally {
      setLoading(false)
    }
  }, [form, message])

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const d = await saveEmployeeSyncConfig(values)
      setCfg(d.data)
      message.success('同步配置已保存')
      if (!d.data?.column_report?.has_employee_number) {
        message.warning('源表中未识别到「工号」列，同步将无法写入，请检查列名', 8)
      }
    } catch (err) { message.error(errMsg(err, '保存失败')) }
    finally { setSaving(false) }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const d = await triggerEmployeeSync()
      const s = d.data || {}
      message.success(
        `同步完成：新增 ${s.created ?? 0}，更新 ${s.updated ?? 0}，删除 ${s.deleted ?? 0}，共 ${s.total ?? 0} 条`,
        6,
      )
      loadConfig()
    } catch (err) { message.error(errMsg(err, '同步失败')) }
    finally { setSyncing(false) }
  }

  if (!hasPermission('hr:settings:manage')) return null

  const bitableUrl = cfg?.app_token
    ? `https://feishu.cn/base/${cfg.app_token}${cfg.source_table_id ? `?table=${cfg.source_table_id}` : ''}`
    : null

  const header = (
    <Space size="middle" wrap>
      <Space>
        <CloudSyncOutlined />
        <span className="font-medium">多维表格同步</span>
      </Space>
      {cfg?.enabled
        ? <Tag color="success">已启用</Tag>
        : <Tag>未启用</Tag>}
      <Text type="secondary" className="text-sm">上次同步：{formatSyncTime(cfg?.last_sync_at ?? null)}</Text>
    </Space>
  )

  return (
    <Collapse
      className="employee-sync-collapse"
      items={[{
        key: 'sync',
        label: header,
        children: (
          <div className="space-y-4">
            <div className="flex justify-end">
              <Button size="small" icon={<ReloadOutlined />} onClick={() => { void loadConfig() }} loading={loading}>
                刷新状态
              </Button>
            </div>

            <Paragraph type="secondary" className="!mb-0 text-sm text-[var(--color-steel)]">
              绑定飞书多维表格后，员工档案以该表为唯一数据源单向同步（每天凌晨 02:00 自动对账，可随时点「立即同步」），
              本页转为只读展示；培训管理所用的脱敏名单在系统内查看（培训管理 → 培训人员名单）。
            </Paragraph>

            <Form
              form={form}
              layout="vertical"
              className="max-w-xl"
              initialValues={{
                enabled: initialConfig?.enabled ?? false,
                app_token: initialConfig?.app_token ?? '',
                source_table_id: initialConfig?.source_table_id ?? '',
              }}
            >
              <Form.Item
                name="app_token"
                label="多维表格 app_token"
                tooltip="支持直接粘贴飞书多维表格完整链接，自动提取"
                rules={[{ required: true, message: '请填写 app_token' }]}
              >
                <Input placeholder="粘贴链接或 app_token，如 Bic6bL8HH..." autoComplete="off" allowClear />
              </Form.Item>
              <Form.Item
                name="source_table_id"
                label="员工档案源数据表 table_id"
                tooltip="支持直接粘贴表格完整链接（自动提取 table= 参数）或 tbl 开头的 table_id"
                rules={[{ required: true, message: '请填写源数据表 table_id' }]}
              >
                <Input placeholder="粘贴链接或 table_id，如 tbl18mDH..." autoComplete="off" allowClear />
              </Form.Item>
              <Form.Item
                name="enabled"
                label="启用同步"
                valuePropName="checked"
                tooltip="启用后系统内员工档案不再支持新建/编辑/Excel 上传，请在飞书表中维护"
              >
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>

              <Space className="mb-2" wrap>
                <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
                  保存并校验
                </Button>
                <Button
                  icon={<SyncOutlined />}
                  loading={syncing}
                  disabled={!cfg?.is_ready}
                  onClick={handleSync}
                >
                  立即同步
                </Button>
                {bitableUrl && (
                  <Button icon={<LinkOutlined />} href={bitableUrl} target="_blank">
                    在飞书打开
                  </Button>
                )}
              </Space>
            </Form>

            {cfg && (
              <div className="pt-4 border-t border-[var(--color-hairline)] space-y-3">
                <Text type="secondary" className="text-sm">源表：{cfg.source_table_name || '-'}</Text>

                {cfg.last_stats?.errors && cfg.last_stats.errors.length > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    message={`上次同步有 ${cfg.last_stats.errors.length} 条记录出错`}
                    description={
                      <ul className="max-h-32 overflow-auto pl-4 m-0">
                        {cfg.last_stats.errors.slice(0, 20).map((e, i) => <li key={i}>{e}</li>)}
                      </ul>
                    }
                  />
                )}

                {cfg.column_report && cfg.column_report.mapped_count > 0 && (
                  <div className="text-sm">
                    <Text type="secondary">列匹配（{cfg.column_report.mapped_count} 列已识别）：</Text>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {cfg.column_report.mapped.map(c => <Tag key={c} color="blue">{c}</Tag>)}
                    </div>
                    {cfg.column_report.ignored.length > 0 && (
                      <div className="mt-2">
                        <Text type="secondary" className="text-xs">忽略的列（与系统字段无映射）：</Text>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {cfg.column_report.ignored.map(c => <Tag key={c}>{c}</Tag>)}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <Alert
                  type="info"
                  showIcon
                  message="脱敏名单在系统内"
                  description="培训管理 → 培训人员名单（脱敏版，不含身份证/学校/专业/联系方式等个人信息）。台账、Word 打印等系统功能读取本地全量档案，不受影响。"
                />
              </div>
            )}
          </div>
        ),
      }]}
    />
  )
}
