'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Descriptions, Card, Modal, Form,
  InputNumber, Select, Popconfirm, Typography, Upload, Result, Skeleton, DatePicker,
} from 'antd'
import {
  ArrowLeftOutlined, SaveOutlined, CheckCircleOutlined, StopOutlined,
  PlusOutlined, DeleteOutlined, RedoOutlined, UploadOutlined, FileTextOutlined,
  HistoryOutlined, DownloadOutlined, EyeOutlined, InboxOutlined, CalculatorOutlined, FileImageOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import dayjs, { type Dayjs } from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import { REPORT_AUDIT_META, TASK_STATUS_META } from '@/types/quality'
import type { ReportAuditStatus, TestResultItem, TestTaskDetail, TaskAttachment,
  TaskReportItem, TaskReviewRecord, LcTemplateConfig } from '@/types/quality'
import {
  fetchTestTaskDetail, updateTestResults, addTestResult,
  updateTestTaskStatus, deleteTestResult, parseLcIntoTask,
  generateTaskReports, downloadReportFile,
  fetchTaskAttachments, uploadTaskAttachment, downloadTaskAttachment, deleteTaskAttachment,
  fetchTaskReviews, approveTaskReview,
  fetchTaskReports,
  fetchTaskHandover,
  confirmTaskResult,
  createRetainedSample,
  fetchLcTemplateConfigs,
  submitCalcFill,
} from '@/actions/quality'
import { CoaPreviewModal, CalcForm, ChromatogramModal } from '@/components/quality'

const { Text } = Typography

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
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [edits, setEdits] = useState<Record<string, EditDraft>>({})

  const [addOpen, setAddOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addForm] = Form.useForm()

  const [generatingCoa, setGeneratingCoa] = useState(false)
  // 多份 COA 生成后的逐份下载弹窗（连续自动下载会被浏览器拦截）
  const [coaFiles, setCoaFiles] = useState<{ report_id: string; filename: string; file_no: string }[]>([])
  const [coaPreviewId, setCoaPreviewId] = useState<string | null>(null)
  const [handoverOpen, setHandoverOpen] = useState(false)
  const [handover, setHandover] = useState<{
    product_name: string; batch_number: string; filled: number; total: number;
    unfilled: string[]; items: { name: string; value: string | number; verdict: string }[];
    reports: { serial_no: string | null; filename: string | null }[];
  } | null>(null)
  const [retainOpen, setRetainOpen] = useState(false)
  const [retainSaving, setRetainSaving] = useState(false)
  const [retainForm] = Form.useForm()
  // 在线计算表：免 Excel 直接填计算后数值（表号合并规则由后端计算）
  const [calcOpen, setCalcOpen] = useState(false)
  const [chromaOpen, setChromaOpen] = useState(false)
  const [calcSaving, setCalcSaving] = useState(false)
  const [calcTableNo, setCalcTableNo] = useState<string | undefined>()
  const [calcDate, setCalcDate] = useState<Dayjs | null>(dayjs())
  const [calcValues, setCalcValues] = useState<Record<string, number | undefined>>({})
  const [calcInputs, setCalcInputs] = useState<Record<string, number | undefined>>({})
  const [calcConfigs, setCalcConfigs] = useState<LcTemplateConfig[]>([])

  const [attachments, setAttachments] = useState<TaskAttachment[]>([])
  const [reviews, setReviews] = useState<TaskReviewRecord[]>([])
  const [taskReports, setTaskReports] = useState<TaskReportItem[]>([])
  // 已通过的复核人数：按复核人去重（后端已禁止同一人重复计，防御性去重）
  const approvedCount = new Set(reviews.map((r) => r.reviewer_id)).size
  const [attPreview, setAttPreview] = useState<{ filename: string; url: string; type: string } | null>(null)

  const loadDetail = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const d = await fetchTestTaskDetail(id)
      setDetail(d)
      // 附属数据逐个容错：任一失败不拖垮其余区块（此前 Promise.all 原子失败
      // 会导致附件/复核/报告单三块全空且无任何提示）
      const [atts, revs, reps] = await Promise.all([
        fetchTaskAttachments(id).catch(() => null),
        fetchTaskReviews(id).catch(() => null),
        fetchTaskReports(id).catch(() => null),
      ])
      setAttachments(atts?.data || [])
      setReviews(revs?.data || [])
      setTaskReports(reps?.data || [])
    } catch (err: unknown) {
      setLoadError((err instanceof Error ? err.message : String(err)) || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { (async () => { await loadDetail() })() }, [loadDetail])

  // 填报中可填；待复核时专员可改结果（不留痕）
  const { hasPermission } = usePermission()
  const canFill = hasPermission('quality:task:fill')
  const canViewReport = hasPermission('quality:report:read')
  const canReview = hasPermission('quality:task:review')
  const canManageMaterial = hasPermission('quality:material:manage')

  const openRetain = () => {
    if (!detail) return
    retainForm.setFieldsValue({
      source_type: 'product',
      batch_no: detail.batch_number,
      sample_name: detail.product_name,
      qty: undefined,
      location: undefined,
      retained_at: dayjs(),
      destroy_due_date: undefined,
      remark: undefined,
    })
    setRetainOpen(true)
  }

  const onRetainSave = async () => {
    const values = await retainForm.validateFields()
    setRetainSaving(true)
    try {
      await createRetainedSample({
        ...values,
        retained_at: values.retained_at ? (values.retained_at as Dayjs).format('YYYY-MM-DD') : undefined,
        destroy_due_date: values.destroy_due_date ? (values.destroy_due_date as Dayjs).format('YYYY-MM-DD') : undefined,
      })
      message.success('留样登记已保存，销毁到期前飞书群会每日提醒')
      setRetainOpen(false)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '留样登记失败')
    } finally {
      setRetainSaving(false)
    }
  }

  // 在线计算表：未填的数值型项目行（manual 行不在此表单）
  const calcRows = (detail?.results ?? []).filter((r) => r.judge_mode === 'auto' && r.is_pass === null)
  const activeCalcCfg = calcConfigs.find((c) => c.table_no === calcTableNo)?.config.calc
  const calcMergeRules = (calcConfigs
    .find((c) => c.table_no === calcTableNo)
    ?.config as { merge?: { op: string; from: string[]; into: string }[] } | undefined)?.merge ?? []
  const normItem = (n: string) => n.replace(/\s+/g, '')
  const calcTyped: Record<string, number> = {}
  for (const r of calcRows) {
    const v = calcValues[r.id]
    if (v != null) calcTyped[normItem(r.item_name)] = v
  }

  const openCalc = () => {
    setCalcValues({})
    setCalcInputs({})
    setCalcTableNo(undefined)
    setCalcDate(dayjs())
    setCalcOpen(true)
    void fetchLcTemplateConfigs().then((res) => setCalcConfigs(res.data)).catch(() => { /* 表号拉取失败仍可无表号填报 */ })
  }

  const onCalcSubmit = async () => {
    const useEngine = !!activeCalcCfg
    let payload: { table_no?: string; record_date?: string; values: { item_name: string; value: number }[]; inputs?: Record<string, number | undefined> }
    if (useEngine) {
      const filledInputs = Object.fromEntries(
        Object.entries(calcInputs).filter(([, v]) => v != null && v > 0),
      )
      if (!Object.keys(filledInputs).length) {
        message.warning('请至少填写一项原始数据')
        return
      }
      payload = {
        table_no: calcTableNo,
        record_date: calcDate ? calcDate.format('YYYY-MM-DD') : undefined,
        values: [],
        inputs: filledInputs,
      }
    } else {
      const values = calcRows
        .map((r) => ({ item_name: r.item_name, value: calcValues[r.id] }))
        .filter((v): v is { item_name: string; value: number } => v.value != null)
      if (!values.length) {
        message.warning('请至少填写一个项目数值')
        return
      }
      payload = {
        table_no: calcTableNo,
        record_date: calcDate ? calcDate.format('YYYY-MM-DD') : undefined,
        values,
      }
    }
    setCalcSaving(true)
    try {
      const res = await submitCalcFill(id, payload)
      message.success(res.message)
      setCalcOpen(false)
      loadDetail()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '计算表提交失败')
    } finally {
      setCalcSaving(false)
    }
  }

  if (!detail) {
    if (loadError) {
      return (
        <Result
          status="error"
          title="加载失败"
          subTitle={loadError}
          extra={<Button type="primary" onClick={loadDetail}>重试</Button>}
        />
      )
    }
    return <Skeleton active paragraph={{ rows: 6 }} />
  }

  // 「待分配」派生口径与机器人一致：填报中且出报日期在未来
  const displayStatus = detail.status === 'in_progress' && detail.report_date && detail.report_date > dayjs().format('YYYY-MM-DD')
    ? { color: 'cyan', label: '待分配' }
    : (TASK_STATUS_META[detail.status] ?? { color: 'default', label: detail.status })

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
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleStatus = async (status: 'in_progress' | 'pending_review' | 'completed' | 'void', tip: string) => {
    try {
      const res = await updateTestTaskStatus(id, status)
      setDetail(res.data)
      message.success(tip)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '操作失败')
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
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '追加失败')
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
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '操作失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteRow = async (resultId: string) => {
    try {
      await deleteTestResult(id, resultId)
      message.success('已删除')
      loadDetail()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
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
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '解析填入失败')
    }
    return false
  }

  // 生成 COA：按标准文件逐份生成（一个批号多份标准 多份报告单）。
  // 单份直接下载；多份弹窗列出逐份下载（连续 a.click 会被浏览器拦截）
  const downloadCoaOne = async (f: { report_id: string; filename: string }) => {
    const blob = await downloadReportFile(f.report_id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = f.filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleGenerateCoa = async () => {
    setGeneratingCoa(true)
    try {
      const res = await generateTaskReports(id)
      const files = res.data || []
      if (files.length === 1) {
        await downloadCoaOne(files[0])
      } else if (files.length > 1) {
        setCoaFiles(files)
      }
      message.success(files.length
        ? `已按标准文件逐份生成 ${files.length} 份 COA：${files.map((f) => f.file_no).join('、')}`
        : 'COA 已生成（见报告单页面）')
      // 刷新本任务报告单列表（主链路闭环：生成即见）；刷新失败不影响成功提示
      try {
        const reps = await fetchTaskReports(id)
        setTaskReports(reps.data || [])
      } catch { /* 忽略刷新失败 */ }
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '生成失败')
    } finally {
      setGeneratingCoa(false)
    }
  }

  // 附件上传：原始证据（计算表/图谱 PDF/图片等）持久化归档，随时调取
  const handleAttUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      await uploadTaskAttachment(id, formData)
      message.success('附件已归档')
      loadDetail()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '上传失败')
    }
    return false
  }

  const handleAttDownload = async (att: TaskAttachment) => {
    try {
      const blob = await downloadTaskAttachment(id, att.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = att.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '下载失败')
    }
  }

  const handleAttPreview = async (att: TaskAttachment) => {
    try {
      const blob = await downloadTaskAttachment(id, att.id)
      // 释放上一个预览的 ObjectURL（此前只在关闭弹窗时释放，连续预览会泄漏）
      setAttPreview((prev) => {
        if (prev) URL.revokeObjectURL(prev.url)
        return { filename: att.filename, url: URL.createObjectURL(blob), type: att.content_type }
      })
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '预览失败')
    }
  }

  const handleAttDelete = async (att: TaskAttachment) => {
    try {
      await deleteTaskAttachment(id, att.id)
      message.success('已删除')
      loadDetail()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  // 双人复核：两名不同复核人通过后任务完成
  const handleApprove = async (thenGenerateCoa: boolean) => {
    try {
      const res = await approveTaskReview(id)
      const count = res.data?.approved_count ?? 0
      const required = res.data?.review_required ?? 2
      if (res.data?.status === 'completed') {
        message.success(`复核通过（${count}/${required}），任务已完成`)
        await loadDetail()
        if (thenGenerateCoa) await handleGenerateCoa()
      } else {
        message.info(`复核已记录（${count}/${required}），等待另一位复核人`)
        await loadDetail()
      }
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '复核失败')
    }
  }

  const renderFillCell = (row: TestResultItem) => {
    const draft = edits[row.id]
    if (row.judge_mode === 'auto') {
      const value = draft?.result_value != null ? draft.result_value : row.result_value
      const preview = previewPass(row.operator, row.limit_min, row.limit_max, value)
      const limitText = row.operator === '范围' && row.limit_min != null && row.limit_max != null
    ? `${row.limit_min}~${row.limit_max}`
    : `${row.operator || ''} ${row.limit_min ?? ''}${row.limit_max ?? ''}`.trim()
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
    { title: '填报', key: 'fill', width: 280, render: (_: unknown, row: TestResultItem) => renderFillCell(row) },
    {
      title: '已判定', dataIndex: 'is_pass', key: 'is_pass', width: 110,
      render: (v: boolean | null, row: TestResultItem) => row.pending_confirm
        ? <Tag color="orange">待确认</Tag>
        : v === null
          ? <Tag>未填</Tag>
          : v ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 130,
      render: (_: unknown, row: TestResultItem) => editable ? (
        <Space size={4}>
          {row.pending_confirm && (
            <Popconfirm
              title={`确认归入：${row.item_name} ${row.result_value ?? ''}（${row.is_pass ? '合格' : '不合格'}）`}
              onConfirm={async () => {
                try { await confirmTaskResult(id, row.id); message.success('已确认归入'); loadDetail() }
                catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '确认失败') }
              }}
            >
              <Button size="small" type="primary">确认</Button>
            </Popconfirm>
          )}
          <Popconfirm title="确认删除该行?" onConfirm={() => handleDeleteRow(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ) : null,
    },
  ]

  return (
    <div className="space-y-4">
      <Space wrap>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/quality/task')}>返回列表</Button>
        <Button icon={<FileTextOutlined />} onClick={async () => {
          try {
            const res = await fetchTaskHandover(id)
            setHandover(res.data)
            setHandoverOpen(true)
          } catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '获取交接汇总失败') }
        }}>交接汇总</Button>
        {canManageMaterial && (
          <Button icon={<InboxOutlined />} onClick={openRetain}>留样登记</Button>
        )}
        {canFill && detail.status === 'in_progress' && (
          <Button icon={<CalculatorOutlined />} onClick={openCalc}>在线计算表</Button>
        )}
        {canFill && detail.status === 'in_progress' && (
          <Button icon={<FileImageOutlined />} onClick={() => setChromaOpen(true)}>图谱解析</Button>
        )}
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave} disabled={!editable}>保存</Button>
        {detail.status === 'in_progress' && (
          <>
            {canFill && (
              <>
                <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={handleParseLc}>
                  <Button icon={<UploadOutlined />}>上传液相计算表填入</Button>
                </Upload>
                <Popconfirm
                  title="批量填入文字项"
                  description={`将 ${detail.results.filter((r) => r.judge_mode === 'manual' && r.is_pass === null).length} 个未填写的文字型项目全部标为「符合规定/合格」，确认？`}
                  okText="确认填入"
                  cancelText="取消"
                  onConfirm={handleFillManualPass}
                >
                  <Button icon={<CheckCircleOutlined />} loading={saving}>文字项一键合格</Button>
                </Popconfirm>
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
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => handleApprove(false)}>复核通过（{approvedCount}/2）</Button>
            {hasPermission('quality:report:generate') && (
              <Button type="primary" icon={<FileTextOutlined />} loading={generatingCoa}
                onClick={() => handleApprove(true)}>
                复核通过并生成 COA
              </Button>
            )}
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
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
          <Descriptions.Item label="产品">{detail.product_name}</Descriptions.Item>
          <Descriptions.Item label="批号">{detail.batch_number}</Descriptions.Item>
          <Descriptions.Item label="生产日期">{detail.production_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="规格">{detail.specification || '-'}</Descriptions.Item>
          <Descriptions.Item label="效期">{detail.expiry_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="COA表格编号">{detail.form_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={displayStatus.color}>{displayStatus.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="进度">
            {detail.results.filter((r) => r.is_pass !== null && !r.pending_confirm).length}/{detail.results.length} 项已判定
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {taskReports.length > 0 && (
        <Card size="small" title={`本任务报告单（${taskReports.length} 份）`}>
          <Table
            rowKey="report_id"
            size="small"
            pagination={false}
            dataSource={taskReports}
            columns={[
              { title: '流水号', dataIndex: 'serial_no', key: 'serial_no', width: 110 },
              { title: '审核', dataIndex: 'audit_status', key: 'audit_status', width: 80,
                render: (v: ReportAuditStatus) => {
                  const meta = REPORT_AUDIT_META[v] ?? { color: 'default', label: v }
                  return <Tag color={meta.color}>{meta.label}</Tag>
                } },
              { title: '模板', dataIndex: 'template_path', key: 'template_path', ellipsis: true },
              {
                title: '生成时间', dataIndex: 'created_at', key: 'created_at', width: 170,
                render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-',
              },
              {
                title: '操作', key: 'actions', width: 150,
                render: (_: unknown, r: TaskReportItem) => canViewReport ? (
                  <Space size={4}>
                    <Button size="small" icon={<EyeOutlined />}
                      onClick={() => setCoaPreviewId(r.report_id)}>预览</Button>
                    <Button size="small" icon={<DownloadOutlined />}
                      onClick={() => downloadCoaOne({ report_id: r.report_id, filename: r.filename || `COA-${detail.batch_number}.docx` })}>
                      下载
                    </Button>
                  </Space>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    预览/下载需报告单查看权限
                  </Typography.Text>
                ),
              },
            ]}
          />
        </Card>
      )}

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

      <Card size="small" title="原始证据（计算表 / 电子图谱，持久化归档随时调取）">
        <Space style={{ marginBottom: 12 }} wrap>
          {canFill && (
            <Upload showUploadList={false} beforeUpload={handleAttUpload}>
              <Button icon={<UploadOutlined />}>上传原始证据</Button>
            </Upload>
          )}
          <Button size="small" icon={<HistoryOutlined />}
            onClick={() => router.push(`/quality/history?batch_number=${encodeURIComponent(detail.batch_number)}`)}>
            液相解析记录
          </Button>
          {detail.status === 'pending_review' && (
            <Text type="warning">
              复核进度：{approvedCount}/2 人已通过
              {reviews.length > 0 && `（${reviews.map((r, i) =>
                `${i + 1}号复核${r.reviewer_name ? `（${r.reviewer_name}）` : ''}：${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '-'}${r.comment ? `，备注「${r.comment}」` : ''}`
              ).join('；')}）`}
            </Text>
          )}
        </Space>
        {attachments.length === 0 ? (
          <Text type="secondary">暂无附件。上传计算表解析时会自动归档原始文件，也可手动上传图谱等证据。</Text>
        ) : (
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={attachments}
            columns={[
              { title: '文件名', dataIndex: 'filename', key: 'filename', ellipsis: true },
              { title: '来源', dataIndex: 'source', key: 'source', width: 100,
                render: (v: string) => v === 'parse' ? <Tag color="blue">自动归档</Tag> : <Tag>人工上传</Tag> },
              { title: '大小', dataIndex: 'size', key: 'size', width: 90,
                render: (v: number) => `${(v / 1024).toFixed(1)}KB` },
              { title: '备注', dataIndex: 'remark', key: 'remark', width: 160, render: (v: string | null) => v || '-' },
              { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160,
                render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
              { title: '操作', key: 'actions', width: 180,
                render: (_: unknown, a: TaskAttachment) => (
                  <Space size={4}>
                    {(a.content_type.startsWith('image/') || a.content_type === 'application/pdf') && (
                      <Button size="small" onClick={() => handleAttPreview(a)}>预览</Button>
                    )}
                    <Button size="small" onClick={() => handleAttDownload(a)}>下载</Button>
                    {canReview && (
                      <Popconfirm title="确认删除该附件?" onConfirm={() => handleAttDelete(a)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        )}
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

      <Modal
        title={attPreview?.filename}
        open={!!attPreview}
        footer={null}
        onCancel={() => { if (attPreview) URL.revokeObjectURL(attPreview.url); setAttPreview(null) }}
        width="min(900px, 94vw)"
      >
        {attPreview && attPreview.type.startsWith('image/') && (
          <img src={attPreview.url} alt={attPreview.filename} style={{ maxWidth: '100%' }} />
        )}
        {attPreview && attPreview.type === 'application/pdf' && (
          <iframe src={attPreview.url} title={attPreview.filename}
            style={{ width: '100%', height: '70vh', border: 'none' }} />
        )}
      </Modal>

      <Modal
        title={`已生成 ${coaFiles.length} 份 COA，请逐份下载`}
        open={coaFiles.length > 0}
        footer={null}
        onCancel={() => setCoaFiles([])}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          {coaFiles.map((f) => (
            <Space key={f.report_id} style={{ justifyContent: 'space-between', width: '100%' }}>
              <Typography.Text ellipsis style={{ maxWidth: 360 }}>
                {f.file_no}（{f.filename}）
              </Typography.Text>
              <Button
                size="small"
                icon={<EyeOutlined />}
                onClick={() => setCoaPreviewId(f.report_id)}
              >
                预览
              </Button>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => downloadCoaOne(f)}
              >
                下载
              </Button>
            </Space>
          ))}
        </Space>
      </Modal>
      <Modal
        title={`在线计算表 ${detail ? `（${detail.product_name} 批号 ${detail.batch_number}）` : ''}`}
        open={calcOpen}
        onCancel={() => setCalcOpen(false)}
        onOk={onCalcSubmit}
        confirmLoading={calcSaving}
        okText="提交填入"
        width={640}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          {activeCalcCfg
            ? '原始数据填峰面积/质量，系统按表号计算规则自动算百分比、判定并填入任务（不合格不落库），双份平均与 RSD 系统计算。'
            : '免 Excel：直接把计算好的数值填进来，系统按任务限度自动判定并填入（不合格不落库）；选择表号时自动套用合并规则（如 杂质B(B1+B2)=B1+B2）。'}
        </Typography.Paragraph>
        <Space size={12} style={{ display: 'flex', marginBottom: 12 }}>
          <Select
            allowClear placeholder="计算表表号" style={{ flex: 1 }}
            value={calcTableNo}
            onChange={setCalcTableNo}
            options={calcConfigs.map((c) => ({ value: c.table_no, label: c.table_no }))}
          />
          <DatePicker value={calcDate} onChange={setCalcDate} />
        </Space>
        {activeCalcCfg ? (
          <CalcForm cfg={activeCalcCfg} inputs={calcInputs} onChange={setCalcInputs} />
        ) : (
          <>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={calcRows}
              scroll={{ x: 560 }}
              columns={[
                { title: '项目', dataIndex: 'item_name', width: 160 },
                { title: '限度', dataIndex: 'standard_text', width: 130, render: (v: string | null) => v || '-' },
                {
                  title: '结果值', key: 'value', width: 130,
                  render: (_: unknown, r: TestResultItem) => (
                    <InputNumber
                      size="small" style={{ width: '100%' }}
                      value={calcValues[r.id]}
                      onChange={(v) => setCalcValues((m) => ({ ...m, [r.id]: v ?? undefined }))}
                    />
                  ),
                },
                {
                  title: '预判', key: 'preview', width: 90,
                  render: (_: unknown, r: TestResultItem) => {
                    const v = calcValues[r.id]
                    if (v == null) return '-'
                    const pass = previewPass(r.operator, r.limit_min, r.limit_max, v)
                    return pass === null ? <Tag>需人工判定</Tag> : pass ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag>
                  },
                },
              ]}
            />
            {calcMergeRules.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>合并计算项（表号 {calcTableNo} 规则，自动求和）：</Typography.Text>
                {calcMergeRules.map((rule, i) => {
                  const computed = rule.from.every((n) => calcTyped[normItem(n)] != null)
                    ? rule.from.reduce((a, n) => a + (calcTyped[normItem(n)] ?? 0), 0)
                    : null
                  return (
                    <div key={i} style={{ fontSize: 13, paddingBlock: 2 }}>
                      {rule.into} = {rule.from.join(' + ')} = <Typography.Text strong>{computed != null ? computed : '（待填齐）'}</Typography.Text>
                    </div>
                  )
                })}
              </div>
            )}
            {calcRows.length === 0 && (
              <Typography.Text type="secondary">本任务数值型项目已全部填写，无待填项。</Typography.Text>
            )}
          </>
        )}
      </Modal>

      <Modal
        title={`留样登记 ${detail ? `（${detail.product_name} 批号 ${detail.batch_number}）` : ''}`}
        open={retainOpen}
        onCancel={() => setRetainOpen(false)}
        onOk={onRetainSave}
        confirmLoading={retainSaving}
        okText="保存"
        width={520}
      >
        <Form form={retainForm} layout="vertical">
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="source_type" label="类型" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={[
                { value: 'product', label: '成品' },
                { value: 'material', label: '物料' },
              ]} />
            </Form.Item>
            <Form.Item name="batch_no" label="批号" rules={[{ required: true, message: '必填' }]} style={{ flex: 1 }}>
              <Input maxLength={100} />
            </Form.Item>
          </Space>
          <Form.Item name="sample_name" label="品名/名称" rules={[{ required: true, message: '必填' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="qty" label="留样量（如 2 瓶）" style={{ flex: 1 }}>
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item name="location" label="贮存位置（柜号）" style={{ flex: 1 }}>
              <Input maxLength={50} />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="retained_at" label="留样日期" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="destroy_due_date" label="销毁到期日" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="交接汇总"
        open={handoverOpen}
        onCancel={() => setHandoverOpen(false)}
        footer={<Button onClick={() => setHandoverOpen(false)}>关闭</Button>}
        width={620}
      >
        {handover && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text strong>{handover.product_name} 批号 {handover.batch_number}</Typography.Text>
            <Typography.Text type="secondary">
              已完成 {handover.filled}/{handover.total} 项
              {handover.unfilled?.length > 0 && <Typography.Text type="warning">｜未完成：{handover.unfilled.join('、')}</Typography.Text>}
              {handover.reports?.length > 0 && <>｜报告单：{handover.reports.map((r: { serial_no: string | null }) => r.serial_no ?? '无流水号').join('、')}</>}
            </Typography.Text>
            <Table
              size="small"
              rowKey="name"
              pagination={false}
              dataSource={handover.items}
              columns={[
                { title: '项目', dataIndex: 'name' },
                { title: '结果', dataIndex: 'value', width: 160 },
                { title: '判定', dataIndex: 'verdict', width: 100, render: (v: string) => <Tag color={v === '合格' ? 'green' : v === '不合格' ? 'red' : 'default'}>{v}</Tag> },
              ]}
            />
          </Space>
        )}
      </Modal>


      <ChromatogramModal
        open={chromaOpen}
        taskId={id}
        title={`图谱解析${detail ? `（${detail.product_name} 批号 ${detail.batch_number}）` : ''}`}
        onClose={() => setChromaOpen(false)}
        onFilled={loadDetail}
      />

      <CoaPreviewModal
        open={!!coaPreviewId}
        reportId={coaPreviewId}
        title="报告单预览"
        onClose={() => setCoaPreviewId(null)}
      />

    </div>
  )
}
