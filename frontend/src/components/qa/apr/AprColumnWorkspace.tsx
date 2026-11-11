'use client'

import { useMemo, useState } from 'react'
import {
  App,
  Button,
  Dropdown,
  Empty,
  Input,
  Skeleton,
  Space,
  Table,
  Tooltip,
} from 'antd'
import type { MenuProps } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CheckCircleOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  LineChartOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  StopOutlined,
} from '@ant-design/icons'
import clsx from 'clsx'
import { actionError, PILL } from '@/components/qa/deviation/shared'
import { createAprItem, deleteAprItem, updateAprItem } from '@/actions/qa-apr'
import type { AprItem, AprProduct, AprSection } from '@/types/qa-apr'
import { AprMeta, AprSheet } from './AprChrome'
import { AprItemModal } from './AprItemModal'
import {
  CATEGORY_LABEL,
  CATEGORY_PILL,
  confirmAsync,
  DANGER_OK_PROPS,
  DATA_KIND_LABEL,
  formatRange,
  isAutoCode,
  itemMissingSpec,
  itemSpecText,
} from './AprConfigShared'

type ItemFilter = 'all' | 'number' | 'text' | 'missing'

interface AprColumnWorkspaceProps {
  product: AprProduct | null
  section: AprSection | null
  loading: boolean
  onEditSection: () => void
  onCopySection: () => void
  onDeleteSection: () => void
  onCreateSection: () => void
  onCopyTemplate: () => void
  onChanged: () => void
}

const CHIP_BASE =
  'inline-flex items-center gap-1 rounded-full px-2.5 py-[3px] text-[12px] leading-[18px] transition-colors cursor-pointer'
const CHIP_OFF = 'border border-[var(--color-hairline)] text-[var(--color-steel)] hover:bg-[var(--color-surface)]'
const CHIP_ON = 'border border-[var(--color-ink)] bg-[var(--color-ink)] text-white'

/**
 * 右侧列定义编辑区：一个模板段的全部列都在这一屏，支持搜索/筛选、
 * 行级复制与排序，新增列走轻量弹窗，批量录入走 Excel 粘贴。
 */
