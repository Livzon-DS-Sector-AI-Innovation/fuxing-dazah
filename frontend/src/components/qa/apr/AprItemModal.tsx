'use client'

import { useState } from 'react'
import {
  App,
  AutoComplete,
  Checkbox,
  Collapse,
  ConfigProvider,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
} from 'antd'
import { actionError } from '@/components/qa/deviation/shared'
import { createAprItem, updateAprItem } from '@/actions/qa'
import type {
  AprItem,
  AprItemCategory,
  AprItemInput,
  AprNdPolicy,
  AprSection,
  AprValueType,
} from '@/types/qa'
import {
  CATEGORY_OPTIONS,
  confirmAsync,
  formatRange,
  isAutoCode,
  parseSpecRange,
} from './AprConfigShared'

interface ItemFormValues {
  name_cn: string
  name_en?: string
  group_name?: string
  category: AprItemCategory
  value_type: AprValueType
  unit?: string
  spec_text?: string
  spec_min?: number | null
  spec_max?: number | null
  oot_min?: number | null
  oot_max?: number | null
  nd_policy: AprNdPolicy
  quick_values: string[]
  stat_precision?: number | null
  trend_enabled: boolean
  required: boolean
  is_active: boolean
  code?: string
  sort_order?: number | null
}

interface AprItemModalProps {
  section: AprSection
  item: AprItem | null
  /** 段内已有表头分组，用于自动补全，避免同一分组写法不一致。 */
  groups: string[]
  /** 新增列时的默认分组（沿用上一列的分组，连续录入更快）。 */
  defaultGroup?: string | null
  onClose: () => void
  onSaved: () => void
}

const BLOCK_LABEL = 'mb-1.5 text-[12px] font-semibold text-[var(--color-steel)]'
const ITEM_STYLE = { marginBottom: 10 }

/**
 * 单列定义表单：按「基本信息 / 标准与预警 / 标记与高级」三段组织，
 * 值类型为文字时自动隐藏数值限，减少无关字段干扰。
 */
