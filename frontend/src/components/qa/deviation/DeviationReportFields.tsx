'use client'

import { useEffect, useState } from 'react'
import { AutoComplete, Button, DatePicker, Form, Input, Select } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchQaDepartments } from '@/lib/api/qa'
import type { QaDepartmentReference } from '@/types/qa'
import {
  DEVIATION_ITEM_CATEGORY_LABEL,
  type DeviationAiAssistInput,
  type DeviationCreateInput,
  type DeviationDetail,
  type DeviationItem,
} from '@/types/qa-deviation'
import { DeviationAiAssistButton } from './DeviationAiAssist'
import { toOptions } from './shared'

const ITEM_CATEGORY_OPTIONS = toOptions(DEVIATION_ITEM_CATEGORY_LABEL)

/** 偏差报告表第一部分的表单值（日期用 dayjs，提交时再转字符串）。 */
export interface ReportFormValues {
  discovery_date: Dayjs
  occurrence_date?: Dayjs | null
  department_name?: string
  group_name?: string
  reporter_name?: string
  qa_person_name?: string
  description: string
  emergency_measures?: string
  remark?: string
  items?: Partial<DeviationItem>[]
}

export function reportFormInitialValues(detail?: DeviationDetail | null): Partial<ReportFormValues> {
  if (!detail) {
    return { discovery_date: dayjs(), items: [] }
  }
  return {
    discovery_date: dayjs(detail.discovery_date),
    occurrence_date: detail.occurrence_date ? dayjs(detail.occurrence_date) : null,
    department_name: detail.department_name ?? undefined,
    group_name: detail.group_name ?? undefined,
    reporter_name: detail.reporter_name ?? undefined,
    qa_person_name: detail.qa_person_name ?? undefined,
    description: detail.description,
    emergency_measures: detail.emergency_measures ?? undefined,
    remark: detail.remark ?? undefined,
    items: detail.items.map((item) => ({ ...item })),
  }
}

/** 把表单值转成后端 payload；部门名称命中飞书部门时带上 ID 做快照校验。 */
export function reportFormToPayload(
  values: ReportFormValues,
  departments: QaDepartmentReference[],
): DeviationCreateInput {
  const departmentName = values.department_name?.trim() || null
  const matched = departmentName
    ? departments.find((dept) => dept.name === departmentName && dept.feishu_department_id)
    : undefined
  return {
    discovery_date: values.discovery_date.format('YYYY-MM-DD'),
    occurrence_date: values.occurrence_date ? values.occurrence_date.format('YYYY-MM-DD') : null,
    department_id: matched?.feishu_department_id ?? null,
    department_name: departmentName,
    group_name: values.group_name?.trim() || null,
    reporter_name: values.reporter_name?.trim() || null,
    qa_person_name: values.qa_person_name?.trim() || null,
    description: values.description.trim(),
    emergency_measures: values.emergency_measures?.trim() || null,
    remark: values.remark?.trim() || null,
    items: (values.items ?? [])
      .filter((item): item is DeviationItem => Boolean(item && item.name && item.name.trim() && item.category))
      .map((item) => ({
        category: item.category,
        name: item.name.trim(),
        batch_no: item.batch_no?.trim() || null,
        handling: item.handling?.trim() || null,
      })),
  }
}

export function useQaDepartments(): QaDepartmentReference[] {
  const [departments, setDepartments] = useState<QaDepartmentReference[]>([])
  useEffect(() => {
    fetchQaDepartments()
      .then((rows) => setDepartments(rows.filter((row) => row.is_active !== false)))
      .catch(() => { /* 部门列表仅用于联想，失败时仍可手填 */ })
  }, [])
  return departments
}

/** 涉及对象明细（物料/批次/设备/文件及处理意见）的动态行编辑。 */
export function DeviationItemsFields({ showHandling = false }: { showHandling?: boolean }) {
  return (
    <Form.List name="items">
      {(fields, { add, remove }) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {fields.map((field) => (
            <div
              key={field.key}
              style={{
                display: 'grid',
                // 末列留 44px：antd v6 图标按钮最小点击区 44×44，给 32px 会撑出横向滚动条。
                gridTemplateColumns: showHandling ? '120px 1fr 160px 1fr 44px' : '120px 1fr 180px 44px',
                gap: 8,
                alignItems: 'start',
              }}
            >
              <Form.Item name={[field.name, 'category']} rules={[{ required: true, message: '选择类别' }]} style={{ marginBottom: 0 }}>
                <Select options={ITEM_CATEGORY_OPTIONS} placeholder="类别" />
              </Form.Item>
              <Form.Item name={[field.name, 'name']} rules={[{ required: true, message: '填写名称' }]} style={{ marginBottom: 0 }}>
                <Input placeholder="品名 / 设备名 / 文件名" maxLength={255} />
              </Form.Item>
              <Form.Item name={[field.name, 'batch_no']} style={{ marginBottom: 0 }}>
                <Input placeholder="批号 / 编号" maxLength={128} />
              </Form.Item>
              {showHandling && (
                <Form.Item name={[field.name, 'handling']} style={{ marginBottom: 0 }}>
                  <Input placeholder="处理意见（复测 / 放行 / 不放行…）" maxLength={4000} />
                </Form.Item>
              )}
              <Button type="text" icon={<DeleteOutlined />} onClick={() => remove(field.name)} aria-label="删除该行" />
            </div>
          ))}
          <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ category: 'finished' })} style={{ alignSelf: 'flex-start' }}>
            添加涉及对象
          </Button>
        </div>
      )}
    </Form.List>
  )
}

