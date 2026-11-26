'use client'

// SOP 培训文件登记表的新增/编辑弹窗。
// 每次打开由父组件换 key 重新挂载：表单初值走 initialValues，不用 effect 把 props 拷进 state。

import { useEffect, useMemo, useState } from 'react'
import { App, DatePicker, Form, Input, Modal, Select, TimePicker } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import {
  createSopTrainingRecord,
  fetchDepartmentsAction,
  fetchSopDeptTrainers,
  updateSopTrainingRecord,
} from '@/actions/hr'
import { useUnsavedConfirm } from '@/hooks/hr'
import { SOP_CHANGE_TYPE_META } from '@/lib/hr'
import type { SopTrainingRecord } from '@/types/hr'
import { changeTagMeta } from './cells'
import styles from './sop-training.module.css'

interface RecordFormValues {
  year: string
  training_date?: Dayjs | null
  file_name: string
  file_no?: string | null
  effective_date?: Dayjs | null
  method?: string | null
  complete_date?: Dayjs | null
  complete_range?: [Dayjs, Dayjs] | null
  trainer?: string | null
  initiator_department?: string | null
  color: string
  involved_departments: string[]
  trainees?: string | null
  change_note?: string | null
}

interface SopRecordFormModalProps {
  open: boolean
  /** null = 新增 */
  editing: SopTrainingRecord | null
  /** 新增时的默认年份 */
  year: string
  onClose: () => void
  onSaved: () => void
}

// 完成时间/课时在后端存成一个字符串："2026.01.04(13:00-14:00)"，时段可缺
const COMPLETE_RE = /^(\d{4})\.(\d{2})\.(\d{2})(\((\d{2}:\d{2})-(\d{2}:\d{2})\))?$/

const CHANGE_OPTIONS = Object.keys(SOP_CHANGE_TYPE_META).map((name) => ({
  value: name,
  label: (
    <span className="inline-flex items-center gap-2">
      <i
        className="inline-block size-2 rounded-full"
        style={{ background: changeTagMeta(name).dot }}
      />
      {name}
    </span>
  ),
}))

// R/T 的含义取自纸质登记表表头：R 记培训完成时间，T 记培训课时
const METHOD_OPTIONS = [
  { value: 'R', label: 'R · 记录培训完成时间' },
  { value: 'T', label: 'T · 记录培训课时' },
]

const DEPARTMENT_SEARCH = (input: string, option?: { label?: string }) =>
  (option?.label ?? '').toLowerCase().includes(input.toLowerCase())

function toDayjs(raw: string | null | undefined): Dayjs | null {
  return raw && /^\d{4}[-.]\d{2}[-.]\d{2}$/.test(raw) ? dayjs(raw) : null
}

function formatDate(value: Dayjs | null | undefined): string | null {
  return value ? value.format('YYYY-MM-DD') : null
}

function toFormValues(editing: SopTrainingRecord | null, year: string): RecordFormValues {
  if (!editing) return { year, file_name: '', method: 'R', color: '新增', involved_departments: [] }
  const parsed = editing.complete_time?.match(COMPLETE_RE)
  return {
    year: editing.year,
    training_date: toDayjs(editing.training_date),
    file_name: editing.file_name,
    file_no: editing.file_no,
    effective_date: toDayjs(editing.effective_date),
    method: editing.method,
    complete_date: parsed ? dayjs(`${parsed[1]}-${parsed[2]}-${parsed[3]}`) : null,
    complete_range: parsed?.[4] ? [dayjs(parsed[5], 'HH:mm'), dayjs(parsed[6], 'HH:mm')] : null,
    trainer: editing.trainer,
    initiator_department: editing.initiator_department,
    color: editing.color,
    involved_departments: editing.involved_departments ?? [],
    trainees: editing.trainees,
    change_note: editing.change_note,
  }
}

