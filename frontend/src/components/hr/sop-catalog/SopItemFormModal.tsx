'use client'

import { useMemo, useState } from 'react'
import { App, Form, Input, Modal, Select } from 'antd'
import type { DefaultOptionType } from 'antd/es/select'

import { createPositionTraining } from '@/actions/hr'
import { useUnsavedConfirm } from '@/hooks/hr'
import type { PositionOption, SopCatalogItem } from '@/types/hr'
import { byName, errText } from './sopGroups'

export interface CreatedSopItem {
  department: string
  positionName: string
  fileName: string
}

interface SopItemFormValues {
  department?: string
  position_name?: string
  training_category?: string
  file_name?: string
  sop_number?: string
}

interface PositionChoice {
  value: string
  label: string
  /** 该岗位在目录里已有的条目数；组织架构里还没配培训内容的岗位没有这个数 */
  count?: number
}

interface SopItemFormModalProps {
  open: boolean
  /** 打开时所处视图的部门；「全部部门」视图下不传 */
  defaultDepartment?: string
  /** 部门下拉选项 */
  departments: string[]
  /** 已加载的目录条目：取所选部门下已有的岗位分组、拦住重复条目 */
  items: SopCatalogItem[]
  /** 组织架构里的岗位：还没配过培训内容的岗位从这里选 */
  positions: PositionOption[]
  onClose: () => void
  onCreated: (created: CreatedSopItem) => void
}

/** 新增一条培训内容（同时写入 SOP 目录和岗位培训关联，入职培训才能选到） */
export default function SopItemFormModal({
  open,
  defaultDepartment,
  departments,
  items,
  positions,
  onClose,
  onCreated,
}: SopItemFormModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<SopItemFormValues>()
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const department = Form.useWatch('department', form)

  // 岗位下拉 = 目录里已有的岗位 ∪ 组织架构里该部门的岗位。
  // 导入的岗位名带部门前缀，在组织架构岗位表里对不上：不把已有的分组列进来，就没法往里加条目
  const [existingChoices, orgChoices] = useMemo<[PositionChoice[], PositionChoice[]]>(() => {
    if (!department) return [[], []]
    const counts = new Map<string, number>()
    for (const item of items) {
      if (item.department === department && item.position_name) {
        counts.set(item.position_name, (counts.get(item.position_name) ?? 0) + 1)
      }
    }
    const existing = [...counts.keys()].sort(byName).map((name) => ({
      value: name,
      label: name,
      count: counts.get(name),
    }))
    const org = positions
      .filter((position) => position.department === department && !counts.has(position.name))
      .map((position) => ({ value: position.name, label: position.name }))
    return [existing, org]
  }, [department, items, positions])

  // 只在弹窗打开且确有改动时拦，放弃/保存后复位 dirty：
  // 组件关闭后仍挂着，不复位的话之后每次刷新都会被 beforeunload 的「离开站点？」拦住
  const guardClose = useUnsavedConfirm(dirty && open, () => {
    setDirty(false)
    onClose()
  })

  const submit = async () => {
    // 校验失败只走表单行内提示
    let values: SopItemFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const dept = values.department as string
    const positionName = (values.position_name as string).trim()
    const category = (values.training_category as string).trim()
    const fileName = (values.file_name ?? '').trim() || category
    if (items.some((item) => item.department === dept
      && item.position_name === positionName && item.file_name === fileName)) {
      message.error(`「${positionName}」下已经有「${fileName}」这条培训内容了`)
      return
    }
    setSaving(true)
    try {
      await createPositionTraining({
        department: dept,
        position_name: positionName,
        training_category: category,
        file_name: fileName,
        sop_number: values.sop_number?.trim() || null,
      })
      setDirty(false)
      onCreated({ department: dept, positionName, fileName })
      onClose()
    } catch (err) {
      message.error(errText(err, '新增失败'))
    } finally {
      setSaving(false)
    }
  }

  // Select 的选项按分组给；已有岗位的 label 里带条数（ReactNode）
  const positionOptions: DefaultOptionType[] = []
  if (existingChoices.length > 0) {
    positionOptions.push({
      label: '已有培训内容的岗位',
      options: existingChoices.map((choice) => ({
        value: choice.value,
        label: (
          <span>
            {choice.label}
            <span className="ml-2 text-[12px] text-[var(--color-stone)]">{choice.count} 条</span>
          </span>
        ),
      })),
    })
  }
  if (orgChoices.length > 0) {
    positionOptions.push({ label: '组织架构里还没配培训内容的岗位', options: orgChoices })
  }

  return (
    <Modal
      title="新增培训内容"
      open={open}
      okText="新增"
      cancelText="取消"
      confirmLoading={saving}
      onOk={() => { void submit() }}
      onCancel={guardClose}
      destroyOnHidden
      mask={{ closable: false }}
      width={520}
    >
      <Form<SopItemFormValues>
        form={form}
        layout="vertical"
        className="mt-4"
        initialValues={{ department: defaultDepartment || undefined }}
        onValuesChange={(changed) => {
          setDirty(true)
          // 文件名称没被单独填过时，跟着培训类别走
          if ('training_category' in changed && !form.isFieldTouched('file_name')) {
            form.setFieldValue('file_name', changed.training_category)
          }
          // 换了部门，原先选的岗位就不属于这个部门了
          if ('department' in changed) {
            form.setFieldValue('position_name', undefined)
          }
        }}
      >
        <Form.Item
          name="department"
          label="部门"
          rules={[{ required: true, message: '请选择部门' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择部门"
            options={departments.map((name) => ({ value: name, label: name }))}
          />
        </Form.Item>

        <Form.Item
          name="position_name"
          label="岗位"
          rules={[{ required: true, message: '请选择岗位' }]}
        >
          <Select
            showSearch
            disabled={!department}
            placeholder={department ? '选择岗位' : '请先选择部门'}
            // label 里带着条数（ReactNode），按 value 过滤才靠得住
            filterOption={(input, option) => String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())}
            notFoundContent="这个部门还没有可选的岗位，请先到「岗位管理」里新增"
            options={positionOptions}
          />
        </Form.Item>

        <Form.Item
          name="training_category"
          label="培训类别"
          rules={[
            { required: true, whitespace: true, message: '请输入培训类别' },
            { max: 128, message: '培训类别不能超过 128 个字符' },
          ]}
        >
          <Input maxLength={128} placeholder="如：岗位职责、文件管理、质量管理" />
        </Form.Item>

        <Form.Item
          name="file_name"
          label="文件名称"
          rules={[{ max: 256, message: '文件名称不能超过 256 个字符' }]}
          extra="默认与培训类别相同；有具体文件名时填文件名"
        >
          <Input maxLength={256} placeholder="默认与培训类别相同" />
        </Form.Item>

        <Form.Item
          name="sop_number"
          label="SOP 编号"
          rules={[{ max: 64, message: 'SOP 编号不能超过 64 个字符' }]}
        >
          <Input maxLength={64} placeholder="选填，如 SOP.01.3701" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
