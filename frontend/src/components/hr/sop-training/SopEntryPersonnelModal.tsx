'use client'

// SOP 培训二级表：给一条二级表记录选「自定义分类」和「分类人员」。
// 选分类后自动带出该分类下的部门人员并默认全选（已保存过人员的记录不覆盖），可再调整。

import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Modal, Select } from 'antd'
import { fetchSopClassifications, fetchSopPersonnel, updateSopTrainingEntry } from '@/actions/hr'
import { useUnsavedConfirm } from '@/hooks/hr'
import type { SopPersonnelOption, SopTrainingEntry } from '@/types/hr'
import styles from './sop-training.module.css'

interface FormValues {
  classification?: string
  personnel?: string[]
}

interface SopEntryPersonnelModalProps {
  open: boolean
  entry: SopTrainingEntry | null
  onClose: () => void
  onSaved: () => void
}

const LINK_BUTTON_STYLE = { height: 'auto', lineHeight: 'inherit', padding: '0 4px' }

export default function SopEntryPersonnelModal({
  open,
  entry,
  onClose,
  onSaved,
}: SopEntryPersonnelModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [classOptions, setClassOptions] = useState<{ label: string; value: string }[]>([])
  const [personnelOptions, setPersonnelOptions] = useState<SopPersonnelOption[]>([])
  const [personnelLoading, setPersonnelLoading] = useState(true)

  const initialValues = useMemo<FormValues>(
    () => ({
      classification: entry?.classification || undefined,
      personnel: (entry?.personnel || []).map((p) => p.employee_number),
    }),
    [entry],
  )
  const personnel = Form.useWatch('personnel', form) as string[] | undefined

  // 已保存、但已不在该分类当前人员里的名字也要能显示出来，不能只剩工号
  const selectOptions = useMemo(() => {
    const seen = new Set(personnelOptions.map((p) => p.employee_number))
    const saved = (entry?.personnel || [])
      .filter((p) => !seen.has(p.employee_number))
      .map((p) => ({ ...p, position: '', status: '' }))
    return [...personnelOptions, ...saved].map((p) => ({
      value: p.employee_number,
      label: `${p.name}（${p.employee_number}${p.position ? ` / ${p.position}` : ''}）`,
    }))
  }, [personnelOptions, entry])

  useEffect(() => {
    if (!entry) return
    let cancelled = false
    ;(async () => {
      const [clsRes, peopleRes] = await Promise.all([
        fetchSopClassifications(entry.department).catch(() => null),
        // 已有保存人员时只加载选项不覆盖；无保存人员时才默认全选分类下人员
        entry.classification
          ? fetchSopPersonnel(entry.department, entry.classification).catch(() => null)
          : Promise.resolve(null),
      ])
      if (cancelled) return
      setClassOptions(
        (clsRes?.data || []).map((c) => ({ label: `${c.tag_name}（${c.count}人）`, value: c.tag_name })),
      )
      const people = peopleRes?.data || []
      setPersonnelOptions(people)
      setPersonnelLoading(false)
      if (entry.classification && !(entry.personnel || []).length) {
        form.setFieldsValue({ personnel: people.map((p) => p.employee_number) })
      }
    })()
    return () => { cancelled = true }
    // 只在打开时加载一次：换一条记录打开由父组件换 key 重新挂载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadPersonnel = async (classification: string) => {
    if (!entry) return []
    try {
      return (await fetchSopPersonnel(entry.department, classification)).data || []
    } catch (e) {
      message.error(e instanceof Error ? e.message : '获取分类人员失败')
      return []
    }
  }

  const handleClassificationChange = async (value: string | undefined) => {
    form.setFieldsValue({ personnel: [] })
    setPersonnelOptions([])
    if (!value) return
    setPersonnelLoading(true)
    try {
      const people = await loadPersonnel(value)
      setPersonnelOptions(people)
      // 默认全选分类下人员，可自由调整
      form.setFieldsValue({ personnel: people.map((p) => p.employee_number) })
    } finally {
      setPersonnelLoading(false)
    }
  }

  // 只在弹窗打开且确有改动时拦，放弃/保存后复位 dirty：组件关闭后仍挂着，
  // 不复位的话之后每次刷新都会被 beforeunload 的「离开站点？」拦住
  const guardClose = useUnsavedConfirm(dirty && open, () => {
    setDirty(false)
    onClose()
  }, {
    content: '分类和人员的选择还没保存，关闭后会丢失，确定放弃吗？',
  })

  const handleOk = async () => {
    if (!entry) return
    let v: FormValues
    try {
      v = await form.validateFields()
    } catch {
      return // 校验失败：错误已在字段下方提示
    }
    const selected = new Set(v.personnel || [])
    const inOptions = new Set(personnelOptions.map((p) => p.employee_number))
    // 当前分类人员里选中的 + 之前已保存、如今不在分类人员里但仍被勾选的
    const personnel = [
      ...personnelOptions
        .filter((p) => selected.has(p.employee_number))
        .map(({ employee_number, name }) => ({ employee_number, name })),
      ...(entry.personnel || []).filter(
        (p) => selected.has(p.employee_number) && !inOptions.has(p.employee_number),
      ),
    ]
    setSaving(true)
    try {
      await updateSopTrainingEntry(entry.id, { classification: v.classification, personnel })
      message.success('已保存')
      setDirty(false)
      onSaved()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const selectedCount = personnel?.length ?? 0

  return (
    <Modal
      title={
        <span className="flex items-baseline gap-3">
          分类人员
          <span className="text-[13px] font-normal text-[var(--color-steel)]">{entry?.department}</span>
        </span>
      }
      open={open}
      onCancel={guardClose}
      onOk={() => { void handleOk() }}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      // 人员还在加载时保存会把已选人员清空
      okButtonProps={{ disabled: personnelLoading }}
      width={640}
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
        <Form.Item
          name="classification"
          label="自定义分类"
          tooltip="对应部门的员工分类；转培训时，这里选的人员会自动归入该分类"
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="选择分类，自动带出该分类下的人员"
            options={classOptions}
            onChange={(v) => { void handleClassificationChange(v) }}
          />
        </Form.Item>
        <Form.Item
          name="personnel"
          label="分类人员"
          rules={[{ required: true, message: '请选择人员' }]}
          extra={
            personnelOptions.length > 0 && (
              <span>
                已选 <b>{selectedCount}</b> / {personnelOptions.length} 人
                <Button
                  type="link"
                  size="small"
                  style={LINK_BUTTON_STYLE}
                  disabled={personnelLoading}
                  onClick={() => {
                    form.setFieldsValue({ personnel: personnelOptions.map((p) => p.employee_number) })
                    setDirty(true)
                  }}
                >
                  全选
                </Button>
                <Button
                  type="link"
                  size="small"
                  style={LINK_BUTTON_STYLE}
                  disabled={personnelLoading}
                  onClick={() => {
                    form.setFieldsValue({ personnel: [] })
                    setDirty(true)
                  }}
                >
                  清空
                </Button>
              </span>
            )
          }
        >
          <Select
            mode="multiple"
            showSearch
            optionFilterProp="label"
            placeholder={entry?.classification ? '选择人员' : '请先选择分类'}
            loading={personnelLoading}
            maxTagCount="responsive"
            options={selectOptions}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
