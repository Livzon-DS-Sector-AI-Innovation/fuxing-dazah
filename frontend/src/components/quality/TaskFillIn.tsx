'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Select, Modal, Form, DatePicker, Progress,
} from 'antd'
import {
  SearchOutlined, PlusOutlined, FormOutlined, StopOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type { TestTaskListItem, TestTaskStatus } from '@/types/quality'
import {
  fetchTestTasks, createTestTask, updateTestTaskStatus, deleteTestTask,
  updateTestTaskReportDate,
  fetchStandardDocuments, fetchStandardItems,
  type StandardDocument,
} from '@/actions/quality'

const STATUS_META: Record<TestTaskStatus, { color: string; label: string }> = {
  in_progress: { color: 'processing', label: '填报中' },
  pending_review: { color: 'warning', label: '待复核' },
  completed: { color: 'success', label: '已完成' },
  void: { color: 'default', label: '已作废' },
}

export default function TaskFillIn() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('quality:task:create')
  const canFill = hasPermission('quality:task:fill')
  const canReview = hasPermission('quality:task:review')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<TestTaskListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [productSearch, setProductSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<TestTaskStatus | undefined>()

  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [productDocs, setProductDocs] = useState<StandardDocument[]>([])
  const [sopLoading, setSopLoading] = useState(false)
  const [sopOptions, setSopOptions] = useState<{ label: string; value: string }[]>([])
  const [createForm] = Form.useForm()

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await fetchTestTasks(productSearch || undefined, statusFilter, p)
      setData(res.data)
      setTotal(res.meta.total)
    } catch (err: any) {
      message.error(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [productSearch, statusFilter, message])

  useEffect(() => { load(page) }, [page, load])

  const openCreateModal = async () => {
    createForm.resetFields()
    setSopOptions([])
    setCreateOpen(true)
    try {
      const res = await fetchStandardDocuments()
      setProductDocs(res.data || [])
    } catch { /* 产品选项加载失败不阻塞建任务弹窗 */ }
  }

  // 产品名归一化（忽略空白差异，与后端匹配规则一致）
  const nameKey = (n: string) => n.replace(/\s+/g, '')

  // 产品名称选项：自动收敛去重（相同产品名只显示一条）
  const productOptions = useMemo(() => {
    const seen = new Map<string, string>()
    for (const d of productDocs) {
      const k = nameKey(d.product_name)
      if (!seen.has(k)) seen.set(k, d.product_name)
    }
    return Array.from(seen.values()).map((n) => ({ label: n, value: n }))
  }, [productDocs])

  // 批号必然含产品代号：选产品+填批号后自动识别批号开头的代号（最长前缀优先）
  const watchedProduct: string | undefined = Form.useWatch('product_name', createForm)
  const watchedBatch: string | undefined = Form.useWatch('batch_number', createForm)

  // 校验器内取最新文档列表（避免渲染闭包里的旧 productDocs 导致粘贴/输入法一次性输入时误报）
  const productDocsRef = useRef<StandardDocument[]>(productDocs)
  useEffect(() => { productDocsRef.current = productDocs }, [productDocs])

  // 该产品在标准库中的全部代号（按长度降序，保证 HAF 优先于 HA 类短代号）
  const productCodes = useMemo(() => {
    const codes = new Set<string>()
    for (const d of productDocs) {
      if (nameKey(d.product_name) === nameKey(watchedProduct || '') && d.product_code?.trim()) {
        codes.add(d.product_code.trim().toUpperCase())
      }
    }
    return Array.from(codes).sort((a, b) => b.length - a.length)
  }, [productDocs, watchedProduct])

  // 从批号开头识别出的产品代号（识别不到为 null）
  const matchedCode = useMemo(() => {
    if (!watchedBatch) return null
    const b = watchedBatch.trim().toUpperCase()
    return productCodes.find((c) => b.startsWith(c)) ?? null
  }, [watchedBatch, productCodes])

  // 标准文件 = 批号代号下的标准文档（file_no 如 SOP.02.3205.010）；一个批号可开多份报告单 → 可多选
  const matchedDocIds: string[] | undefined = Form.useWatch('standard_document_ids', createForm)

  // 该代号下的标准文件选项
  const docOptions = useMemo(() => {
    if (!watchedProduct || !matchedCode) return []
    return productDocs
      .filter(
        (d) => nameKey(d.product_name) === nameKey(watchedProduct) && (d.product_code || '').toUpperCase() === matchedCode,
      )
      .map((d) => ({ label: d.file_no, value: d.id }))
  }, [productDocs, watchedProduct, matchedCode])

  // 规格可选项：从所选全部标准文件的 specification 合并解析（唯一规格自动默认）
  const specOptions = useMemo(() => {
    if (!matchedDocIds?.length) return []
    const parts = new Set<string>()
    for (const d of productDocs) {
      if (!matchedDocIds.includes(d.id)) continue
      for (const s of (d.specification || '').split(/[、，,；;]/)) {
        const t = s.replace(/[。.]$/, '').trim()
        if (t) parts.add(t)
      }
    }
    return Array.from(parts)
  }, [productDocs, matchedDocIds])

  const handleProductChange = () => {
    createForm.setFieldValue('batch_number', undefined)
    createForm.setFieldValue('standard_document_ids', undefined)
    createForm.setFieldValue('sop_ids', undefined)
    createForm.setFieldValue('specification', undefined)
    setSopOptions([])
  }

  // 识别出代号后：该代号只有一份标准文件时自动默认，多份时让用户勾选
  useEffect(() => {
    createForm.setFieldValue('sop_ids', undefined)
    createForm.setFieldValue('specification', undefined)
    setSopOptions([])
    if (!matchedCode) {
      createForm.setFieldValue('standard_document_ids', undefined)
      return
    }
    if (docOptions.length === 1) {
      createForm.setFieldValue('standard_document_ids', [docOptions[0].value])
    } else {
      createForm.setFieldValue('standard_document_ids', undefined)
    }
  }, [matchedCode, docOptions, createForm])

  // 代号识别结果变化后重校验批号字段：清除粘贴/输入法一次性输入时遗留的旧校验结果
  useEffect(() => {
    if (!matchedCode) return
    createForm.validateFields(['batch_number']).catch(() => { /* 错误由表单字段呈现 */ })
  }, [matchedCode, createForm])

  // 选中标准文件后，加载其全部检验项目合并（默认全选）；规格唯一时自动默认
  useEffect(() => {
    let cancelled = false
    createForm.setFieldValue('sop_ids', undefined)
    createForm.setFieldValue('specification', undefined)
    setSopOptions([])
    if (!matchedDocIds?.length) return
    setSopLoading(true)
    ;(async () => {
      try {
        const opts: { label: string; value: string }[] = []
        for (const docId of matchedDocIds) {
          const res = await fetchStandardItems(docId)
          for (const it of res.data || []) {
            opts.push({ label: `${it.sop_no || '无SOP号'} ${it.item_name}`, value: it.id })
          }
        }
        if (cancelled) return
        setSopOptions(opts)
        createForm.setFieldValue('sop_ids', opts.map((o) => o.value))
        if (specOptions.length === 1) {
          createForm.setFieldValue('specification', specOptions[0])
        }
      } catch {
        if (!cancelled) message.error('加载检验项目失败')
      } finally {
        if (!cancelled) setSopLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [matchedDocIds, specOptions, createForm, message])

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    if (!values.sop_ids?.length) {
      message.warning('请选择本批要做的检验项目')
      return
    }
    setCreating(true)
    try {
      await createTestTask({
        product_name: values.product_name,
        batch_number: values.batch_number,
        production_date: values.production_date ? values.production_date.format('YYYY-MM-DD') : undefined,
        specification: values.specification,
        report_date: values.report_date ? values.report_date.format('YYYY-MM-DD') : undefined,
        standard_document_ids: values.standard_document_ids,
        standard_item_ids: values.sop_ids,
      })
      message.success(`任务创建成功，已收录 ${values.sop_ids.length} 个检验项目`)
      setCreateOpen(false)
      setPage(1)
      load(1)
    } catch (err: any) {
      message.error(err.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleStatus = async (id: string, status: TestTaskStatus, tip: string) => {
    try {
      await updateTestTaskStatus(id, status)
      message.success(tip)
      load(page)
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteTestTask(id)
      message.success('已删除')
      load(page)
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const columns = [
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', width: 160, ellipsis: true },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 120 },
    { title: '生产日期', dataIndex: 'production_date', key: 'production_date', width: 110, render: (v: string | null) => v || '-' },
    {
      title: '出报日期', key: 'report_date', width: 150,
      render: (_: any, r: TestTaskListItem) => (
        <DatePicker
          size="small"
          style={{ width: '100%' }}
          value={r.report_date ? dayjs(r.report_date) : null}
          disabled={r.status === 'void' || !canFill}
          placeholder="补录"
          onChange={async (d) => {
            try {
              await updateTestTaskReportDate(r.id, d ? d.format('YYYY-MM-DD') : null)
              message.success(d ? '出报日期已更新' : '出报日期已清空')
              load(page)
            } catch (err: any) {
              message.error(err.message || '更新出报日期失败')
            }
          }}
        />
      ),
    },
    { title: '效期', dataIndex: 'expiry_date', key: 'expiry_date', width: 110, render: (v: string | null) => v || '-' },
    { title: 'COA表格编号', dataIndex: 'form_id', key: 'form_id', width: 150, render: (v: string | null) => v || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: TestTaskStatus) => <Tag color={STATUS_META[v].color}>{STATUS_META[v].label}</Tag>,
    },
    {
      title: '进度', key: 'progress', width: 150,
      render: (_: any, r: TestTaskListItem) => (
        <Progress
          percent={r.results_total ? Math.round(r.results_filled / r.results_total * 100) : 0}
          size="small"
          format={() => `${r.results_filled}/${r.results_total}`}
        />
      ),
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160,
      render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_: any, r: TestTaskListItem) => (
        <Space>
          <Button size="small" type={r.status === 'in_progress' ? 'primary' : 'default'} icon={<FormOutlined />}
            onClick={() => router.push(`/quality/task/${r.id}`)}>
            {r.status === 'in_progress' ? '填报' : '查看'}
          </Button>
          {canReview && r.status !== 'void' && (
            <Button size="small" icon={<StopOutlined />}
              onClick={() => handleStatus(r.id, 'void', '任务已作废')}>
              作废
            </Button>
          )}
          {canReview && (
            <Button size="small" danger icon={<DeleteOutlined />}
              onClick={() => handleDelete(r.id)} />
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input placeholder="产品名称" allowClear value={productSearch}
          onChange={e => setProductSearch(e.target.value)}
          onPressEnter={() => { setPage(1); load(1) }}
          style={{ width: 180 }} prefix={<SearchOutlined />} />
        <Select
          placeholder="状态筛选" allowClear
          style={{ width: 140 }}
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1) }}
          options={(Object.keys(STATUS_META) as TestTaskStatus[]).map((s) => ({ label: STATUS_META[s].label, value: s }))}
        />
        <Button type="primary" onClick={() => { setPage(1); load(1) }}>搜索</Button>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>新建检验任务</Button>
        )}
      </Space>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => setPage(p) }}
        size="small"
        scroll={{ x: 1100 }}
      />

      <Modal
        title="新建检验任务（产品 → 批号 → 标准文件 → 检验项目）"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="创建"
        confirmLoading={creating}
        width={560}
      >
        <Form form={createForm} layout="vertical" className="mt-4">
          <Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '请选择产品' }]}>
            <Select
              showSearch
              placeholder="选择产品（需已在产品标准中导入）"
              options={productOptions}
              onChange={handleProductChange}
            />
          </Form.Item>
          <Form.Item
            name="batch_number"
            label="批号（自动识别产品代号）"
            validateTrigger="onBlur"
            rules={[
              { required: true, message: '请输入批号' },
              {
                // 直接按当前表单值与最新文档列表计算，不读渲染闭包，避免旧校验结果残留
                validator: (_: unknown, value: string | undefined) => {
                  if (!value) return Promise.resolve()
                  const product = createForm.getFieldValue('product_name') as string | undefined
                  if (!product) return Promise.resolve()
                  const codes = productDocsRef.current
                    .filter((d) => nameKey(d.product_name) === nameKey(product) && d.product_code?.trim())
                    .map((d) => d.product_code!.trim().toUpperCase())
                    .sort((a, b) => b.length - a.length)
                  if (!codes.length) {
                    return Promise.reject(new Error('该产品标准未配置产品代号，请先在产品标准中补充'))
                  }
                  const b = value.trim().toUpperCase()
                  return codes.some((c) => b.startsWith(c))
                    ? Promise.resolve()
                    : Promise.reject(new Error(`批号开头未匹配到产品代号（该产品代号：${codes.join(' / ')}）`))
                },
              },
            ]}
          >
            <Input
              placeholder={watchedProduct ? '如 HAF2608001B（开头字母为产品代号）' : '请先选择产品名称'}
              disabled={!watchedProduct}
            />
          </Form.Item>
          <Form.Item name="standard_document_ids" label="标准文件（可多选，一个批号可开多份报告单）" rules={[{ required: true, message: '请选择标准文件' }]}>
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              placeholder={matchedCode ? '勾选本批要开具报告单的标准文件（如 SOP.02.3205.010）' : '请先填写批号（自动识别产品代号）'}
              options={docOptions}
              disabled={!matchedCode}
            />
          </Form.Item>
          <Form.Item name="sop_ids" label="检验项目（勾选本批要做的，默认全选）" rules={[{ required: true, message: '请选择检验项目' }]}>
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              placeholder={matchedDocIds?.length ? '选择本批要做的检验项目' : '请先选择标准文件'}
              options={sopOptions}
              disabled={!matchedDocIds?.length}
              loading={sopLoading}
            />
          </Form.Item>
          <Form.Item name="specification" label="规格（本批）" rules={[{ required: true, message: '请选择规格' }]}>
            <Select
              placeholder={matchedDocIds?.length ? '选择本批规格' : '先选择标准文件'}
              options={specOptions.map((s) => ({ label: s, value: s }))}
              disabled={!matchedDocIds?.length}
            />
          </Form.Item>
          <Form.Item name="production_date" label="生产日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="report_date" label="出报日期（可选，后续可在列表中补录）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
