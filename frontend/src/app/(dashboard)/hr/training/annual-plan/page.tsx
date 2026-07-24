'use client'

import { Suspense, useEffect, useState, useMemo } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { App, Card, Row, Col, Select, Input, Upload, Button, Space, Spin, Table, Popconfirm, Modal, Form, DatePicker, InputNumber } from 'antd'
import { UploadOutlined, SearchOutlined, ReloadOutlined, DeleteOutlined, ArrowLeftOutlined, BellOutlined, PlusOutlined } from '@ant-design/icons'
import { logError } from '@/lib/hr'

const API_BASE = ''

// ─── 列表视图：按部门卡片 ───
function PlanListView({ year, keyword, onYearChange, onKeywordChange, onReload }: {
  year: number; keyword: string
  onYearChange: (y: number) => void; onKeywordChange: (k: string) => void; onReload: () => void
}) {
  const { message } = App.useApp()
  const router = useRouter()
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const sp = new URLSearchParams()
      if (year) sp.set('year', String(year))
      if (keyword) sp.set('keyword', keyword)
      const res = await fetch(`${API_BASE}/api/v1/hr/annual-plan-items?${sp}`, { credentials: 'include' })
      const d = await res.json()
      setData(d.data || [])
    } catch (err: any) {
      logError('加载年度计划列表失败', { error: err.message })
      message.error('加载失败: ' + (err.message || '未知错误'))
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [year])

  // 按部门+plan_id 分组
  const plans = useMemo(() => {
    const map: Record<string, { dept: string; planId: string; count: number; year: number }> = {}
    for (const item of data) {
      const key = item.plan_id
      if (!map[key]) map[key] = { dept: item.department, planId: item.plan_id, count: 0, year: item.year }
      map[key].count++
    }
    return Object.values(map).sort((a, b) => a.dept.localeCompare(b.dept, 'zh'))
  }, [data])

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">年度培训计划</h1>
          <p className="text-[14px] text-[var(--color-steel)]">按部门管理年度培训计划，支持上传与编辑</p>
        </div>
        <Space>
          <span suppressHydrationWarning>
            <Upload accept=".xlsx,.xls" showUploadList={false} customRequest={async ({ file }) => {
              const fd = new FormData(); fd.append('file', file as File)
              try {
                const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/upload`, {
                  method: 'POST', body: fd, credentials: 'include',
                })
                const d = await res.json()
                if (res.ok) { message.success(d.message); onReload() }
                else message.error(d.message || '上传失败')
              } catch { message.error('上传失败') }
            }}>
              <Button icon={<UploadOutlined />}>上传计划明细</Button>
            </Upload>
          </span>
          <Button icon={<ReloadOutlined />} onClick={onReload}>刷新</Button>
        </Space>
      </div>

      <div className="flex gap-3 items-center">
        <Select value={year} onChange={onYearChange} style={{ width: 100 }}
          options={[2024, 2025, 2026, 2027, 2028].map(y => ({ label: `${y}年`, value: y }))} />
        <Input prefix={<SearchOutlined />} placeholder="搜索培训内容" value={keyword}
          onChange={e => onKeywordChange(e.target.value)} onPressEnter={onReload} style={{ width: 250 }} allowClear />
        <span className="text-gray-400 text-sm">共 {plans.length} 个部门计划</span>
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><Spin size="large" /></div>
      ) : plans.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <p>{year}年暂无年度培训计划</p>
          <p className="text-sm mt-2">点击上方按钮上传 Excel 导入</p>
        </div>
      ) : (
        <Row gutter={[16, 16]}>
          {plans.map((plan) => (
            <Col xs={24} sm={12} lg={8} key={plan.planId}>
              <Card hoverable className="h-full"
                onClick={() => router.push(`/hr/training/annual-plan?id=${plan.planId}`)}>
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-500 text-lg font-bold shrink-0">
                    {plan.dept.charAt(0)}
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-[16px] font-semibold text-[var(--color-charcoal)] mb-1 truncate">{plan.dept}</h3>
                    <p className="text-[14px] text-[var(--color-steel)]">{plan.year} 年度 · {plan.count} 条培训计划</p>
                  </div>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}

// ─── 明细视图：某个部门的计划明细 ───
function PlanDetailView({ planId }: { planId: string }) {
  const { message } = App.useApp()
  const router = useRouter()
  const [items, setItems] = useState<any[]>([])
  const [planInfo, setPlanInfo] = useState<{ dept: string; year: number } | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${planId}/items`, { credentials: 'include' })
      const d = await res.json()
      setItems(d.data || [])

      const sp = new URLSearchParams({ page_size: '200' })
      const planRes = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans?${sp}`, { credentials: 'include' })
      const plans = await planRes.json()
      const plan = (plans.data || []).find((p: any) => p.id === planId)
      if (plan) setPlanInfo({ dept: plan.department, year: plan.year })
    } catch (err: any) {
      logError('加载计划明细失败', { planId, error: err.message })
      message.error('加载失败: ' + (err.message || '未知错误'))
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [planId])

  const handleDelete = async (itemId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${planId}/items/${itemId}`, {
        method: 'DELETE', credentials: 'include',
      })
      if (res.ok) { message.success('已删除'); load() }
      else message.error('删除失败')
    } catch { message.error('删除失败') }
  }

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [creating, setCreating] = useState(false)
  const [deptOptions, setDeptOptions] = useState<{value:string,label:string}[]>([])
  const [trainerOptions, setTrainerOptions] = useState<{value:string,label:string}[]>([])

  // 加载部门选项和培训师选项
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/departments`, { credentials: 'include' })
      .then(r => r.json()).then(d => setDeptOptions((d.data||[]).map((v:string)=>({value:v,label:v}))))
    fetch(`${API_BASE}/api/v1/hr/trainers?page_size=200`, { credentials: 'include' })
      .then(r => r.json()).then(d => setTrainerOptions((d.data||[]).map((t:any)=>({value:t.name,label:`${t.name}(${t.department})`}))))
  }, [])

  const handleCreate = async () => {
    const vals = await createForm.validateFields()
    setCreating(true)
    try {
      const payload: Record<string, any> = {}
      for (const [k, v] of Object.entries(vals)) {
        if (v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)) continue
        if (k === 'confirm_date') payload[k] = (v as any).format('YYYY-MM-DD')
        else if (k === 'month') payload[k] = (v as any).format('YYYY-MM')
        else if (k === 'target_audience') payload[k] = (v as string[]).join('，')
        else payload[k] = v
      }
      const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${planId}/items`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), credentials: 'include',
      })
      if (res.ok) {
        message.success('创建成功')
        setCreateOpen(false)
        createForm.resetFields()
        load()
      } else {
        const d = await res.json()
        message.error(d.message || '创建失败')
      }
    } catch { message.error('创建失败') }
    finally { setCreating(false) }
  }

  const dept = planInfo?.dept || ''

  const goToNotification = (record: any) => {
    const params = new URLSearchParams()
    const set = (k: string, v: any) => { if (v) params.set(k, encodeURIComponent(String(v))) }
    set('dept', dept)
    set('subject', record.content_and_textbook)
    set('method', record.training_method)
    set('assessment', record.assessment_method)
    set('location', record.location)
    set('trainer', record.position_and_count)
    set('confirm_date', record.confirm_date)
    router.push(`/hr/training/notification?${params.toString()}`)
  }

  const columns = [
    { title: '月份', dataIndex: 'month', width: 55 },
    { title: '培训内容', dataIndex: 'content_and_textbook', width: 200, ellipsis: true },
    { title: '培训对象', dataIndex: 'target_audience', width: 90 },
    { title: '培训师', dataIndex: 'position_and_count', width: 110, ellipsis: true },
    { title: '培训方式', dataIndex: 'training_method', width: 70 },
    { title: '考核方式', dataIndex: 'assessment_method', width: 70 },
    { title: '培训地点', dataIndex: 'location', width: 100, ellipsis: true },
    { title: '课时', dataIndex: 'duration_hours', width: 50 },
    { title: '实施日期', dataIndex: 'confirm_date', width: 95 },
    { title: '注意事项', dataIndex: 'notes', width: 100, ellipsis: true },
    { title: '备注', dataIndex: 'remarks', width: 80, ellipsis: true },
    {
      title: '操作', width: 130, fixed: 'right' as const,
      render: (_: any, record: any) => (
        <Space size="small">
          <Button type="link" size="small" icon={<BellOutlined />}
            onClick={() => goToNotification(record)}>通知</Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push('/hr/training/annual-plan')}
          className="mb-2 pl-0">返回计划列表</Button>
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
              {planInfo ? `${planInfo.dept} · ${planInfo.year}年度培训计划` : '年度培训计划'}
            </h1>
            <p className="text-[14px] text-[var(--color-steel)]">共 {items.length} 条明细</p>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建计划</Button>
        </div>
      </div>

      <Table
        dataSource={items}
        rowKey="id"
        loading={loading}
        size="small"
        scroll={{ x: 1050 }}
        pagination={false}
        columns={columns}
      />

      <Modal
        title="新建培训计划"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields() }}
        onOk={handleCreate}
        confirmLoading={creating}
        okText="创建"
        width={600}
      >
        <Form form={createForm} layout="vertical" className="mt-4">
          <div className="grid grid-cols-2 gap-x-4">
            <Form.Item name="month" label="月份"><DatePicker picker="month" className="w-full" /></Form.Item>
            <Form.Item name="duration_hours" label="课时"><InputNumber min={0} step={0.5} className="w-full" /></Form.Item>
            <Form.Item name="training_method" label="培训方式">
              <Select options={['面授','自学','面授+自学','自学+面授'].map(v=>({value:v,label:v}))} allowClear />
            </Form.Item>
            <Form.Item name="assessment_method" label="考核方式">
              <Select options={['笔试','问答','笔试+问答'].map(v=>({value:v,label:v}))} allowClear />
            </Form.Item>
          </div>
          <Form.Item name="content_and_textbook" label="培训内容"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="target_audience" label="培训对象">
            <Select mode="multiple" placeholder="选择部门" options={deptOptions} showSearch
              filterOption={(i,o) => (o?.label??'').includes(i)} />
          </Form.Item>
          <Form.Item name="position_and_count" label="培训师">
            <Select placeholder="选择培训师" options={trainerOptions} showSearch allowClear
              filterOption={(i,o) => (o?.label??'').includes(i)} />
          </Form.Item>
          <div className="grid grid-cols-2 gap-x-4">
            <Form.Item name="location" label="培训地点"><Input /></Form.Item>
            <Form.Item name="confirm_date" label="实施日期"><DatePicker className="w-full" /></Form.Item>
          </div>
          <Form.Item name="notes" label="注意事项"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="remarks" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ─── 路由入口 ───
function AnnualPlanContent() {
  const searchParams = useSearchParams()
  const planId = searchParams.get('id')
  const [year, setYear] = useState(2026)
  const [keyword, setKeyword] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  if (planId) {
    return <PlanDetailView planId={planId} />
  }

  return (
    <PlanListView
      year={year} keyword={keyword}
      onYearChange={(y) => { setYear(y); setReloadKey(k => k + 1) }}
      onKeywordChange={setKeyword}
      onReload={() => setReloadKey(k => k + 1)}
    />
  )
}

export default function AnnualPlanPage() {
  return (
    <Suspense fallback={<div className="flex justify-center py-20"><Spin size="large" /></div>}>
      <AnnualPlanContent />
    </Suspense>
  )
}
