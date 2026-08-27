'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Tooltip } from 'antd'
import { DownloadOutlined, FileZipOutlined, ReloadOutlined, SendOutlined, TagsOutlined } from '@ant-design/icons'

import {
  fetchSopTrainingEntries, transferSopTrainingEntry, batchTransferSopEntries,
  generateSopTrainingMaterials, updateSopTrainingEntry,
  fetchSopClassifications, fetchSopPersonnel, exportSopTrainingEntries,
  fetchSopTrainingRecords, fetchDepartmentsAction,
} from '@/actions/hr'
import { usePermission } from '@/hooks/usePermission'
import { downloadBase64File } from '@/lib/hr'
import type { SopTrainingEntry, SopPersonnelOption } from '@/types/hr'

export default function SopEntryClient() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:training:manage')
  const canGenerateDoc = hasPermission('hr:training:document')

  const [data, setData] = useState<SopTrainingEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [recordId, setRecordId] = useState<string | undefined>()
  const [dept, setDept] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [deptOptions, setDeptOptions] = useState<{ label: string; value: string }[]>([])
  const [recordOptions, setRecordOptions] = useState<{ label: string; value: string }[]>([])
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])
  const [transferring, setTransferring] = useState(false)
  const [generating, setGenerating] = useState(false)

  // 分类人员弹窗
  const [modalOpen, setModalOpen] = useState(false)
  const [current, setCurrent] = useState<SopTrainingEntry | null>(null)
  const [form] = Form.useForm()
  const [classOptions, setClassOptions] = useState<{ label: string; value: string }[]>([])
  const [personnelOptions, setPersonnelOptions] = useState<SopPersonnelOption[]>([])
  const [personnelLoading, setPersonnelLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchSopTrainingEntries({ record_id: recordId, department: dept, status })
      setData(res.data || [])
    } catch (e: any) {
      message.error(e.message || '加载失败')
    } finally { setLoading(false) }
  }, [recordId, dept, status, message])

  useEffect(() => {
    load()
    fetchDepartmentsAction({ page_size: 100 }).then((r) =>
      setDeptOptions((r.data || []).map((d: any) => ({ label: d.name || d.department_name, value: d.name || d.department_name })))
    ).catch(() => {})
    // 登记记录选项（用于筛选）
    fetchSopTrainingRecords({}).then((r) =>
      setRecordOptions((r.data || []).map((x) => ({ label: `${x.file_name}（${x.file_no || x.year}）`, value: x.id })))
    ).catch(() => {})
  }, [load])

  const handleBatchTransfer = async () => {
    if (!selectedKeys.length) { message.warning('请先勾选要转训的记录'); return }
    setTransferring(true)
    try {
      const res = await batchTransferSopEntries(selectedKeys.map(String))
      message.success(res.message || '批量转培训完成')
      setSelectedKeys([])
      load()
    } catch (e: any) { message.error(e.message || '批量转培训失败') }
    finally { setTransferring(false) }
  }

  const handleBatchMaterials = async () => {
    if (!selectedKeys.length) { message.warning('请先勾选记录（多条SOP合并生成一套材料）'); return }
    setGenerating(true)
    try {
      const { base64, filename } = await generateSopTrainingMaterials(selectedKeys.map(String))
      downloadBase64File(base64, filename)
      message.success('一套培训材料已生成（每部门一份通知+签到表）')
    } catch (e: any) { message.error(e.message || '生成失败') }
    finally { setGenerating(false) }
  }

  const handleTransfer = async (e: SopTrainingEntry) => {
    setTransferring(true)
    try {
      const res = await transferSopTrainingEntry(e.id)
      message.success(res.data?.trainer ? `已转培训，培训师：${res.data.trainer}` : '已转培训')
      load()
    } catch (err: any) { message.error(err.message || '转培训失败') }
    finally { setTransferring(false) }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const { base64, filename } = await exportSopTrainingEntries({ record_id: recordId, department: dept, status })
      downloadBase64File(base64, filename)
      message.success('培训清单已导出')
    } catch (e: any) { message.error(e.message || '导出失败') }
    finally { setExporting(false) }
  }

  const openPersonnelModal = async (e: SopTrainingEntry) => {
    setCurrent(e)
    form.setFieldsValue({
      classification: e.classification || undefined,
      personnel: (e.personnel || []).map((p) => p.employee_number),
      complete_time: e.complete_time || undefined,
    })
    setPersonnelOptions([])
    setModalOpen(true)
    try {
      const cls = await fetchSopClassifications(e.department)
      setClassOptions((cls.data || []).map((c) => ({ label: `${c.tag_name}（${c.count}人）`, value: c.tag_name })))
    } catch { setClassOptions([]) }
    if (e.classification) {
      await loadPersonnel(e.department, e.classification)
    }
  }

  const loadPersonnel = async (department: string, classification: string) => {
    setPersonnelLoading(true)
    try {
      const res = await fetchSopPersonnel(department, classification)
      setPersonnelOptions(res.data || [])
      // 默认全选分类下人员，可自由调整
      form.setFieldsValue({ personnel: (res.data || []).map((p) => p.employee_number) })
    } catch (err: any) {
      message.error(err.message || '获取分类人员失败')
    } finally { setPersonnelLoading(false) }
  }

  const handleClassificationChange = (value: string | undefined) => {
    form.setFieldsValue({ personnel: [] })
    setPersonnelOptions([])
    if (value && current) {
      loadPersonnel(current.department, value)
    }
  }

  const handleSavePersonnel = async () => {
    if (!current) return
    const v = await form.validateFields()
    const selected = (v.personnel || []) as string[]
    const personnel = selected
      .map((en) => personnelOptions.find((p) => p.employee_number === en))
      .filter(Boolean)
      .map((p) => ({ employee_number: p!.employee_number, name: p!.name }))
    try {
      await updateSopTrainingEntry(current.id, {
        classification: v.classification,
        personnel,
        complete_time: v.complete_time || undefined,
      })
      message.success('已保存')
      setModalOpen(false)
      load()
    } catch (e: any) { message.error(e.message || '保存失败') }
  }

  const columns = useMemo(() => [
    { title: '部门', dataIndex: 'department', width: 120 },
    { title: '文件名称', dataIndex: 'file_name', width: 220, ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '文件编号', dataIndex: 'file_no', width: 130, render: (v: string | null) => v || '——' },
    { title: '培训方式', dataIndex: 'method', width: 70, render: (v: string | null) => v || '-' },
    { title: '培训师', dataIndex: 'trainer', width: 90, render: (v: string | null) => v || '待转训' },
    { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => (
      <Tag color={s === '已转训' ? 'green' : 'orange'}>{s}</Tag>
    ) },
    { title: '完成时间/课时', dataIndex: 'complete_time', width: 140, render: (v: string | null) => v || '——' },
    { title: '自定义分类', dataIndex: 'classification', width: 100, render: (v: string | null) => v || '-' },
    {
      title: '分类人员', dataIndex: 'personnel', render: (p: SopPersonnelOption[]) => (
        p?.length ? (
          <Tooltip title={(p || []).map((x) => x.name).join('、')}>
            <span className="text-[var(--color-steel)]">{p.map((x) => x.name).slice(0, 3).join('、')}{p.length > 3 ? ` 等${p.length}人` : ''}</span>
          </Tooltip>
        ) : '-'
      ),
    },
    {
      title: '操作', width: 150, render: (_: any, r: SopTrainingEntry) => (
        canManage ? (
          <Space size={4}>
            {r.status !== '已转训' && (
              <Button type="text" size="small" icon={<SendOutlined />}
                loading={transferring} onClick={() => handleTransfer(r)}>转培训</Button>
            )}
            <Button type="text" size="small" icon={<TagsOutlined />} onClick={() => openPersonnelModal(r)}>分类人员</Button>
          </Space>
        ) : '-'
      ),
    },
  ], [transferring, canManage])

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-[22px] font-semibold">SOP培训二级表</h1>
          <p className="text-[13px] text-[var(--color-steel)]">
            登记提交后按涉及部门自动生成；勾选多条可一起转训、合并生成一套材料
          </p>
        </div>
        <Space>
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>导出培训清单</Button>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </div>
      <Card>
        <Space className="mb-3" wrap>
          <Select allowClear showSearch style={{ width: 260 }} placeholder="按登记文件筛选"
            options={recordOptions} value={recordId} onChange={(v) => setRecordId(v)}
            filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
          <Select allowClear showSearch style={{ width: 200 }} placeholder="按部门筛选"
            options={deptOptions} value={dept} onChange={(v) => setDept(v)}
            filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
          <Select allowClear style={{ width: 130 }} placeholder="按状态筛选" value={status} onChange={(v) => setStatus(v)}
            options={[{ label: '待转训', value: '待转训' }, { label: '已转训', value: '已转训' }]} />
          {canManage && (
            <Button icon={<SendOutlined />} loading={transferring}
              onClick={handleBatchTransfer}>批量转培训</Button>
          )}
          {canGenerateDoc && (
            <Button type="primary" icon={<FileZipOutlined />} loading={generating}
              onClick={handleBatchMaterials}>生成一套材料</Button>
          )}
          {selectedKeys.length > 0 && (
            <span className="text-[12px] text-[var(--color-primary)]">已选 {selectedKeys.length} 条</span>
          )}
        </Space>
        <Table rowKey="id" columns={columns} dataSource={data} loading={loading} size="small"
          rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
          pagination={{ pageSize: 20 }} />
      </Card>

      <Modal title={`分类人员与完成时间（${current?.department || ''}）`} open={modalOpen}
        onCancel={() => setModalOpen(false)} onOk={handleSavePersonnel} width={560}
        okText="保存">
        <Form form={form} layout="vertical" className="mt-2">
          <Form.Item name="classification" label="自定义分类（选择后自动拉取该分类下人员）">
            <Select allowClear placeholder="选择分类" options={classOptions}
              onChange={handleClassificationChange}
              filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item name="personnel" label="分类人员（可自由选择）" rules={[{ required: true, message: '请选择人员' }]}>
            <Select mode="multiple" placeholder={current?.classification ? '选择人员' : '请先选择分类'} loading={personnelLoading}
              options={personnelOptions.map((p) => ({ label: `${p.name}（${p.employee_number}${p.position ? ` / ${p.position}` : ''}）`, value: p.employee_number }))}
              filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item name="complete_time" label="完成时间/课时">
            <Input placeholder="R：2026.01.05；T：2026.01.05(14:00-15:00)" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