/** 偏差报告表第一部分的字段集合；登记弹窗与详情页"报告信息"编辑共用。 */
export function DeviationReportFields({
  departments,
  showItems = true,
  showHandling = false,
}: {
  departments: QaDepartmentReference[]
  showItems?: boolean
  showHandling?: boolean
}) {
  const form = Form.useFormInstance<ReportFormValues>()
  const departmentOptions = departments.map((dept) => ({ value: dept.name }))
  const buildDescribeInput = (): DeviationAiAssistInput => {
    const values = form.getFieldsValue()
    return {
      kind: 'describe',
      description: values.description ?? '',
      department_name: values.department_name ?? null,
      group_name: values.group_name ?? null,
      reporter_name: values.reporter_name ?? null,
      emergency_measures: values.emergency_measures ?? null,
      items: (values.items ?? [])
        .filter((item): item is DeviationItem => Boolean(item && item.name && item.name.trim() && item.category))
        .map((item) => ({ category: item.category, name: item.name, batch_no: item.batch_no ?? null })),
    }
  }
  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '0 16px' }}>
        <Form.Item name="discovery_date" label="发现日期" rules={[{ required: true, message: '请选择发现日期' }]}
          tooltip="30 天关闭期限从这一天起算">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="occurrence_date" label="发生日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="qa_person_name" label="质量员">
          <Input placeholder="默认当前登录人" maxLength={128} />
        </Form.Item>
        <Form.Item name="department_name" label="发生部门">
          <AutoComplete
            options={departmentOptions}
            placeholder="选择飞书部门或手填"
            filterOption={(input, option) => String(option?.value ?? '').includes(input)}
            allowClear
          />
        </Form.Item>
        <Form.Item name="group_name" label="组别" tooltip="同部门同组别 3 个月内同根因再发即重复偏差">
          <Input placeholder="如：理化组" maxLength={128} />
        </Form.Item>
        <Form.Item name="reporter_name" label="发现人">
          <Input maxLength={128} />
        </Form.Item>
      </div>
      <Form.Item
        name="description"
        label={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            偏差描述（5W1H）
            <DeviationAiAssistButton
              kind="describe"
              label="规范化"
              buildInput={buildDescribeInput}
              onAdopt={(payload) => {
                if (payload.kind !== 'describe') return
                if (payload.description) {
                  form.setFieldValue('description', payload.description)
                  // 采纳后把焦点放到描述框，长表单里用户能立刻复核改写结果。
                  form.focusField('description')
                }
                if (payload.items.length > 0) {
                  const existing = (form.getFieldValue('items') as Partial<DeviationItem>[] | undefined) ?? []
                  form.setFieldValue('items', [...existing, ...payload.items])
                }
              }}
            />
          </span>
        }
        rules={[{ required: true, whitespace: true, message: '请填写偏差描述' }]}
        extra="何时、何地、谁、发现了什么、如何导致、为何算偏差（正确做法是什么）"
      >
        <Input.TextArea autoSize={{ minRows: 4, maxRows: 12 }} maxLength={20000} showCount />
      </Form.Item>
      <Form.Item name="emergency_measures" label="应急处理措施">
        <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} maxLength={8000} placeholder="暂停放行 / 隔离 / 设备停用 / 批记录备注等" />
      </Form.Item>
      {showItems && (
        <Form.Item label="涉及物料 / 产品 / 设备 / 文件" style={{ marginBottom: 16 }}>
          <DeviationItemsFields showHandling={showHandling} />
        </Form.Item>
      )}
      <Form.Item name="remark" label="其他说明" style={{ marginBottom: 0 }}>
        <Input.TextArea autoSize={{ minRows: 1, maxRows: 6 }} maxLength={8000} />
      </Form.Item>
    </>
  )
}