export default function SopRecordFormModal({ open, editing, year, onClose, onSaved }: SopRecordFormModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<RecordFormValues>()
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [deptOptions, setDeptOptions] = useState<{ label: string; value: string }[]>([])
  const [deptTrainers, setDeptTrainers] = useState<{ department: string; trainer: string | null }[]>([])

  const initialValues = useMemo(() => toFormValues(editing, year), [editing, year])
  const method = Form.useWatch('method', form)

  // 历史数据的完成时间若不是「日期(时段)」写法，表单解析不出来；
  // 用户没动时间字段时原样保留，避免只是改个文件名就把完成时间清空
  const legacyTime = useMemo(() => {
    const raw = editing?.complete_time
    return raw && !COMPLETE_RE.test(raw) ? raw : null
  }, [editing])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchDepartmentsAction({ page_size: 100 })
        if (!cancelled) setDeptOptions((r.data || []).map((d) => ({ label: d.name, value: d.name })))
      } catch {
        if (!cancelled) message.error('加载部门列表失败')
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 编辑时回显已选部门的一级培训师（与下方 onChange 同一口径）
  const initialDepartments = initialValues.involved_departments
  useEffect(() => {
    if (!initialDepartments.length) return
    let cancelled = false
    ;(async () => {
      const res = await fetchSopDeptTrainers(initialDepartments).catch(() => null)
      if (!cancelled) setDeptTrainers(res?.data ?? [])
    })()
    return () => { cancelled = true }
  }, [initialDepartments])

  const handleDepartmentsChange = async (depts: string[]) => {
    setDeptTrainers([])
    if (!depts.length) return
    try {
      setDeptTrainers((await fetchSopDeptTrainers(depts)).data || [])
    } catch {
      // 查不到培训师不阻塞登记
    }
  }

  const handleInitiatorChange = (dept: string | undefined) => {
    // 培训对象为空时自动生成「X部门全体员工及相关部门培训师」
    if (!form.getFieldValue('trainees')) {
      form.setFieldsValue({ trainees: dept ? `「${dept}」全体员工及相关岗位培训师` : undefined })
    }
  }

  // 弹窗关闭后组件仍挂着（下次打开换 key 重建），所以：
  // ① 放弃/保存成功时把 dirty 复位，② 只在弹窗打开时才拦 beforeunload——
  //    否则放弃一次修改后，刷新页面都会被「离开站点？」拦住
  const guardClose = useUnsavedConfirm(dirty && open, () => {
    setDirty(false)
    onClose()
  }, {
    content: '表单里填写的内容还没保存，关闭后会丢失，确定放弃吗？',
  })

  const handleOk = async () => {
    let v: RecordFormValues
    try {
      v = await form.validateFields()
    } catch {
      return // 校验失败：错误已在字段下方提示
    }
    const date = v.complete_date ?? null
    const range = v.complete_range ?? null
    const hasRange = Array.isArray(range) && !!range[0] && !!range[1]
    const completeTime = date
      ? `${date.format('YYYY.MM.DD')}${hasRange ? `(${range[0].format('HH:mm')}-${range[1].format('HH:mm')})` : ''}`
      : hasRange
        ? `(${range[0].format('HH:mm')}-${range[1].format('HH:mm')})`
        : null
    const timeUntouched = !form.isFieldTouched('complete_date') && !form.isFieldTouched('complete_range')
    const payload: Partial<SopTrainingRecord> = {
      year: v.year.trim(),
      training_date: formatDate(v.training_date),
      file_name: v.file_name.trim(),
      file_no: v.file_no?.trim() || null,
      effective_date: formatDate(v.effective_date),
      method: v.method ?? null,
      complete_time: timeUntouched && legacyTime ? legacyTime : completeTime,
      trainer: v.trainer?.trim() || null,
      trainees: v.trainees?.trim() || null,
      involved_departments: v.involved_departments,
      change_note: v.change_note?.trim() || null,
      color: v.color,
      initiator_department: v.initiator_department ?? null,
    }
    setSaving(true)
    try {
      if (editing) {
        await updateSopTrainingRecord(editing.id, payload)
        message.success('已更新')
      } else {
        await createSopTrainingRecord(payload)
        message.success('已保存草稿，点「转培训」后收录到各部门二级表并通知培训管理员')
      }
      setDirty(false)
      onSaved()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={editing ? '编辑登记' : '新增培训文件登记'}
      open={open}
      onCancel={guardClose}
      onOk={() => { void handleOk() }}
      okText={editing ? '保存修改' : '保存草稿'}
      cancelText="取消"
      confirmLoading={saving}
      width={760}
      // 三段表单在 768 高度的屏幕上会超出窗口：正文内部滚动，标题和「保存/取消」始终可见
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      // 不加 forceRender：关闭状态下预渲染会让服务端与客户端输出不一致（hydration 报错）
      destroyOnHidden
      mask={{ closable: false }}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onValuesChange={() => setDirty(true)}
        className={styles.form}
      >
        <div className={styles.sectionTitle}>培训文件</div>
        <div className="grid grid-cols-3 gap-x-4">
          <Form.Item
            name="file_name"
            label="文件名称"
            className="col-span-2"
            rules={[{ required: true, whitespace: true, message: '请填写文件名称' }]}
          >
            <Input placeholder="如：发酵罐灭菌操作规程" />
          </Form.Item>
          <Form.Item name="file_no" label="文件编号">
            <Input placeholder="SOP 编号" />
          </Form.Item>
          <Form.Item name="effective_date" label="生效日期">
            <DatePicker className="w-full" format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item
            name="color"
            label="变更类型"
            tooltip="对应纸质登记表的颜色标注：黄=新增、红=修改、灰=撤销"
          >
            <Select options={CHANGE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="year"
            label="年份"
            rules={[
              { required: true, message: '请填写年份' },
              { pattern: /^\d{4}$/, message: '年份应为 4 位数字' },
            ]}
          >
            <Input maxLength={4} />
          </Form.Item>
        </div>
        <Form.Item name="change_note" label="变更内容">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} placeholder="新制订 / 修订了哪些条款" />
        </Form.Item>

        <div className={styles.sectionTitle}>培训安排</div>
        <div className="grid grid-cols-3 gap-x-4">
          <Form.Item name="training_date" label="培训日期">
            <DatePicker className="w-full" format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item
            name="method"
            label="培训方式"
            tooltip="取自纸质登记表表头：R 记录培训完成时间，T 记录培训课时"
          >
            <Select options={METHOD_OPTIONS} />
          </Form.Item>
          <Form.Item name="complete_date" label={method === 'T' ? '课时（日期）' : '完成时间（日期）'}>
            <DatePicker className="w-full" format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="complete_range" label="时间段（可选）" className="col-span-2">
            <TimePicker.RangePicker className="w-full" format="HH:mm" minuteStep={5} />
          </Form.Item>
          <Form.Item name="trainer" label="培训师">
            <Input placeholder="集中培训时填写" />
          </Form.Item>
        </div>

        <div className={styles.sectionTitle}>培训范围</div>
        <div className="grid grid-cols-5 gap-x-4">
          <Form.Item name="initiator_department" label="发起部门（主办部门）" className="col-span-2">
            <Select
              showSearch
              allowClear
              options={deptOptions}
              onChange={handleInitiatorChange}
              filterOption={DEPARTMENT_SEARCH}
            />
          </Form.Item>
          <Form.Item
            name="involved_departments"
            label="培训涉及部门"
            className="col-span-3"
            rules={[{ required: true, message: '请选择涉及部门' }]}
          >
            <Select
              mode="multiple"
              showSearch
              options={deptOptions}
              maxTagCount="responsive"
              onChange={(vals: string[]) => { void handleDepartmentsChange(vals || []) }}
              filterOption={DEPARTMENT_SEARCH}
            />
          </Form.Item>
        </div>
        {deptTrainers.length > 0 && (
          <div className="mb-[14px] rounded-[var(--rounded-md)] bg-[var(--color-surface)] px-3 py-2.5">
            <div className="mb-1.5 text-[12px] text-[var(--color-steel)]">
              涉及部门的一级培训师（转培训后作为被培训人员）
            </div>
            <div className="flex flex-wrap gap-1.5">
              {deptTrainers.map((t) => (
                <span key={t.department} className={styles.deptChip}>
                  {t.department}
                  <span className="mx-1.5 text-[var(--color-stone)]">·</span>
                  {t.trainer ?? <span className={styles.placeholder}>未配置</span>}
                </span>
              ))}
            </div>
          </div>
        )}
        <Form.Item
          name="trainees"
          label="培训对象"
          tooltip="留空自动生成「X部门全体员工及相关岗位培训师」"
        >
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  )
}