export function AprItemModal({ section, item, groups, defaultGroup, onClose, onSaved }: AprItemModalProps) {
  const { message, modal } = App.useApp()
  const [form] = Form.useForm<ItemFormValues>()
  const valueType = Form.useWatch('value_type', form) ?? item?.value_type ?? 'number'
  const isNumber = valueType === 'number'
  const [saving, setSaving] = useState(false)
  const [parsedHint, setParsedHint] = useState<string | null>(null)

  const initialValues: ItemFormValues = item
    ? {
        name_cn: item.name_cn,
        name_en: item.name_en ?? '',
        group_name: item.group_name ?? '',
        category: item.category,
        value_type: item.value_type,
        unit: item.unit ?? '',
        spec_text: item.spec_text ?? '',
        spec_min: item.spec_min,
        spec_max: item.spec_max,
        oot_min: item.oot_min,
        oot_max: item.oot_max,
        nd_policy: item.nd_policy,
        quick_values: item.quick_values,
        stat_precision: item.stat_precision,
        trend_enabled: item.trend_enabled,
        required: item.required,
        is_active: item.is_active,
        // 自动编码是内部实现，不展示给用户；留空保存时保持原编码
        code: isAutoCode(item.code) ? '' : item.code,
        sort_order: item.sort_order,
      }
    : {
        name_cn: '',
        name_en: '',
        group_name: defaultGroup ?? '',
        category: section.data_kind === 'production' ? 'cpp' : 'test',
        value_type: 'number',
        unit: '',
        spec_text: '',
        spec_min: null,
        spec_max: null,
        oot_min: null,
        oot_max: null,
        nd_policy: 'zero',
        quick_values: ['未检出', '<1'],
        stat_precision: null,
        trend_enabled: true,
        required: true,
        is_active: true,
        code: '',
        sort_order: null,
      }

  const handleSpecBlur = (raw: string) => {
    if (!isNumber) return
    const parsed = parseSpecRange(raw)
    if (!parsed) {
      setParsedHint(null)
      return
    }
    const min = form.getFieldValue('spec_min') as number | null | undefined
    const max = form.getFieldValue('spec_max') as number | null | undefined
    const patch: { spec_min?: number; spec_max?: number } = {}
    if (min == null && parsed.min != null) patch.spec_min = parsed.min
    if (max == null && parsed.max != null) patch.spec_max = parsed.max
    if (Object.keys(patch).length === 0) {
      setParsedHint(null)
      return
    }
    form.setFieldsValue(patch)
    setParsedHint(
      `已自动识别限度：${formatRange(
        patch.spec_min ?? min ?? null,
        patch.spec_max ?? max ?? null,
      )}，可直接修改`,
    )
  }

  const handleSubmit = async () => {
    let values: ItemFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const text = (value?: string) => value?.trim() || null
    const isNumberValue = values.value_type === 'number'
    const input: AprItemInput = {
      section_id: section.id,
      name_cn: values.name_cn.trim(),
      name_en: text(values.name_en),
      group_name: text(values.group_name),
      category: values.category,
      value_type: values.value_type,
      unit: isNumberValue ? text(values.unit) : null,
      spec_text: text(values.spec_text),
      spec_min: isNumberValue ? values.spec_min ?? null : null,
      spec_max: isNumberValue ? values.spec_max ?? null : null,
      oot_min: isNumberValue ? values.oot_min ?? null : null,
      oot_max: isNumberValue ? values.oot_max ?? null : null,
      nd_policy: isNumberValue ? values.nd_policy : undefined,
      quick_values: isNumberValue ? values.quick_values : undefined,
      stat_precision: isNumberValue ? (values.stat_precision ?? null) : null,
      trend_enabled: isNumberValue ? Boolean(values.trend_enabled) : false,
      required: Boolean(values.required),
      // 编码留空时：新增由后端生成，编辑保持原编码不变
      code: values.code?.trim() || undefined,
      sort_order: values.sort_order ?? undefined,
    }

    const doSubmit = async () => {
      setSaving(true)
      try {
        const result = item
          ? await updateAprItem(item.id, { ...input, is_active: values.is_active })
          : await createAprItem(input)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success(item ? '列定义已更新' : '列定义已新增')
        onSaved()
        onClose()
      } finally {
        setSaving(false)
      }
    }

    const specChanged =
      item != null && (input.spec_min !== item.spec_min || input.spec_max !== item.spec_max)
    if (specChanged) {
      confirmAsync(modal, {
        title: '确认修改标准限？',
        content: '历史录入值会按新限度重新判定 OOS/OOT，趋势图参考线也会随之变化。',
        okText: '继续保存',
        cancelText: '再看看',
        onOk: doSubmit,
      })
      return
    }
    await doSubmit()
  }

  return (
    <Modal
      title={
        <div>
          <div className="text-[16px]">{item ? '编辑列定义' : '新增列定义'}</div>
          <div className="mt-0.5 text-[12px] font-normal text-[var(--color-steel)]">
            {section.name}
          </div>
        </div>
      }
      open
      width={760}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      mask={{ closable: false }}
      styles={{ body: { maxHeight: '72vh', overflowY: 'auto', paddingRight: 6 } }}
    >
      <ConfigProvider componentSize="small">
      <Form form={form} layout="vertical" initialValues={initialValues} preserve={false}>
        <div className={BLOCK_LABEL}>基本信息</div>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item
            name="name_cn"
            label="名称（中文）"
            style={ITEM_STYLE}
            rules={[{ required: true, whitespace: true, message: '请输入列名称' }]}
          >
            <Input autoFocus maxLength={200} placeholder="如 斜面培养基消后 PH" />
          </Form.Item>
          <Form.Item name="name_en" label="名称（英文）" style={ITEM_STYLE}>
            <Input maxLength={200} placeholder="如 pH after sterilization" />
          </Form.Item>
          <Form.Item
            name="group_name"
            label="表头分组"
            style={ITEM_STYLE}
            tooltip="Excel 里的第一层表头，如 斜面培养基配制 / 一级摇瓶；同一分组的列在表格里合并显示"
          >
            <AutoComplete
              allowClear
              maxLength={100}
              placeholder="可选，如 斜面培养基配制"
              options={groups.map((group) => ({ value: group }))}
              filterOption={(input, option) =>
                String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item name="category" label="类别" style={ITEM_STYLE}>
            <Select options={CATEGORY_OPTIONS} />
          </Form.Item>
          <Form.Item name="value_type" label="值类型" style={ITEM_STYLE}>
            <Segmented
              block
              options={[
                { value: 'number', label: '数值（带标准限）' },
                { value: 'text', label: '文字判定' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="unit"
            label="单位"
            style={ITEM_STYLE}
            tooltip="数值列填写，如 ℃ / rpm / % / min；文字列不需要单位"
          >
            <Input maxLength={32} disabled={!isNumber} placeholder="如 ℃ / rpm / %" />
          </Form.Item>
        </div>

        <div className={BLOCK_LABEL}>标准与预警</div>
        <Form.Item
          name="spec_text"
          label="标准原文"
          style={ITEM_STYLE}
          tooltip="录入表单和汇总表头都会显示这段原文"
        >
          <Input
            maxLength={200}
            placeholder={
              isNumber
                ? '如 6.6±0.4 / 20-30分钟 / ≤5.0%（离开输入框会自动识别上下限）'
                : '如 符合规定 / 无杂菌生长'
            }
            onBlur={(event) => handleSpecBlur(event.target.value)}
            onChange={() => {
              if (parsedHint) setParsedHint(null)
            }}
          />
        </Form.Item>
        {parsedHint && (
          <div className="-mt-2 mb-3 text-[12px] text-[var(--color-success)]">{parsedHint}</div>
        )}
        {isNumber ? (
          <>
            <div className="grid grid-cols-4 gap-x-4">
              <Form.Item name="spec_min" label="标准下限" style={ITEM_STYLE}>
                <InputNumber style={{ width: '100%' }} placeholder="≥" />
              </Form.Item>
              <Form.Item
                name="spec_max"
                label="标准上限"
                style={ITEM_STYLE}
                dependencies={['spec_min']}
                rules={[
                  {
                    validator: async (_, value: number | null) => {
                      const min = form.getFieldValue('spec_min') as number | null | undefined
                      if (value != null && min != null && value < min) {
                        throw new Error('上限不能小于下限')
                      }
                    },
                  },
                ]}
              >
                <InputNumber style={{ width: '100%' }} placeholder="≤" />
              </Form.Item>
              <Form.Item
                name="oot_min"
                label="OOT 下限"
                style={ITEM_STYLE}
                tooltip="仅预警：超出该线但仍在标准内时标黄，可不填"
              >
                <InputNumber style={{ width: '100%' }} placeholder="可不填" />
              </Form.Item>
              <Form.Item
                name="oot_max"
                label="OOT 上限"
                style={ITEM_STYLE}
                tooltip="仅预警：超出该线但仍在标准内时标黄，可不填"
              >
                <InputNumber style={{ width: '100%' }} placeholder="可不填" />
              </Form.Item>
            </div>
            <div className="grid grid-cols-3 gap-x-4">
              <Form.Item
                name="nd_policy"
                label="未检出统计口径"
                style={ITEM_STYLE}
                tooltip="数值列录入「未检出」等文字结果时，统计（均值/±3σ/OOT）如何处理；原始记录始终保留文字"
              >
                <Select
                  options={[
                    { value: 'zero', label: '按 0 计入统计' },
                    { value: 'exclude', label: '不进统计' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="quick_values"
                label="快捷文字结果"
                style={ITEM_STYLE}
                tooltip="录入页在该列显示的快捷按钮，也是允许录入的文字结果白名单；清空后该列只能填数字"
              >
                <Select
                  mode="tags"
                  maxCount={4}
                  tokenSeparators={[',', '，']}
                  placeholder="如 未检出、<0.5"
                />
              </Form.Item>
              <Form.Item
                name="stat_precision"
                label="统计精度（位）"
                style={ITEM_STYLE}
                tooltip="汇总表尾统计值、导出 Excel 与年度回顾报告的小数位；留空按 2 位"
              >
                <InputNumber
                  style={{ width: '100%' }}
                  min={0}
                  max={6}
                  precision={0}
                  placeholder="默认 2"
                />
              </Form.Item>
            </div>
          </>
        ) : (
          <div className="-mt-1 mb-3 rounded-md bg-[var(--color-surface)] px-3 py-2 text-[12px] text-[var(--color-steel)]">
            文字判定列只记录结论，不参与 OOS/OOT 判定与趋势图。
          </div>
        )}

        <div className={BLOCK_LABEL}>标记</div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <Form.Item name="trend_enabled" valuePropName="checked" noStyle>
            <Checkbox disabled={!isNumber}>纳入趋势图</Checkbox>
          </Form.Item>
          <Form.Item name="required" valuePropName="checked" noStyle>
            <Checkbox>录入时必填</Checkbox>
          </Form.Item>
          {item && (
            <Form.Item name="is_active" valuePropName="checked" noStyle>
              <Checkbox>启用（停用后保留历史值）</Checkbox>
            </Form.Item>
          )}
        </div>
        <Collapse
          ghost
          size="small"
          className="-mx-3 mt-2"
          items={[
            {
              key: 'advanced',
              forceRender: true,
              label: (
                <span className="text-[12px] text-[var(--color-steel)]">
                  更多设置（列编码 / 列顺序）
                </span>
              ),
              children: (
                <div className="grid grid-cols-2 gap-x-4">
                  <Form.Item
                    name="code"
                    label="列编码"
                    style={ITEM_STYLE}
                    tooltip="导入导出匹配时使用；留空自动生成。MIN/MAX 成对列用 #min / #max 后缀"
                  >
                    <Input maxLength={64} placeholder="留空自动生成" />
                  </Form.Item>
                  <Form.Item
                    name="sort_order"
                    label="列顺序"
                    style={ITEM_STYLE}
                    tooltip="数值越小越靠前；留空追加到段尾，也可以用列表里的上移/下移调整"
                  >
                    <InputNumber style={{ width: '100%' }} min={0} placeholder="留空追加到段尾" />
                  </Form.Item>
                </div>
              ),
            },
          ]}
        />
        <div className="mt-3 text-[12px] leading-[1.6] text-[var(--color-steel)]">
          {isNumber
            ? '录入时填数字，也可填「未检出」等文字结果（按上面口径参与统计）；数值超标准限判 OOS，超 OOT 线判预警。'
            : '文字列只记录结论，不设标准限；需要标准限请改为数值类型。'}
        </div>
      </Form>
      </ConfigProvider>
    </Modal>
  )
}
