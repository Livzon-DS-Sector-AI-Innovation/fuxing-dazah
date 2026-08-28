'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Card, DatePicker, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, TimePicker } from 'antd'
import { usePermission } from '@/hooks/usePermission'
import { DownloadOutlined, PlusOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'

import {
  fetchSopTrainingRecords, fetchSopRecordYears, createSopTrainingRecord,
  updateSopTrainingRecord, deleteSopTrainingRecord, exportSopTrainingRecords,
  submitSopTrainingRecord, fetchDepartmentsAction, fetchSopDeptTrainers,
  downloadSopMasterMaterials,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import type { SopTrainingRecord } from '@/types/hr'

const COLOR_MAP: Record<string, { tag: string; bg: string }> = {
  新增: { tag: 'gold', bg: '#FFFBE6' },
  撤销: { tag: 'default', bg: '#F5F5F5' },
  修改: { tag: 'red', bg: '#FFF1F0' },
}

export default function SopMasterClient() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canGenerateDoc = hasPermission('hr:training:document')
  const [years, setYears] = useState<string[]>([])
  const [year, setYear] = useState<string>(String(new Date().getFullYear()))
  const [color, setColor] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [data, setData] = useState<SopTrainingRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [generating, setGenerating] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<SopTrainingRecord | null>(null)
  const [form] = Form.useForm()
  const [deptOptions, setDeptOptions] = useState<{ label: string; value: string }[]>([])
  const [deptTrainers, setDeptTrainers] = useState<{ department: string; trainer: string | null }[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchSopTrainingRecords({ year, color, keyword: keyword || undefined })
      setData(res.data || [])
    } catch (e: any) {
      message.error(e.message || '加载失败')
    } finally { setLoading(false) }
  }, [year, color, keyword, message])

  useEffect(() => {
    load()
    fetchSopRecordYears().then((r) => {
      const ys = r.data || []
      setYears(ys)
      if (ys.length && !ys.includes(year)) setYear(ys[0])
    }).catch(() => {})
    fetchDepartmentsAction({ page_size: 100 }).then((r) =>
      setDeptOptions((r.data || []).map((d: any) => ({ label: d.name || d.department_name, value: d.name || d.department_name })))
    ).catch(() => {})
  }, [load, year])

  const loadDeptTrainers = useCallback(async (depts: string[]) => {
    if (!depts?.length) {
      setDeptTrainers([])
      return
    }
    try {
      const res = await fetchSopDeptTrainers(depts)
      setDeptTrainers(res.data || [])
    } catch { setDeptTrainers([]) }
  }, [])

  const openCreate = () => {
    setEditing(null)
    setDeptTrainers([])
    form.resetFields()
    form.setFieldsValue({
      year: year || String(new Date().getFullYear()),
      method: 'R', color: '新增',
      involved_departments: [],
    })
    setModalOpen(true)
  }

  const openEdit = (r: SopTrainingRecord) => {
    setEditing(r)
    form.setFieldsValue({
      year: r.year,
      training_date: r.training_date ? dayjs(r.training_date) : null,
      file_name: r.file_name,
      file_no: r.file_no,
      effective_date: r.effective_date ? dayjs(r.effective_date) : null,
      method: r.method,
      complete_date: null,
      complete_range: null,
      trainer: r.trainer, trainees: r.trainees,
      involved_departments: r.involved_departments, change_note: r.change_note,
      color: r.color, initiator_department: r.initiator_department,
    })
    // 回显完成时间/课时（如 2026.01.05(14:00-15:00)）
    if (r.complete_time) {
      const m = r.complete_time.match(/^(\d{4})\.(\d{2})\.(\d{2})(\((\d{2}:\d{2})-(\d{2}:\d{2})\))?$/)
      if (m) {
        form.setFieldsValue({
          complete_date: dayjs(`${m[1]}-${m[2]}-${m[3]}`),
          complete_range: m[4] ? [dayjs(m[5], 'HH:mm'), dayjs(m[6], 'HH:mm')] : null,
        })
      }
    }
    loadDeptTrainers(r.involved_departments || [])
    setModalOpen(true)
  }

  const handleSave = async () => {
    const v = await form.validateFields()
    const date = v.complete_date as Dayjs | null
    const range = v.complete_range as [Dayjs, Dayjs] | null
    const complete_time = date
      ? `${date.format('YYYY.MM.DD')}${range && range[0] && range[1] ? `(${range[0].format('HH:mm')}-${range[1].format('HH:mm')})` : ''}`
      : (range && range[0] && range[1] ? `(${range[0].format('HH:mm')}-${range[1].format('HH:mm')})` : null)
    const payload = {
      ...v,
      training_date: v.training_date ? (v.training_date as Dayjs).format('YYYY-MM-DD') : null,
      effective_date: v.effective_date ? (v.effective_date as Dayjs).format('YYYY-MM-DD') : null,
      complete_time,
      complete_date: undefined,
      complete_range: undefined,
    }
    try {
      if (editing) {
        await updateSopTrainingRecord(editing.id, payload)
        message.success('已更新')
      } else {
        await createSopTrainingRecord(payload)
        message.success('已保存草稿，点「提交/通知」后生成二级表并通知培训管理员')
      }
      setModalOpen(false)
      load()
    } catch (e: any) { message.error(e.message || '保存失败') }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteSopTrainingRecord(id)
      message.success('已删除')
      load()
    } catch (e: any) { message.error(e.message || '删除失败') }
  }

  const handleSubmit = async (r: SopTrainingRecord) => {
    setSubmitting(r.id)
    try {
      const res = await submitSopTrainingRecord(r.id)
      message.success(res.message || '已提交')
      load()
    } catch (e: any) { message.error(e.message || '提交失败') }
    finally { setSubmitting(null) }
  }

  const handleGenerateMaterials = async (r: SopTrainingRecord) => {
    setGenerating(r.id)
    try {
      const { base64, filename } = await downloadSopMasterMaterials(r.id)
      downloadBase64File(base64, filename || 'SOP全套培训材料.zip')
      message.success('全套材料已生成')
    } catch (e: any) { message.error(e.message || '生成失败') }
    finally { setGenerating(null) }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const { base64, filename } = await exportSopTrainingRecords(year)
      downloadBase64File(base64, filename)
      message.success('登记表已导出')
    } catch (e: any) { message.error(e.message || '导出失败') }
    finally { setExporting(false) }
  }

  const fmtShortDate = (v: string | null) => {
    if (!v) return '——'
    const s = v.replaceAll('-', '.')
    return s.length >= 8 ? s.slice(5) : s  // 月.日
  }
  const fmtFullDate = (v: string | null) => v ? v.replaceAll('-', '.') : '——'

  const columns = [
    { title: '培训日期', dataIndex: 'training_date', width: 90, render: fmtShortDate },
    { title: '文件名称', dataIndex: 'file_name', width: 240, ellipsis: true },
    { title: '文件编号', dataIndex: 'file_no', width: 140, render: (v: string | null) => v || '——' },
    { title: '生效日期', dataIndex: 'effective_date', width: 100, render: fmtFullDate },
    { title: '培训方式', dataIndex: 'method', width: 80, render: (v: string | null) => v || '-' },
    { title: '完成时间/课时', dataIndex: 'complete_time', width: 150, render: (v: string | null) => v || '——' },
    { title: '培训师', dataIndex: 'trainer', width: 90, render: (v: string | null) => v || '——' },
    { title: '培训对象', dataIndex: 'trainees', width: 190, ellipsis: true },
    {
      title: '培训涉及部门', dataIndex: 'involved_departments', width: 170,
      render: (depts: string[]) => depts?.length ? depts.join(' / ') : '-',
    },
    { title: '变更内容', dataIndex: 'change_note', width: 150, ellipsis: true },
    {
      title: '状态', dataIndex: 'color', width: 70, fixed: 'right' as const,
      render: (c: string) => <Tag color={COLOR_MAP[c]?.tag}>{c}</Tag>,
    },
    {
      title: '进度', dataIndex: 'status', width: 80, fixed: 'right' as const,
      render: (s: string) => <Tag color={s === '已提交' ? 'blue' : 'default'}>{s === '已提交' ? '已提交' : '草稿'}</Tag>,
    },
    {
      title: '操作', width: 260, fixed: 'right' as const, render: (_: any, r: SopTrainingRecord) => (
        <Space size={4}>
          {r.status !== '已提交' && (
            <Button type="text" size="small" icon={<SendOutlined />}
              loading={submitting === r.id}
              onClick={() => handleSubmit(r)}>提交/通知</Button>
          )}
          {canGenerateDoc && (
            <Button type="text" size="small" icon={<DownloadOutlined />}
              loading={generating === r.id}
              onClick={() => handleGenerateMaterials(r)}>全套材料</Button>
          )}
          <Button type="text" size="small" onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除该登记？未转训的二级表记录将一并删除" onConfirm={() => handleDelete(r.id)}>
            <Button type="text" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-[22px] font-semibold">SOP培训文件登记表</h1>
          <p className="text-[13px] text-[var(--color-steel)]">
            每年一张登记表；提交后自动生成各部门二级表并通知培训管理员
          </p>
        </div>
        <Space>
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>导出登记表</Button>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增登记</Button>
        </Space>
      </div>
      <Card>
        <Space className="mb-3" wrap>
          <Select style={{ width: 120 }} value={year} onChange={(v) => setYear(v)}
            options={years.map((y) => ({ label: `${y}年`, value: y }))} placeholder="年份" />
          <Select allowClear style={{ width: 110 }} placeholder="颜色状态" value={color} onChange={(v) => setColor(v)}
            options={[{ label: '新增', value: '新增' }, { label: '撤销', value: '撤销' }, { label: '修改', value: '修改' }]} />
          <Input.Search allowClear style={{ width: 240 }} placeholder="文件名称/编号"
            onSearch={(v) => setKeyword(v)} onChange={(e) => { if (!e.target.value) setKeyword('') }} />
          <span className="text-[12px] text-[var(--color-stone)]">图例：🟨新增　⬜撤销　🟥修改</span>
        </Space>
        <Table rowKey="id" columns={columns} dataSource={data} loading={loading} size="small"
          scroll={{ x: 1600 }} pagination={{ pageSize: 20 }}
          onRow={(r) => ({ style: { background: COLOR_MAP[r.color]?.bg } })} />
      </Card>
      <Modal title={editing ? '编辑登记' : '新增培训文件登记'} open={modalOpen}
        onCancel={() => setModalOpen(false)} onOk={handleSave} width={640}>
        <Form form={form} layout="vertical" className="mt-2">
          <div className="grid grid-cols-3 gap-3">
            <Form.Item name="year" label="年份" rules={[{ required: true, message: '请填写年份' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="training_date" label="培训日期">
              <DatePicker className="w-full" format="YYYY-MM-DD" />
            </Form.Item>
            <Form.Item name="method" label="培训方式（R/T）">
              <Select options={[{ label: 'R', value: 'R' }, { label: 'T', value: 'T' }]} />
            </Form.Item>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Form.Item name="file_name" label="文件名称" rules={[{ required: true, message: '请填写文件名称' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="file_no" label="文件编号">
              <Input />
            </Form.Item>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Form.Item name="effective_date" label="生效日期">
              <DatePicker className="w-full" format="YYYY-MM-DD" />
            </Form.Item>
            <Form.Item name="complete_date" label="完成时间/课时（日期）">
              <DatePicker className="w-full" format="YYYY-MM-DD" />
            </Form.Item>
            <Form.Item name="complete_range" label="时间段（可选）">
              <TimePicker.RangePicker className="w-full" format="HH:mm" minuteStep={5} />
            </Form.Item>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Form.Item name="trainer" label="培训师">
              <Input />
            </Form.Item>
            <Form.Item name="initiator_department" label="发起部门（主办部门）">
              <Select showSearch allowClear options={deptOptions}
                onChange={(v: string) => {
                  // 培训对象为空时自动生成「X部门全体员工及相关部门培训师」
                  if (!form.getFieldValue('trainees')) {
                    form.setFieldsValue({ trainees: v ? `「${v}」全体员工及相关部门培训师` : '' })
                  }
                }}
                filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
            </Form.Item>
            <Form.Item name="color" label="颜色状态">
              <Select options={[{ label: '新增', value: '新增' }, { label: '撤销', value: '撤销' }, { label: '修改', value: '修改' }]} />
            </Form.Item>
          </div>
          <Form.Item name="involved_departments" label="培训涉及部门（提交后自动生成各部二级表）" rules={[{ required: true, message: '请选择涉及部门' }]}>
            <Select mode="multiple" showSearch options={deptOptions}
              onChange={(vals: string[]) => loadDeptTrainers(vals || [])}
              filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          {deptTrainers.length > 0 && (
            <div className="mb-3 -mt-1 rounded-[var(--rounded-sm)] bg-[var(--color-surface)] p-3">
              <div className="text-[12px] text-[var(--color-stone)] mb-1">已自动关联的一级培训师（被培训人员）</div>
              <div className="flex flex-wrap gap-2">
                {deptTrainers.map((t) => (
                  <Tag key={t.department} color="blue">{t.department}：{t.trainer || '未配置'}</Tag>
                ))}
              </div>
            </div>
          )}
          <Form.Item name="trainees" label="培训对象" tooltip="留空自动生成「X部门全体员工及相关部门培训师」">
            <Input />
          </Form.Item>
          <Form.Item name="change_note" label="变更内容">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
