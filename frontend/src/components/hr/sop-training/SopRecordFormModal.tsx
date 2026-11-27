'use client'

// SOP 培训文件登记表的新增/编辑弹窗。
// 每次打开由父组件换 key 重新挂载：表单初值走 initialValues，不用 effect 把 props 拷进 state。

import { useEffect, useMemo, useState } from 'react'
import { App, Button, Checkbox, DatePicker, Form, Input, Modal, Select, TimePicker, Tooltip } from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import {
  createSopTrainingRecord,
  fetchDepartmentsAction,
  fetchQuestionBankCounts,
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
  /** 一次登记可含多份培训文件，其余字段为这几份文件共用 */
  files: { file_name?: string; file_no?: string | null }[]
  effective_date?: Dayjs | null
  method?: string | null
  assessment_method?: string | null
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

// R/T 的含义取自纸质登记表表头：R 记培训完成时间（自学），T 记培训课时（面授）
const METHOD_OPTIONS = [
  { value: 'R', label: 'R · 自学（记完成时间）' },
  { value: 'T', label: 'T · 面授（记课时）' },
]

// 考核方式决定「生成一套材料」打包哪些文件：
// 阅读并理解→通知+签到+评估；问答→另有问答实操记录；笔试→另有试卷（题库按文件编号出题）
const ASSESSMENT_OPTIONS = ['阅读并理解', '问答', '笔试'].map((v) => ({ value: v, label: v }))
// 考核方式没手动选过时，随培训方式带默认值
const ASSESSMENT_DEFAULT_BY_METHOD: Record<string, string> = { R: '阅读并理解', T: '问答' }

const DEPARTMENT_SEARCH = (input: string, option?: { label?: string }) =>
  (option?.label ?? '').toLowerCase().includes(input.toLowerCase())

function toDayjs(raw: string | null | undefined): Dayjs | null {
  return raw && /^\d{4}[-.]\d{2}[-.]\d{2}$/.test(raw) ? dayjs(raw) : null
}

function formatDate(value: Dayjs | null | undefined): string | null {
  return value ? value.format('YYYY-MM-DD') : null
}

function toFormValues(editing: SopTrainingRecord | null, year: string): RecordFormValues {
  if (!editing) {
    return {
      year, method: 'R', assessment_method: '阅读并理解', color: '新增',
      involved_departments: [], files: [{ file_name: '', file_no: '' }],
    }
  }
  const parsed = editing.complete_time?.match(COMPLETE_RE)
  // 合并登记回显全部文件；历史单文件数据回落单列
  const rows = editing.files?.length
    ? editing.files.map((f) => ({ file_name: f.file_name, file_no: f.file_no ?? '' }))
    : [{ file_name: editing.file_name, file_no: editing.file_no ?? '' }]
  return {
    year: editing.year,
    training_date: toDayjs(editing.training_date),
    files: rows,
    effective_date: toDayjs(editing.effective_date),
    method: editing.method,
    // 历史记录没填考核方式时按培训方式带默认值
    assessment_method: editing.assessment_method ?? ASSESSMENT_DEFAULT_BY_METHOD[editing.method ?? ''] ?? '阅读并理解',
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
  /** 新增多份文件时可选「合并为一条登记」；默认分开（每份一条，维持原行为） */
  const [mergeIntoOne, setMergeIntoOne] = useState(false)
  const [deptOptions, setDeptOptions] = useState<{ label: string; value: string }[]>([])
  const [deptTrainers, setDeptTrainers] = useState<{ department: string; trainer: string | null }[]>([])

  const initialValues = useMemo(() => toFormValues(editing, year), [editing, year])
  const method = Form.useWatch('method', form)
  const selectedDepartments = (Form.useWatch('involved_departments', form) ?? []) as string[]

  // 考核方式=问答时提示题库收录情况：问答实操记录表按 SOP 编号从题库带题，缺题就留空白行手写。
  // 防抖 400ms：文件编号是逐字输入的，不必每敲一个字符查一次
  const watchedAssessment = Form.useWatch('assessment_method', form)
  const watchedFiles = (Form.useWatch('files', form) ?? []) as { file_no?: string | null }[]
  const effectiveAssessment =
    watchedAssessment || ASSESSMENT_DEFAULT_BY_METHOD[method ?? ''] || '阅读并理解'
  const fileNos = [...new Set(watchedFiles.map((f) => (f?.file_no ?? '').trim()).filter(Boolean))]
  const fileNoKey = fileNos.join('\n')
  const [qaHint, setQaHint] = useState<{ total: number | null; missing: string[] } | null>(null)

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(async () => {
      let next: { total: number | null; missing: string[] } | null = null
      if (effectiveAssessment === '问答') {
        if (!fileNos.length) {
          next = { total: null, missing: [] } // 还没填编号也提示：不查库，纯文案
        } else {
          try {
            const r = await fetchQuestionBankCounts(fileNos)
            const counts = r.data?.counts ?? {}
            next = {
              total: fileNos.reduce((sum, no) => sum + (counts[no] ?? 0), 0),
              missing: fileNos.filter((no) => !(counts[no] ?? 0)),
            }
          } catch {
            next = null // 计数拉不到就不提示，不阻塞登记
          }
        }
      }
      if (!cancelled) setQaHint(next)
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // fileNos 是每次渲染新建的数组，用拼接串做依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveAssessment, fileNoKey])

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

  // 全选口径固定为全部部门，不随搜索词变化：antd 在 blur/ESC/点选项后会静默清搜索框（不发 onSearch），
  // 若按搜索结果算「当前 N 项」会与列表实际显示脱节；35 个部门的场景也不需要「按结果全选」
  const allDepartmentsSelected =
    deptOptions.length > 0 && deptOptions.every((o) => selectedDepartments.includes(o.value))
  const someDepartmentsSelected = deptOptions.some((o) => selectedDepartments.includes(o.value))

  const toggleAllDepartments = (checked: boolean) => {
    const next = checked ? deptOptions.map((o) => o.value) : []
    // setFieldsValue 不触发 onValuesChange：dirty 与培训师联动在这里手动补
    form.setFieldsValue({ involved_departments: next })
    setDirty(true)
    void handleDepartmentsChange(next)
  }

  const handleInitiatorChange = (dept: string | undefined) => {
    // 培训对象为空时自动生成「X部门全体员工及相关岗位培训师」
    if (!form.getFieldValue('trainees')) {
      form.setFieldsValue({ trainees: dept ? `「${dept}」全体员工及相关岗位培训师` : undefined })
    }
  }

  const handleMethodChange = (val: string) => {
    // 考核方式没手动选过时跟随培训方式的默认值；手选过则尊重手选
    if (!form.isFieldTouched('assessment_method')) {
      form.setFieldsValue({ assessment_method: ASSESSMENT_DEFAULT_BY_METHOD[val] ?? '阅读并理解' })
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
    const files = (v.files ?? []).map((f) => ({
      file_name: (f.file_name ?? '').trim(),
      file_no: f.file_no?.trim() || null,
    }))
    // 文件名称/编号之外的字段为各份文件共用
    const payload: Partial<SopTrainingRecord> = {
      year: v.year.trim(),
      training_date: formatDate(v.training_date),
      effective_date: formatDate(v.effective_date),
      method: v.method ?? null,
      assessment_method: v.assessment_method ?? null,
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
        // 编辑保存为一条记录；files 里是完整的文件列表（后端据此重算展示串）
        await updateSopTrainingRecord(editing.id, { ...payload, files })
        message.success('已更新')
      } else if (mergeIntoOne && files.length > 1) {
        await createSopTrainingRecord({ ...payload, files })
        message.success(
          `已合并为一条登记（含 ${files.length} 份文件），点「转培训」后收录到各部门二级表并通知培训管理员`,
        )
      } else {
        // 每份文件一条登记记录；逐条串行建，中途失败时已入库的行从表单移除，重试只补剩余的
        let saved = 0
        try {
          for (const f of files) {
            await createSopTrainingRecord({ ...payload, files: [f], ...f })
            saved++
          }
        } catch (e) {
          const failed = files[saved]
          form.setFieldsValue({ files: v.files?.slice(saved) })
          message.error(
            `前 ${saved} 条已保存，第 ${saved + 1} 条「${failed.file_name}」保存失败：${
              e instanceof Error ? e.message : '未知错误'
            }，未保存的仍留在表单中，可修正后重试`,
          )
          return
        }
        message.success(
          files.length > 1
            ? `已保存 ${files.length} 条登记草稿，点「转培训」后收录到各部门二级表并通知培训管理员`
            : '已保存草稿，点「转培训」后收录到各部门二级表并通知培训管理员',
        )
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
        {/* 一次培训可能覆盖多份文件：加号逐行添加、可删行；编辑态同样可增删（存 files） */}
        <Form.List name="files">
          {(fields, { add, remove }) => (
            <div className="mb-[14px]">
              {fields.length > 1 && (
                <div className="grid grid-cols-[2fr_1fr_auto] gap-x-4">
                  <Form.Item label="文件名称" required style={{ marginBottom: 0 }} />
                  <Form.Item label="文件编号" style={{ marginBottom: 0 }} />
                  <span />
                </div>
              )}
              <div className="space-y-2">
                {fields.map(({ key, name }, index) => (
                  <div key={key} className="grid grid-cols-[2fr_1fr_auto] items-start gap-x-4">
                    <Form.Item
                      name={[name, 'file_name']}
                      label={fields.length === 1 ? '文件名称' : undefined}
                      style={{ marginBottom: 0 }}
                      rules={[{ required: true, whitespace: true, message: '请填写文件名称' }]}
                    >
                      <Input placeholder="如：发酵罐灭菌操作规程" />
                    </Form.Item>
                    <Form.Item
                      name={[name, 'file_no']}
                      label={fields.length === 1 ? '文件编号' : undefined}
                      style={{ marginBottom: 0 }}
                    >
                      <Input placeholder="SOP 编号" />
                    </Form.Item>
                    <Tooltip title="删除该行">
                      <Button
                        type="text"
                        danger
                        aria-label={`删除第 ${index + 1} 行培训文件`}
                        disabled={fields.length === 1}
                        icon={<MinusCircleOutlined />}
                        onClick={() => remove(name)}
                      />
                    </Tooltip>
                  </div>
                ))}
              </div>
              {!editing && fields.length > 1 && (
                <Checkbox
                  className="mt-2"
                  checked={mergeIntoOne}
                  onChange={(e) => { setMergeIntoOne(e.target.checked); setDirty(true) }}
                >
                  合并为一条登记（总表一行，转培训 / 生成材料按一次处理）
                </Checkbox>
              )}
              <Button
                type="dashed"
                block
                icon={<PlusOutlined />}
                className="mt-2"
                onClick={() => add({ file_name: '', file_no: '' })}
              >
                添加培训文件
              </Button>
            </div>
          )}
        </Form.List>
        <div className="grid grid-cols-3 gap-x-4">
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
            label="培训方式（R/T）"
            tooltip="R=自学（记完成时间），T=面授（记课时）"
          >
            <Select options={METHOD_OPTIONS} onChange={handleMethodChange} />
          </Form.Item>
          <Form.Item
            name="assessment_method"
            label="考核方式"
            tooltip="决定「生成一套材料」的内容：阅读并理解→通知/签到/评估；问答→另有问答实操记录；笔试→另有试卷（题库按文件编号出题）。默认随培训方式带出：自学(R)=阅读并理解、面授(T)=问答，可手动修改"
          >
            <Select options={ASSESSMENT_OPTIONS} />
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
        {effectiveAssessment === '问答' && qaHint && (
          <div className="mb-[14px] rounded-[var(--rounded-md)] bg-[var(--color-surface)] px-3 py-2.5 text-[12px] text-[var(--color-steel)]">
            {qaHint.total === null ? (
              <>培训文件还没填 SOP 编号：题库按编号匹配考题，生成材料时问答实操记录表会留空白行手写</>
            ) : qaHint.total > 0 && !qaHint.missing.length ? (
              <>题库已收录这些编号的 <b className="text-[var(--color-ink)]">{qaHint.total}</b> 道考题，「生成一套材料」时问答实操记录表自动带题</>
            ) : qaHint.total > 0 ? (
              <>题库已收录 {qaHint.total} 道考题；这些编号尚无题：{qaHint.missing.join('、')}——保存后可在总表行上用「AI 出题」补题</>
            ) : (
              <>题库还没有这些编号（{fileNos.join('、')}）的考题：保存后可在总表行上用「AI 出题」补题，生成材料时问答实操记录表留空白行手写</>
            )}
          </div>
        )}

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
              popupRender={(menu) => (
                <>
                  <div
                    className="flex items-center border-b border-[var(--color-hairline-soft)] px-2 py-1.5"
                    // 阻止默认按下行为，点全选时下拉不收起、搜索框不失焦
                    onMouseDown={(e) => { e.preventDefault() }}
                  >
                    <Checkbox
                      checked={allDepartmentsSelected}
                      indeterminate={someDepartmentsSelected && !allDepartmentsSelected}
                      disabled={!deptOptions.length}
                      onChange={(e) => toggleAllDepartments(e.target.checked)}
                    >
                      全选{deptOptions.length ? `（${deptOptions.length}）` : ''}
                    </Checkbox>
                  </div>
                  {menu}
                </>
              )}
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