export function AprColumnWorkspace({
  product,
  section,
  loading,
  onEditSection,
  onCopySection,
  onDeleteSection,
  onCreateSection,
  onCopyTemplate,
  onChanged,
}: AprColumnWorkspaceProps) {
  const { message, modal } = App.useApp()
  const [keyword, setKeyword] = useState('')
  const [filter, setFilter] = useState<ItemFilter>('all')
  const [itemModal, setItemModal] = useState<{ item: AprItem | null } | null>(null)
  const [busyItemId, setBusyItemId] = useState<string | null>(null)

  const items = useMemo(() => section?.items ?? [], [section])

  const groups = useMemo(() => {
    const seen = new Set<string>()
    for (const item of items) {
      const group = item.group_name?.trim()
      if (group) seen.add(group)
    }
    return Array.from(seen)
  }, [items])

  const numberCount = items.filter((item) => item.value_type === 'number').length
  const textCount = items.length - numberCount
  const missingCount = items.filter(itemMissingSpec).length
  const inactiveCount = items.filter((item) => !item.is_active).length

  const filtering = filter !== 'all' || keyword.trim().length > 0

  const visibleItems = useMemo(() => {
    const text = keyword.trim().toLowerCase()
    return items.filter((item) => {
      if (filter === 'number' && item.value_type !== 'number') return false
      if (filter === 'text' && item.value_type !== 'text') return false
      if (filter === 'missing' && !itemMissingSpec(item)) return false
      if (!text) return true
      return [item.name_cn, item.name_en, item.group_name, item.code]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(text)
    })
  }, [items, keyword, filter])

  /** 相邻同分组的行合并成 Excel 式的一格；空白分组不合并。 */
  const groupSpans = useMemo(() => {
    const spans = visibleItems.map(() => 1)
    let cursor = 0
    while (cursor < visibleItems.length) {
      const group = visibleItems[cursor].group_name?.trim()
      let next = cursor + 1
      if (group) {
        while (next < visibleItems.length && visibleItems[next].group_name?.trim() === group) {
          next += 1
        }
      }
      spans[cursor] = next - cursor
      for (let index = cursor + 1; index < next; index += 1) spans[index] = 0
      cursor = next
    }
    return spans
  }, [visibleItems])

  const clearFilters = () => {
    setKeyword('')
    setFilter('all')
  }

  const handleDuplicate = async (item: AprItem) => {
    setBusyItemId(item.id)
    try {
      const result = await createAprItem({
        section_id: section!.id,
        name_cn: `${item.name_cn}（副本）`,
        name_en: item.name_en ?? null,
        group_name: item.group_name ?? null,
        category: item.category,
        value_type: item.value_type,
        unit: item.unit ?? null,
        spec_text: item.spec_text ?? null,
        spec_min: item.value_type === 'number' ? item.spec_min : null,
        spec_max: item.value_type === 'number' ? item.spec_max : null,
        oot_min: item.value_type === 'number' ? item.oot_min : null,
        oot_max: item.value_type === 'number' ? item.oot_max : null,
        nd_policy: item.value_type === 'number' ? item.nd_policy : undefined,
        quick_values: item.value_type === 'number' ? item.quick_values : undefined,
        trend_enabled: item.trend_enabled,
        required: item.required,
        // 排到原列后面；编码交给后端生成
        sort_order: item.sort_order + 1,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('已复制为新列，可直接修改名称与标准')
      onChanged()
    } finally {
      setBusyItemId(null)
    }
  }

  /** 上移/下移：重排整段顺序后只提交有变化的行，避免 sort_order 重复导致排序错乱。 */
  const handleMove = async (item: AprItem, direction: -1 | 1) => {
    const index = items.findIndex((row) => row.id === item.id)
    const targetIndex = index + direction
    if (index < 0 || targetIndex < 0 || targetIndex >= items.length) return
    const next = [...items]
    const [moved] = next.splice(index, 1)
    next.splice(targetIndex, 0, moved)
    const updates = next
      .map((row, position) => ({ row, sortOrder: (position + 1) * 10 }))
      .filter(({ row, sortOrder }) => row.sort_order !== sortOrder)
    if (updates.length === 0) return

    setBusyItemId(item.id)
    try {
      const results = await Promise.all(
        updates.map(({ row, sortOrder }) => updateAprItem(row.id, { sort_order: sortOrder })),
      )
      const failure = results.find((result) => !result.success)
      if (failure && !failure.success) {
        message.error(actionError(failure))
        return
      }
      onChanged()
    } finally {
      setBusyItemId(null)
    }
  }

  const handleToggleActive = async (item: AprItem) => {
    setBusyItemId(item.id)
    try {
      const result = await updateAprItem(item.id, { is_active: !item.is_active })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(item.is_active ? '已停用，历史值保留' : '已启用')
      onChanged()
    } finally {
      setBusyItemId(null)
    }
  }

  const handleDelete = (item: AprItem) => {
    confirmAsync(modal, {
      title: `删除列「${item.name_cn}」？`,
      content: '没有录入过值的列会直接删除；已录入过值的列会转为「停用」，历史数据仍可查看。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: DANGER_OK_PROPS,
      onOk: async () => {
        const result = await deleteAprItem(item.id)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        // 后端规则：有值的列删除时转为停用；本来就停用的列无法再从返回值区分，按已删除提示
        const deactivated = item.is_active && result.data?.is_active === false
        message.success(deactivated ? '该列已录入过值，已转为停用，历史保留' : '列定义已删除')
        onChanged()
      },
    })
  }

  const rowMenu = (item: AprItem): MenuProps => {
    const position = items.findIndex((row) => row.id === item.id)
    return {
      items: [
        { key: 'copy', label: '复制为新列', icon: <CopyOutlined /> },
        { type: 'divider' },
        {
          key: 'up',
          label: '上移',
          icon: <ArrowUpOutlined />,
          disabled: filtering || position <= 0,
        },
        {
          key: 'down',
          label: '下移',
          icon: <ArrowDownOutlined />,
          disabled: filtering || position < 0 || position >= items.length - 1,
        },
        { type: 'divider' },
        {
          key: 'toggle',
          label: item.is_active ? '停用此列' : '启用此列',
          icon: item.is_active ? <StopOutlined /> : <CheckCircleOutlined />,
        },
        { key: 'delete', label: '删除', icon: <DeleteOutlined />, danger: true },
      ],
      onClick: ({ key, domEvent }) => {
        domEvent.stopPropagation()
        if (key === 'copy') void handleDuplicate(item)
        if (key === 'up') void handleMove(item, -1)
        if (key === 'down') void handleMove(item, 1)
        if (key === 'toggle') void handleToggleActive(item)
        if (key === 'delete') handleDelete(item)
      },
    }
  }

  const columns: ColumnsType<AprItem> = [
    {
      title: '分组',
      dataIndex: 'group_name',
      width: 108,
      onCell: (_, index) => ({
        rowSpan: groupSpans[index ?? 0] ?? 1,
        style: { verticalAlign: 'top' },
      }),
      render: (value: string | null) =>
        value ? (
          <span className="text-[12px] leading-[18px] text-[var(--color-slate)]">{value}</span>
        ) : (
          <span className="text-[var(--color-hairline-strong)]">—</span>
        ),
    },
    {
      title: '名称',
      key: 'name',
      width: 208,
      render: (_, item) => {
        const meta = [item.name_en, !isAutoCode(item.code) ? item.code : null]
          .filter(Boolean)
          .join(' / ')
        return (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span
                className={clsx(
                  'truncate text-[13px]',
                  item.is_active ? 'font-medium text-[var(--color-ink)]' : 'text-[var(--color-stone)]',
                )}
                title={item.name_cn}
              >
                {item.name_cn}
              </span>
              {item.value_type === 'number' && item.trend_enabled && (
                <Tooltip title="纳入趋势图">
                  <LineChartOutlined style={{ color: 'var(--color-brand-purple)', fontSize: 11 }} />
                </Tooltip>
              )}
              {item.required && (
                <Tooltip title="录入必填">
                  <span style={{ color: 'var(--color-error)', lineHeight: 1 }}>*</span>
                </Tooltip>
              )}
              {!item.is_active && <span style={PILL.muted}>停用</span>}
            </div>
            {meta && (
              <div className="mt-0.5 truncate text-[11px] leading-[16px] text-[var(--color-steel)]" title={meta}>
                {meta}
              </div>
            )}
          </div>
        )
      },
    },
    {
      title: '类别',
      dataIndex: 'category',
      width: 98,
      render: (value: AprItem['category']) => (
        <span style={CATEGORY_PILL[value]}>{CATEGORY_LABEL[value]}</span>
      ),
    },
    {
      title: '值类型',
      key: 'value_type',
      width: 150,
      render: (_, item) =>
        item.value_type === 'number' ? (
          <span className="text-[12px]">
            数值
            {item.unit && <span className="text-[var(--color-steel)]">（{item.unit}）</span>}
          </span>
        ) : (
          <span className="text-[12px] text-[var(--color-steel)]">文字</span>
        ),
    },
    {
      title: '标准',
      key: 'spec',
      width: 176,
      render: (_, item) => {
        if (itemMissingSpec(item)) {
          return <span style={PILL.warning}>未设标准限</span>
        }
        if (item.category === 'info' && !item.spec_text?.trim()) {
          return <span className="text-[var(--color-hairline-strong)]">—</span>
        }
        const range = formatRange(item.spec_min, item.spec_max)
        const showRangeLine = item.value_type === 'number' && item.spec_text && range
        const oot = formatRange(item.oot_min, item.oot_max)
        return (
          <div className="min-w-0 text-[12px] leading-[18px]">
            <div className="truncate" title={itemSpecText(item) ?? ''}>
              {itemSpecText(item)}
            </div>
            {showRangeLine && <div className="text-[11px] text-[var(--color-steel)]">限度 {range}</div>}
            {oot && <div className="text-[11px] text-[var(--color-warning)]">OOT {oot}</div>}
          </div>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 96,
      render: (_, item) => (
        <div className="flex items-center gap-1">
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            disabled={busyItemId === item.id}
            onClick={() => setItemModal({ item })}
          >
            编辑
          </Button>
          <Dropdown menu={rowMenu(item)} trigger={['click']} placement="bottomRight">
            <Button
              type="text"
              size="small"
              icon={<MoreOutlined />}
              loading={busyItemId === item.id}
              aria-label="列操作"
            />
          </Dropdown>
        </div>
      ),
    },
  ]

  if (loading) {
    return (
      <AprSheet title="列定义" bleed={false} className="mt-0">
        <Skeleton active paragraph={{ rows: 6 }} />
      </AprSheet>
    )
  }

  if (!section) {
    return (
      <AprSheet title="列定义" className="mt-0">
        <div className="flex flex-col items-center px-6 py-16 text-center">
          <div className="text-[15px] font-semibold text-[var(--color-charcoal)]">
            {product ? `「${product.name}」还没有模板段` : '先在左侧选择产品，或新增一个产品'}
          </div>
          <div className="mt-1.5 max-w-[520px] text-[13px] leading-[1.6] text-[var(--color-steel)]">
            {product
              ? '模板段对应 Excel 的一张 sheet 或一个横向块。先建段，再添加列定义，或从已有产品整树复制。'
              : '产品 → 模板段 → 列定义，三层配齐后数据录入页就能按这个结构生成表单。'}
          </div>
          {product && (
            <Space className="mt-5" wrap>
              <Button icon={<CopyOutlined />} onClick={onCopyTemplate}>
                从已有产品复制模板
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={onCreateSection}>
                新建模板段
              </Button>
            </Space>
          )}
        </div>
      </AprSheet>
    )
  }

  const filterChips: { key: ItemFilter; label: string; count: number }[] = [
    { key: 'all', label: '全部', count: items.length },
    { key: 'number', label: '数值', count: numberCount },
    { key: 'text', label: '文字', count: textCount },
    { key: 'missing', label: '未设标准', count: missingCount },
  ]

  return (
    <AprSheet
      title={section.name}
      meta={
        <AprMeta
          items={[
            DATA_KIND_LABEL[section.data_kind],
            section.market,
            section.multi_row ? '一批多行' : '一批一行',
            `${items.length} 列`,
            `数值 ${numberCount} / 文字 ${textCount}`,
            missingCount > 0 ? (
              <span style={{ color: 'var(--color-warning)' }}>{missingCount} 列未设标准限</span>
            ) : (
              '标准齐全'
            ),
            inactiveCount > 0 ? `停用 ${inactiveCount}` : false,
          ]}
        />
      }
      actions={
        <Space size={6} wrap>
          <Button size="small" icon={<CopyOutlined />} onClick={onCopySection}>
            复制段
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={onEditSection}>
            编辑段
          </Button>
          <Dropdown
            trigger={['click']}
            placement="bottomRight"
            menu={{
              items: [{ key: 'delete', label: '删除此段', icon: <DeleteOutlined />, danger: true }],
              onClick: () => onDeleteSection(),
            }}
          >
            <Button size="small" type="text" icon={<MoreOutlined />} aria-label="更多段操作" />
          </Dropdown>
        </Space>
      }
      toolbar={
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            {filterChips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                onClick={() => setFilter(chip.key)}
                className={clsx(CHIP_BASE, filter === chip.key ? CHIP_ON : CHIP_OFF)}
              >
                {chip.label}
                <span className="tabular-nums opacity-70">{chip.count}</span>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              size="small"
              allowClear
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              prefix={<SearchOutlined style={{ color: 'var(--color-stone)' }} />}
              placeholder="搜索列名称或分组"
              style={{ width: 190 }}
            />
            <Button
              size="small"
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setItemModal({ item: null })}
            >
              新增列
            </Button>
          </div>
        </>
      }
      footer={
        <>
          <span>列顺序即录入表单的字段顺序；已停用的列保留历史值但不再录入。</span>
          {missingCount > 0 && (
            <button
              type="button"
              className="cursor-pointer text-[var(--color-warning)] underline-offset-2 hover:underline"
              onClick={() => setFilter('missing')}
            >
              查看未设标准限的 {missingCount} 列
            </button>
          )}
        </>
      }
      className="mt-0"
    >
      <Table<AprItem>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={visibleItems}
        pagination={false}
        scroll={{ x: 766 }}
        locale={{
          emptyText: (
            <div className="py-10">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  items.length === 0
                    ? '这个段还没有列定义'
                    : '没有匹配的列定义，换个关键词或清除筛选'
                }
              >
                {items.length === 0 ? (
                  <Space wrap>
                    <Button
                      size="small"
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setItemModal({ item: null })}
                    >
                      新增列
                    </Button>
                  </Space>
                ) : (
                  <Button size="small" onClick={clearFilters}>
                    清除筛选
                  </Button>
                )}
              </Empty>
            </div>
          ),
        }}
      />

      {itemModal && (
        <AprItemModal
          section={section}
          item={itemModal.item}
          groups={groups}
          defaultGroup={items.length > 0 ? items[items.length - 1].group_name : null}
          onClose={() => setItemModal(null)}
          onSaved={onChanged}
        />
      )}
    </AprSheet>
  )
}
