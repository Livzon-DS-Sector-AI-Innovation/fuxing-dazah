'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Descriptions, Card, Modal, Form,
  InputNumber, Select, Popconfirm, Typography, Upload,
} from 'antd'
import {
  ArrowLeftOutlined, SaveOutlined, CheckCircleOutlined, StopOutlined,
  PlusOutlined, DeleteOutlined, RedoOutlined, UploadOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { TestResultItem, TestTaskDetail } from '@/types/quality'
import {
  fetchTestTaskDetail, updateTestResults, addTestResult,
  updateTestTaskStatus, deleteTestResult, parseLcIntoTask,
  generateTaskReports, downloadReportFile,
} from '@/actions/quality'

const { Text } = Typography

const STATUS_META: Record<string, { color: string; label: string }> = {
  in_progress: { color: 'processing', label: '填报中' },
  pending_review: { color: 'warning', label: '待复核' },
  completed: { color: 'success', label: '已完成' },
  void: { color: 'default', label: '已作废' },
}

/** 前端判定预览（与后端 _judge_value 同规则，后端判定为最终权威）。 */
function previewPass(
  operator: string | null,
  limitMin: number | null,
  limitMax: number | null,
  value: number | null,
): boolean | null {
  if (value === null) return null
  if (operator === '≤' && limitMax !== null) return value <= limitMax
  if (operator === '<' && limitMax !== null) return value < limitMax
  if (operator === '≥' && limitMin !== null) return value >= limitMin
  if (operator === '>' && limitMin !== null) return value > limitMin
  if (operator === '范围' && limitMin !== null && limitMax !== null) {
    return limitMin <= value && value <= limitMax
  }
  return null
}

interface EditDraft {
  result_text?: string | null
  result_value?: number | null
  is_pass?: boolean | null
}

export default function TaskDetail({ id }: { id: string }) {
  const router = useRouter()
  const { message } = App.useApp()
  const [detail, setDetail] = useState<TestTaskDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [edits, setEdits] = useState<Record<string, EditDraft>>({})

  const [addOpen, setAddOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addForm] = Form.useForm()

  const [generatingCoa, setGeneratingCoa] = useState(false)

  const loadDetail = useCallback(async () => {
    setLoading(true)
    try {
      const d = await fetchTestTaskDetail(id)
      setDetail(d)
    } catch (err: any) {
      message.error(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id, message])

  useEffect(() => { loadDetail() }, [loadDetail])

  if (!detail) {
    return loading ? <Text type="secondary">加载中…</Text> : null
  }

  // 填报中可填；待复核时专员可改结果（不留痕）
  const { hasPermission } = usePermission()
  const canFill = hasPermission('quality:task:fill')
  const canReview = hasPermission('quality:task:review')
  const editable =
    (detail.status === 'in_progress' && canFill) ||
    (detail.status === 'pending_review' && canReview)
  const setEdit = (resultId: string, patch: Partial<EditDraft>) => {
    setEdits((prev) => ({ ...prev, [resultId]: { ...prev[resultId], ...patch } }))
  }

  const handleSave = async () => {
    const results = Object.entries(edits)
      .filter(([, e]) => e.result_value != null || (e.result_text != null && e.result_text !== '') || e.is_pass != null)
      .map(([resultId, e]) => ({ result_id: resultId, ...e }))
    if (!results.length) {
      message.info('没有需要保存的修改')
      return
    }
    // 文字型行必须人工判定
    for (const r of results) {
      const row = detail.results.find((x) => x.id === r.result_id)
      if (row && row.judge_mode === 'manual' && r.is_pass == null) {
        message.warning(`项目「${row.item_name}」为文字型，请先选择判定（合格/不合格）`)
        return
      }
      if (row && row.judge_mode === 'auto' && r.result_value == null) {
        message.warning(`项目「${row.item_name}」为数值型，请填写结果值`)
        return
      }
    }
    setSaving(true)
    try {
      const res = await updateTestResults(id, results)
      setDetail(res.data)
      setEdits({})
      message.success('已保存')
    } catch (err: any) {
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleStatus = async (status: 'in_progress' | 'pending_review' | 'completed' | 'void', tip: string) => {
    try {
      const res = await updateTestTaskStatus(id, status)
      setDetail(res.data)
      message.success(tip)
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const handleAdd = async () => {
    const values = await addForm.validateFields()
    setAdding(true)
    try {
      await addTestResult(id, values)
      message.success('已追加项目行')
      setAddOpen(false)
      addForm.resetFields()
      loadDetail()
    } catch (err: any) {
      message.error(err.message || '追加失败')
    } finally {
      setAdding(false)
    }
  }

  // 一键将未填写的文字型项目全部标为「符合规定/合格」（减少逐行填写）
  const handleFillManualPass = async () => {
    const rows = detail.results.filter((r) => r.judge_mode === 'manual' && r.is_pass === null)
    if (!rows.length) {
      message.info('没有未填写的文字型项目')
      return
    }
    setSaving(true)
    try {
      const res = await updateTestResults(id, rows.map((r) => ({
        result_id: r.id, result_text: '符合规定', is_pass: true,
      })))
      setDetail(res.data)
      setEdits({})
      message.success(`已批量填入 ${rows.length} 个文字型项目（符合规定）`)
    } catch (err: any) {
      message.error(err.message || '操作失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteRow = async (resultId: string) => {
    try {
      await deleteTestResult(id, resultId)
      message.success('已删除')
      loadDetail()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const handleParseLc = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await parseLcIntoTask(id, fd)
      setDetail(res.data)
      setEdits({})
      message.success(res.message || '解析填入完成')
    } catch (err: any) {
      message.error(err.message || '解析填入失败')
    }
    return false
  }

  // 生成 COA：按标准文件逐份生成（一个批号多份标准 → 多份报告单），逐份下载
  const handleGenerateCoa = async () => {
    setGeneratingCoa(true)
    try {
      const res = await generateTaskReports(id)
      const files = res.data || []
      for (const f of files) {
        const blob = await downloadReportFile(f.report_id)
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = f.filename
        a.click()
        URL.revokeObjectURL(url)
      }
      message.success(files.length
        ? `已按标准文件逐份生成 ${files.length} 份 COA：${files.map((f) => f.file_no).join('、')}`
        : 'COA 已生成（见报告单页面）')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setGeneratingCoa(false)
    }
  }

  const renderFillCell = (row: TestResultItem) => {
    const draft = edits[row.id]
    if (row.judge_mode === 'auto') {
      const value = draft?.result_value != null ? draft.result_value : row.result_value
      const preview = previewPass(row.operator, row.limit_min, row.limit_max, value)
      const limitText = `${row.operator || ''} ${row.limit_min ?? ''}${row.limit_max ?? ''}`.trim()
      return (
        <Space size={8} direction="vertical" style={{ width: '100%' }}>
          <Space size={8}>
            <InputNumber
              size="small"
              style={{ width: 110 }}
              status={preview === false ? 'error' : undefined}
              placeholder={limitText}
              value={draft?.result_value ?? row.result_value ?? undefined}
              onChange={(v) => setEdit(row.id, { result_value: v ?? null })}
              disabled={!editable}
            />
            {preview !== null && (
              <Tag color={preview ? 'success' : 'error'}>{preview ? '合格' : '不合格'}</Tag>
            )}
          </Space>
          {preview === false && (
            <Text type="danger" style={{ fontSize: 12 }}>超出限度（{limitText}），请复核</Text>
          )}
        </Space>
      )
    }
    const isPass = draft?.is_pass != null ? draft.is_pass : row.is_pass
    return (
      <Space size={8} direction="vertical" style={{ width: '100%' }}>
        <Input
          size="small"
          placeholder="填写结果描述，如 白色粉末"
          value={draft?.result_text ?? row.result_text ?? ''}
          onChange={(e) => setEdit(row.id, { result_text: e.target.value })}
          disabled={!editable}
        />
        <Select
          size="small"
          style={{ width: 120 }}
          placeholder="判定"
          value={isPass ?? undefined}
          onChange={(v: boolean) => setEdit(row.id, { is_pass: v })}
          disabled={!editable}
          options={[{ label: '合格', value: true }, { label: '不合格', value: false }]}
        />
      </Space>
    )
  }

  const columns = [
    { title: '序号', dataIndex: 'seq', key: 'seq', width: 60, render: (v: number | null) => v ?? '-' },
    { title: '子项目', dataIndex: 'item_name', key: 'item_name', width: 150, ellipsis: true },
    { title: 'SOP号', dataIndex: 'sop_no', key: 'sop_no', width: 130, render: (v: string | null) => v || '-' },
    { title: '合格标准', dataIndex: 'standard_text', key: 'standard_text', width: 180, ellipsis: true,
      render: (v: string | null) => v || '-' },
    { title: '方法来源', dataIndex: 'method_source', key: 'method_source', width: 100, render: (v: string | null) => v || '-' },
    { title: '备注', dataIndex: 'remark', key: 'remark', width: 140, ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '填报', key: 'fill', width: 280, render: (_: any, row: TestResultItem) => renderFillCell(row) },
    {
      title: '已判定', dataIndex: 'is_pass', key: 'is_pass', width: 80,
      render: (v: boolean | null) => v === null
        ? <Tag>未填</Tag>
        : v ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_: any, row: TestResultItem) => editable ? (
        <Popconfirm title="确认删除该行?" onConfirm={() => handleDeleteRow(row.id)}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ) : null,
    },
  ]

  return (
    <div className="space-y-4">
      <Space wrap>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/quality/task')}>返回列表</Button>
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave} disabled={!editable}>保存</Button>
        {detail.status === 'in_progress' && (
          <>
            {canFill && (
              <>
                <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={handleParseLc}>
                  <Button icon={<UploadOutlined />}>上传液相计算表填入</Button>
                </Upload>
                <Button icon={<CheckCircleOutlined />} loading={saving} onClick={handleFillManualPass}>文字项一键合格</Button>
                <Button icon={<PlusOutlined />} onClick={() => { addForm.resetFields(); setAddOpen(true) }}>追加项目</Button>
              </>
            )}
            {canReview && (
              <Popconfirm title="作废后不可填报，确认作废?" onConfirm={() => handleStatus('void', '任务已作废')}>
                <Button icon={<StopOutlined />}>作废任务</Button>
              </Popconfirm>
            )}
          </>
        )}
        {detail.status === 'pending_review' && canReview && (
          <>
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => handleStatus('completed', '审核通过，任务已完成')}>审核通过</Button>
            <Popconfirm title="驳回后任务回到填报中，确认驳回?" onConfirm={() => handleStatus('in_progress', '已驳回，任务回到填报中')}>
              <Button icon={<RedoOutlined />}>驳回重填</Button>
            </Popconfirm>
            <Popconfirm title="确认作废该任务?" onConfirm={() => handleStatus('void', '任务已作废')}>
              <Button icon={<StopOutlined />}>作废任务</Button>
            </Popconfirm>
          </>
        )}
        {detail.status === 'completed' && (
          <>
            {hasPermission('quality:report:generate') && (
              <Button type="primary" icon={<FileTextOutlined />} loading={generatingCoa} onClick={handleGenerateCoa}>生成 COA（逐份）</Button>
            )}
            {canReview && (
              <>
                <Button icon={<RedoOutlined />} onClick={() => handleStatus('in_progress', '已重新打开')}>重新打开</Button>
                <Popconfirm title="确认作废该任务?" onConfirm={() => handleStatus('void', '任务已作废')}>
                  <Button icon={<StopOutlined />}>作废任务</Button>
                </Popconfirm>
              </>
            )}
          </>
        )}
      </Space>

      <Card size="small">
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="产品">{detail.product_name}</Descriptions.Item>
          <Descriptions.Item label="批号">{detail.batch_number}</Descriptions.Item>
          <Descriptions.Item label="生产日期">{detail.production_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="规格">{detail.specification || '-'}</Descriptions.Item>
          <Descriptions.Item label="效期">{detail.expiry_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="COA表格编号">{detail.form_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_META[detail.status].color}>{STATUS_META[detail.status].label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="进度">
            {detail.results.filter((r) => r.is_pass !== null).length}/{detail.results.length} 项已判定
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title="检阅清单（按 SOP 匹配的内容填报）">
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={detail.results}
          loading={loading}
          pagination={false}
          scroll={{ x: 1500 }}
        />
      </Card>

      <Modal
        title="追加临时项目行"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={handleAdd}
        okText="添加"
        confirmLoading={adding}
        width={620}
      >
        <Form form={addForm} layout="vertical" className="mt-4">
          <Form.Item name="item_name" label="子项目名称" rules={[{ required: true, message: '请输入子项目名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="category" label="检验项目大类">
            <Input placeholder="性状 / 有关物质" />
          </Form.Item>
          <Form.Item name="sop_no" label="SOP号（可选）">
            <Input placeholder="SOP.03.5214" />
          </Form.Item>
          <Form.Item name="standard_text" label="合格标准原文">
            <Input placeholder="≤3.0% / 应为白色粉末" />
          </Form.Item>
          <Space wrap>
            <Form.Item name="operator" label="运算符" initialValue="≤">
              <Select
                style={{ width: 110 }}
                options={[{ value: '≤', label: '≤' }, { value: '≥', label: '≥' },
                  { value: '<', label: '<' }, { value: '>', label: '>' }, { value: '范围', label: '范围' }]}
              />
            </Form.Item>
            <Form.Item name="limit_min" label="下限">
              <InputNumber style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="limit_max" label="上限">
              <InputNumber style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="method_source" label="方法来源">
              <Input style={{ width: 120 }} placeholder="IP / 内部" />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input />
          </Form.Item>
        </Form>
      </Modal>

    </div>
  )
}
