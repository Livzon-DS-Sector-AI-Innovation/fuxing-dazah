'use client'

import { useCallback, useEffect, useState } from 'react'
import { usePermission } from '@/hooks/usePermission'
import { Card, Table, Button, Space, App, Modal, Form, Input, Popconfirm, Tag, Typography, Upload, Radio } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, ThunderboltOutlined, InboxOutlined } from '@ant-design/icons'
import type { LcTemplateConfig } from '@/types/quality'
import {
  fetchLcTemplateConfigs,
  createLcTemplateConfig,
  updateLcTemplateConfig,
  deleteLcTemplateConfig,
  testCalc,
  autoDetectTemplate,
  autoCreateTemplate,
} from '@/actions/quality'
import { CalcForm } from '@/components/quality'

const { Text } = Typography

/** 液相计算表模板配置维护：表号（EX-xx-xxxx-vvv）取值配置 JSON。 */
export default function LcTemplateConfigs() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:standard:manage')
  const [items, setItems] = useState<LcTemplateConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<LcTemplateConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  // 测试计算：选表号填数值跑引擎，不落库
  const [testOpen, setTestOpen] = useState(false)
  const [testCfg, setTestCfg] = useState<LcTemplateConfig | null>(null)
  const [testSection, setTestSection] = useState(0)
  const [testInputs, setTestInputs] = useState<Record<string, number | undefined>>({})
  const [testResult, setTestResult] = useState<{ items: { label: string; std_name: string; value: number | null; nd?: boolean; detail?: string }[] } | null>(null)
  // 傻瓜式维护：上传文件自动识别同版式
  const [autoOpen, setAutoOpen] = useState(false)
  const [autoDetecting, setAutoDetecting] = useState(false)
  const [autoPassword, setAutoPassword] = useState('zlkz6941')
  const [autoDetect, setAutoDetect] = useState<{ table_no: string; candidates: { template_table_no: string; product_name: string; description: string; component_count: number; value_count: number; blank?: boolean; name_shift: number; value_shift: number; step: number | null; samples: { name: string; value: number | null }[] }[] } | null>(null)
  const [autoPick, setAutoPick] = useState<string | null>(null)
  const [autoCreating, setAutoCreating] = useState(false)

  const onAutoUpload = async (file: File) => {
    setAutoDetecting(true)
    setAutoDetect(null)
    setAutoPick(null)
    try {
      const res = await autoDetectTemplate(file, autoPassword || undefined)
      setAutoDetect(res.data)
      if (res.data.candidates.length) setAutoPick(res.data.candidates[0].template_table_no)
      if (!res.data.candidates.length) message.warning('未找到同版式模板（全新版式请联系管理员配置）')
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '自动识别失败')
    } finally {
      setAutoDetecting(false)
    }
    return false
  }

  const onAutoCreate = async () => {
    if (!autoDetect?.table_no || !autoPick) return
    setAutoCreating(true)
    try {
      await autoCreateTemplate(autoDetect.table_no, autoPick)
      message.success(`配置 ${autoDetect.table_no} 已生成，可用「测试计算」验证后启用`)
      setAutoOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '生成配置失败')
    } finally {
      setAutoCreating(false)
    }
  }

  const openTest = (r: LcTemplateConfig) => {
    setTestCfg(r)
    setTestSection(0)
    setTestInputs({})
    setTestResult(null)
    setTestOpen(true)
  }

  const runTest = async () => {
    if (!testCfg) return
    try {
      const res = await testCalc(testCfg.table_no, testSection, testInputs)
      setTestResult(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '测试计算失败')
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchLcTemplateConfigs()
      setItems(res.data || [])
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ config: '{}' })
    setEditOpen(true)
  }

  const openEdit = (cfg: LcTemplateConfig) => {
    setEditing(cfg)
    form.setFieldsValue({
      table_no: cfg.table_no,
      product_name: cfg.product_name,
      sop_no: cfg.sop_no ?? '',
      description: cfg.description ?? '',
      config: JSON.stringify(cfg.config, null, 2),
    })
    setEditOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    let config: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(values.config || '{}')
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        message.error('配置 JSON 必须是对象（如 {"batch_label": "批号", "blocks": []}）')
        return
      }
      config = parsed as Record<string, unknown>
    } catch {
      message.error('配置 JSON 格式错误')
      return
    }
    setSaving(true)
    try {
      if (editing) {
        await updateLcTemplateConfig(editing.id, {
          product_name: values.product_name,
          sop_no: values.sop_no || null,
          description: values.description || null,
          config,
        })
        message.success('配置已更新')
      } else {
        await createLcTemplateConfig({
          table_no: values.table_no.trim(),
          product_name: values.product_name,
          sop_no: values.sop_no || undefined,
          description: values.description || undefined,
          config,
        })
        message.success('配置已创建')
      }
      setEditOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteLcTemplateConfig(id)
      message.success('已删除')
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  const columns = [
    { title: '表号', dataIndex: 'table_no', key: 'table_no', width: 150 },
    { title: '产品', dataIndex: 'product_name', key: 'product_name', width: 150 },
    {
      title: 'SOP', dataIndex: 'sop_no', key: 'sop_no', width: 150,
      render: (v: string | null) => v ? <Tag color="green">{v}</Tag> : '-',
    },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '操作', key: 'actions', width: 230,
      render: (_: unknown, r: LcTemplateConfig) => (
        <Space size={4}>
          {canManage && (
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          )}
          {(r.config.calc || r.config.calc_sections) && (
          <Button size="small" icon={<ExperimentOutlined />} onClick={() => openTest(r)}>测试计算</Button>
          )}
          {canManage && (
          <Popconfirm
            title={`确认删除配置 ${r.table_no}？`}
            description="删除后该表号的计算表将回落到旧解析器"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(r.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Card
      size="small"
      title="液相计算表模板配置（表号 取值位置）"
      extra={canManage ? (
        <Space>
          <Button size="small" icon={<ThunderboltOutlined />} onClick={() => { setAutoOpen(true); setAutoDetect(null); setAutoPick(null) }}>上传文件自动生成</Button>
          <Button size="small" icon={<PlusOutlined />} onClick={openCreate}>新增配置</Button>
        </Space>
      ) : null}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        表号来自计算表标题（如 EX-HA-5246-001）；新增产品线时在此登记表号与取值区块。
      </Text>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        size="small"
        scroll={{ x: 720 }}
        pagination={false}
      />

      <Modal
        title="傻瓜式维护：上传计算表自动生成配置"
        open={autoOpen}
        onCancel={() => setAutoOpen(false)}
        footer={autoDetect?.candidates.length ? [
          <Button key="cancel" onClick={() => setAutoOpen(false)}>取消</Button>,
          <Button key="ok" type="primary" loading={autoCreating} onClick={onAutoCreate}>生成配置</Button>,
        ] : null}
        width={720}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Upload.Dragger
            accept=".xlsx,.xls"
            showUploadList={false}
            beforeUpload={onAutoUpload}
            disabled={autoDetecting}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽计算表文件到此区域</p>
            <p className="ant-upload-hint">系统自动识别表号并匹配同版式模板，无需编写任何配置（JSON）</p>
          </Upload.Dragger>
          <Space>
            <Text type="secondary">文件密码（默认实验室通行密码，可清空）：</Text>
            <Input.Password size="small" style={{ width: 200 }} value={autoPassword}
              onChange={(e) => setAutoPassword(e.target.value)} autoComplete="new-password" />
          </Space>
          {autoDetecting && <Text type="secondary">正在识别版式…</Text>}
          {autoDetect && (
            <>
              <Text>识别表号：<Tag color="blue">{autoDetect.table_no}</Tag>
                {autoDetect.candidates.length
                  ? `共 ${autoDetect.candidates.length} 个同版式候选，选择其一生成：`
                  : '（无同版式候选，全新版式请联系管理员配置）'}
              </Text>
              {autoDetect.candidates.length > 0 && (
                <Radio.Group value={autoPick} onChange={(e) => setAutoPick(e.target.value)} style={{ width: '100%' }}>
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {autoDetect.candidates.map((c) => (
                      <Radio key={c.template_table_no} value={c.template_table_no} style={{ width: '100%' }}>
                        <Text strong>{c.template_table_no}</Text>
                        <Text type="secondary">　{c.product_name || '（无产品名）'}　提取到 {c.value_count}/{c.component_count} 个有效值</Text>
                        {c.blank && <Tag color="orange" style={{ marginLeft: 8 }}>空白模板（按版式匹配）</Tag>}
                        <div style={{ paddingLeft: 24 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            样例：{(c.samples || []).map((s) => `${s.name}=${s.value}`).join('，')}
                          </Text>
                        </div>
                      </Radio>
                    ))}
                  </Space>
                </Radio.Group>
              )}
            </>
          )}
        </Space>
      </Modal>

      <Modal
        title={`测试计算 ${testCfg ? testCfg.table_no : ''}（不落库，仅验证计算规则）`}
        open={testOpen}
        onCancel={() => setTestOpen(false)}
        footer={null}
        width={760}
      >
        {testCfg?.config.calc_sections && testCfg.config.calc_sections.length > 1 && (
          <Space style={{ marginBottom: 10 }}>
            {testCfg.config.calc_sections.map((sec, i) => (
              <Button
                key={i}
                size="small"
                type={testSection === i ? 'primary' : 'default'}
                onClick={() => { setTestSection(i); setTestInputs({}); setTestResult(null) }}
              >
                {sec.name}
              </Button>
            ))}
          </Space>
        )}
        {(() => {
          const cfg = testCfg?.config.calc_sections
            ? testCfg.config.calc_sections[testSection]?.calc
            : testCfg?.config.calc
          if (!cfg) return <Text type="secondary">该表号未配置计算规则</Text>
          return (
            <Space direction="vertical" style={{ width: '100%' }} size={10}>
              <CalcForm cfg={cfg} inputs={testInputs} onChange={setTestInputs} />
              <Button type="primary" onClick={runTest}>运行计算</Button>
              {testResult && (
                <Table
                  rowKey="std_name" size="small" pagination={false}
                  dataSource={testResult.items ?? []}
                  columns={[
                    { title: '项目', dataIndex: 'label', width: 180 },
                    { title: '结果', dataIndex: 'value', width: 120, render: (v: number | null, r: { nd?: boolean }) => v != null ? <Text strong>{v.toFixed(4)}{r.nd ? '（未检出）' : ''}</Text> : '-' },
                    { title: '明细', dataIndex: 'detail', ellipsis: true },
                  ]}
                />
              )}
            </Space>
          )
        })()}
      </Modal>

      <Modal
        title={editing ? `编辑配置 ${editing.table_no}` : '新增液相模板配置'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="table_no"
            label="表号（EX-xx-xxxx-vvv）"
            rules={[{ required: true, message: '请输入表号' }]}
          >
            <Input placeholder="EX-HA-5246-001" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '请输入产品名称' }]}>
            <Input placeholder="盐酸万古霉素" />
          </Form.Item>
          <Form.Item name="sop_no" label="对应 SOP 号（可选）">
            <Input placeholder="SOP.02.3205.010" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input placeholder="万古霉素冻干粉-赞比亚" />
          </Form.Item>
          <Form.Item name="config" label="取值配置 JSON" rules={[{ required: true, message: '请输入配置 JSON' }]}>
            <Input.TextArea rows={10} placeholder={'{\n  "batch_label": "批号",\n  "blocks": [...]\n}'} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
