'use client'

import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Space, Button, App, Modal, Form, Input, DatePicker, Upload } from 'antd'
import { PlusOutlined, DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type { InspectionPlan } from '@/types/quality'
import {
  fetchInspectionPlans, createInspectionPlan, updateInspectionPlanStatus,
  importInspectionPlans, downloadInspectionPlanTemplate,
} from '@/actions/quality'

export default function InspectionPlans({ onBuildTask }: { onBuildTask?: (batch: string, product: string) => void } = {}) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [data, setData] = useState<InspectionPlan[]>([])
  const [loading, setLoading] = useState(false)
  const [dateFilter, setDateFilter] = useState<string | undefined>(dayjs().format('YYYY-MM-DD'))
  const [createOpen, setCreateOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [reschedule, setReschedule] = useState<InspectionPlan | null>(null)
  const [rescheduling, setRescheduling] = useState(false)
  const [form] = Form.useForm()
  const [rescheduleForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchInspectionPlans(dateFilter)
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取请检计划失败')
    } finally {
      setLoading(false)
    }
  }, [message, dateFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  const onCreate = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await createInspectionPlan({
        ...values,
        plan_time: values.plan_time.format('YYYY-MM-DD HH:mm'),
      })
      message.success('计划已新增')
      setCreateOpen(false)
      form.resetFields()
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '新增失败')
    } finally {
      setSaving(false)
    }
  }

  const onToggleStatus = async (item: InspectionPlan) => {
    try {
      await updateInspectionPlanStatus(item.id, item.status === 'pending' ? 'inspected' : 'pending')
      message.success('状态已更新')
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '状态更新失败')
    }
  }

  const onReschedule = async () => {
    const values = await rescheduleForm.validateFields()
    if (!reschedule) return
    setRescheduling(true)
    try {
      await updateInspectionPlanStatus(reschedule.id, reschedule.status, values.plan_time.format('YYYY-MM-DD HH:mm'))
      message.success('已改期')
      setReschedule(null)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '改期失败')
    } finally {
      setRescheduling(false)
    }
  }

  const onImport = async (file: File) => {
    try {
      const res = await importInspectionPlans(file)
      message.success(res.message)
      if (res.data.skipped.length) {
        message.warning(`跳过 ${res.data.skipped.length} 条：${res.data.skipped.slice(0, 3).join('；')}`)
      }
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '导入失败')
    }
    return false
  }

  const onDownloadTemplate = async () => {
    try {
      const blob = await downloadInspectionPlanTemplate()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '请检计划导入模板.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '模板下载失败')
    }
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <DatePicker
          value={dateFilter ? dayjs(dateFilter) : null}
          onChange={(d) => setDateFilter(d ? d.format('YYYY-MM-DD') : undefined)}
          placeholder="按计划日期筛选"
        />
        <Button onClick={() => setDateFilter(undefined)}>查看全部</Button>
        {canManage && (
          <>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setCreateOpen(true) }}>手动新增</Button>
            <Button icon={<DownloadOutlined />} onClick={onDownloadTemplate}>下载模板</Button>
            <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={onImport}>
              <Button>导入 Excel</Button>
            </Upload>
          </>
        )}
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        scroll={{ x: 800 }}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '车间/部门', dataIndex: 'department', width: 140 },
          { title: '品种', dataIndex: 'product_name', width: 180 },
          { title: '批号', dataIndex: 'batch_no', width: 130, render: (v: string | null) => v || '-' },
          { title: '计划请检时间', dataIndex: 'plan_time', width: 160 },
          {
            title: '状态', dataIndex: 'status', width: 100,
            render: (v: string) => v === 'pending' ? <Tag color="gold">待请检</Tag> : <Tag color="green">已请检</Tag>,
          },
          {
            title: '操作', key: 'actions', width: 160,
            render: (_: unknown, item: InspectionPlan) => (
              canManage ? (
                <Space size="small">
                  {item.status === 'pending' && onBuildTask && (
                    <Button size="small" type="primary" onClick={() => onBuildTask(item.batch_no ?? '', item.product_name)}>
                      建任务
                    </Button>
                  )}
                  {item.status === 'pending' && (
                    <Button size="small" type="link" onClick={() => {
                      rescheduleForm.setFieldsValue({ plan_time: dayjs(item.plan_time) })
                      setReschedule(item)
                    }}>
                      改期
                    </Button>
                  )}
                  <Button size="small" type="link" onClick={() => onToggleStatus(item)}>
                    {item.status === 'pending' ? '标记已请检' : '改回待请检'}
                  </Button>
                </Space>
              ) : '-'
            ),
          },
        ]}
      />

      <Modal
        title="手动新增请检计划"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={onCreate}
        confirmLoading={saving}
        okText="新增"
        width={440}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="department" label="车间/部门" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如 发酵一车间" />
          </Form.Item>
          <Form.Item name="product_name" label="品种/产品名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如 盐酸万古霉素" />
          </Form.Item>
          <Form.Item name="batch_no" label="批号（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="plan_time" label="计划请检时间" rules={[{ required: true, message: '必填' }]}>
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="remark" label="备注（可选）">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`请检计划改期（${reschedule?.product_name ?? ''}${reschedule?.batch_no ? ` 批号 ${reschedule.batch_no}` : ''}）`}
        open={!!reschedule}
        onCancel={() => setReschedule(null)}
        onOk={onReschedule}
        confirmLoading={rescheduling}
        okText="保存"
        width={360}
      >
        <Form form={rescheduleForm} layout="vertical">
          <Form.Item name="plan_time" label="计划请检时间" rules={[{ required: true, message: '必填' }]}>
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
