'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import {
  App,
  Button,
  ConfigProvider,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Switch,
  Table,
  Tag,
  Spin,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  InboxOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { antdTheme } from '@/lib/antd-theme'
import {
  fetchMaterialsClient,
  fetchMaterialMovementsClient,
  fetchProductsClient,
} from '@/lib/api/production-client'
import {
  createIntermediateType,
  updateIntermediateType,
  deleteIntermediateType,
} from '@/actions/production'
import type { IntermediateType, MaterialMovement } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'

// ── 设计令牌（来自 DESIGN.md） ──
const T = {
  purple: '#5645d4',
  purpleLight: '#ede9f8',
  green: '#1aae39',
  greenLight: '#e6f7e6',
  orange: '#dd5b00',
  orangeLight: '#fff7e6',
  red: '#e03131',
  redLight: '#fff1f0',
  ink: '#1a1a1a',
  charcoal: '#5d5b54',
  steel: '#787671',
  stone: '#a4a097',
  mute: '#bbb8b1',
  canvas: '#ffffff',
  surface: '#fafaf9',
  hairline: '#e5e3df',
  navy: '#0a1530',
}

// ── 表单弹窗（结构保持，样式微调） ──

interface FormModalProps {
  open: boolean
  editItem: IntermediateType | null
  onClose: () => void
  onSaved: () => void
}

function MaterialFormModal({ open, editItem, onClose, onSaved }: FormModalProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const { data: products } = useQuery({
    queryKey: ['products-select'],
    queryFn: () => fetchProductsClient(),
    enabled: open,
  })

  const isProduct = Form.useWatch('is_product', form)

  useEffect(() => {
    if (open) {
      form.setFieldsValue(
        editItem ?? {
          code: '', name: '', category: '', default_unit: '', description: '',
          is_product: false, product_id: null,
        },
      )
    }
  }, [open, editItem, form])

  const handleOk = async () => {
    try {
      const values = await form.validateFields().catch(() => null)
      if (!values) return
      let result
      if (editItem) {
        result = await updateIntermediateType(editItem.id, values)
      } else {
        result = await createIntermediateType(values as Parameters<typeof createIntermediateType>[0])
      }
      if (result.success) {
        message.success(editItem ? '产出物已更新' : '产出物已创建')
        onSaved()
      } else {
        message.error(result.error)
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败')
    }
  }

  return (
    <Modal
      title={editItem ? '编辑产出物' : '新增产出物'}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="code" label="编码" rules={[{ required: true, message: '请输入编码' }]}>
          <Input maxLength={50} disabled={!!editItem} />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="category" label="分类">
          <Input maxLength={100} placeholder="如：发酵液、结晶粉、湿品" />
        </Form.Item>
        <Form.Item name="default_unit" label="默认单位">
          <Input maxLength={20} placeholder="如：kg、L" />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="is_product" label="标记为成品" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="product_id" label="关联产品">
          <Select
            allowClear
            placeholder="选择关联的产品"
            disabled={!isProduct}
            options={(products ?? []).map((p) => ({
              value: p.id,
              label: p.product_name,
            }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 库存概览卡片（签名元素） ──

function StockOverview({
  summary,
  unit,
}: {
  summary: { total_output: number; total_consumed: number; current_stock: number }
  unit: string
}) {
  const { total_output, total_consumed, current_stock } = summary
  const consumedPct = total_output > 0 ? (total_consumed / total_output) * 100 : 0
  const stockPct = total_output > 0 ? (current_stock / total_output) * 100 : 0
  const stockRatio = total_output > 0 ? current_stock / total_output : 0

  // 库存率颜色：≤10% 红色，≤30% 橙色，>30% 绿色
  const stockColor = stockRatio <= 0.1 ? T.red : stockRatio <= 0.3 ? T.orange : T.green

  return (
    <div style={{ marginBottom: 20 }}>
      {/* 三列统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        {([
          { label: '总产出', value: total_output, color: T.ink },
          { label: '总消耗', value: total_consumed, color: T.orange },
          { label: '当前库存', value: current_stock, color: stockColor },
        ] as const).map((stat) => (
          <div
            key={stat.label}
            style={{
              background: T.surface,
              borderRadius: 10,
              padding: '16px 20px',
              textAlign: 'center',
              border: `1px solid ${T.hairline}`,
            }}
          >
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                color: stat.color,
                lineHeight: 1.2,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {stat.value.toLocaleString('zh-CN')}
            </div>
            <div style={{ fontSize: 12, color: T.steel, marginTop: 4 }}>
              {unit}
            </div>
            <div style={{ fontSize: 13, color: T.charcoal, marginTop: 2, fontWeight: 500 }}>
              {stat.label}
            </div>
          </div>
        ))}
      </div>

      {/* 物料平衡条 */}
      <div
        style={{
          background: T.canvas,
          border: `1px solid ${T.hairline}`,
          borderRadius: 10,
          padding: '14px 20px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: T.charcoal }}>物料平衡</span>
          <span style={{ fontSize: 12, color: T.steel }}>
            库存率{' '}
            <b style={{ color: stockColor, fontVariantNumeric: 'tabular-nums' }}>
              {(stockRatio * 100).toFixed(1)}%
            </b>
          </span>
        </div>

        {/* 平衡条本体 */}
        <div
          style={{
            position: 'relative',
            height: 10,
            borderRadius: 5,
            background: T.hairline,
            overflow: 'hidden',
          }}
        >
          {/* 已消耗部分 */}
          {consumedPct > 0 && (
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                height: '100%',
                width: `${Math.min(consumedPct, 100)}%`,
                background: `linear-gradient(90deg, ${T.orange}dd, ${T.orange})`,
                borderRadius: '5px 0 0 5px',
                transition: 'width 0.4s ease',
              }}
            />
          )}
          {/* 在库部分 — 紧接已消耗之后 */}
          {stockPct > 0 && (
            <div
              style={{
                position: 'absolute',
                left: `${consumedPct}%`,
                top: 0,
                height: '100%',
                width: `${Math.min(stockPct, 100 - consumedPct)}%`,
                background: `linear-gradient(90deg, ${stockColor}, ${stockColor}dd)`,
                borderRadius: consumedPct === 0 ? '5px' : '0 5px 5px 0',
                transition: 'width 0.4s ease',
              }}
            />
          )}
        </div>

        {/* 图例 */}
        <div style={{ display: 'flex', gap: 20, marginTop: 8, fontSize: 12, color: T.steel }}>
          <span>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: T.orange, marginRight: 6 }} />
            已消耗 {total_consumed.toLocaleString('zh-CN')} {unit}
          </span>
          <span>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: stockColor, marginRight: 6 }} />
            在库 {current_stock.toLocaleString('zh-CN')} {unit}
          </span>
        </div>
      </div>
    </div>
  )
}

// ── 出入库流水表 ──

function MovementTable({ materialId }: { materialId: string }) {
  const [batchSearch, setBatchSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['material-movements', materialId, batchSearch],
    queryFn: () => fetchMaterialMovementsClient(materialId, batchSearch || undefined),
    enabled: !!materialId,
  })

  const columns: ColumnsType<MaterialMovement> = [
    {
      title: '类型', width: 64,
      render: (_, r) => (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 12,
            fontWeight: 600,
            color: r.type === 'output' ? T.green : T.orange,
          }}
        >
          <span
            style={{
              display: 'inline-block',
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: r.type === 'output' ? T.green : T.orange,
            }}
          />
          {r.type === 'output' ? '入库' : '出库'}
        </span>
      ),
    },
    {
      title: '批次号', dataIndex: 'batch_no', width: 110,
      render: (v: string | null) => (
        <span style={{ fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: 12, color: T.charcoal }}>
          {v || '-'}
        </span>
      ),
    },
    { title: '工序', dataIndex: 'node_name', width: 90, render: (v: string | null) => v || '-' },
    {
      title: '数量', width: 100,
      render: (_, r) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
          {r.quantity.toLocaleString('zh-CN')} <span style={{ color: T.steel, fontWeight: 400 }}>{r.unit}</span>
        </span>
      ),
    },
    {
      title: '产出批号', width: 120,
      render: (_, r) => (
        <span style={{ fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: 12 }}>
          {r.type === 'output' ? (r.intermediate_batch_no || '-') : (r.source_batch_no || '-')}
        </span>
      ),
    },
    {
      title: '时间', width: 150,
      render: (_, r) => (
        <span style={{ color: T.steel, fontSize: 12 }}>
          {new Date(r.created_at).toLocaleString('zh-CN', {
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
          })}
        </span>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h4 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: T.ink }}>出入库流水</h4>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Input
            placeholder="搜索产出批号..."
            allowClear
            size="small"
            style={{ width: 180 }}
            value={batchSearch}
            onChange={(e) => setBatchSearch(e.target.value)}
          />
          {data?.movements && (
            <span style={{ fontSize: 12, color: T.steel, whiteSpace: 'nowrap' }}>
              共 {data.movements.length} 条记录
            </span>
          )}
        </div>
      </div>
      <Table
        rowKey={(r) => `${r.type}-${r.batch_id}-${r.source_output_id ?? ''}-${r.created_at}`}
        columns={columns}
        dataSource={data?.movements ?? []}
        loading={isLoading}
        pagination={{ pageSize: 15, showSizeChanger: false, size: 'small' }}
        size="small"
        locale={{ emptyText: <Empty description="暂无出入库记录" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        onRow={() => ({
          style: { cursor: 'default' },
        })}
      />
    </div>
  )
}

// ── 左侧物料清单项 ──

function MaterialListItem({
  item,
  isSelected,
  onClick,
  onEdit,
  onDelete,
}: {
  item: IntermediateType
  isSelected: boolean
  onClick: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 14px',
        cursor: 'pointer',
        borderRadius: 8,
        marginBottom: 2,
        background: isSelected ? T.purpleLight : 'transparent',
        borderLeft: isSelected ? `3px solid ${T.purple}` : '3px solid transparent',
        transition: 'background 0.15s, border-color 0.15s',
      }}
      onMouseEnter={(e) => {
        if (!isSelected) (e.currentTarget as HTMLElement).style.background = T.surface
      }}
      onMouseLeave={(e) => {
        if (!isSelected) (e.currentTarget as HTMLElement).style.background = 'transparent'
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              fontSize: 14,
              fontWeight: isSelected ? 600 : 500,
              color: isSelected ? T.purple : T.ink,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {item.name}
          </span>
          {item.is_product && (
            <Tag
              color="green"
              style={{ fontSize: 10, lineHeight: '18px', padding: '0 6px', margin: 0, borderRadius: 4 }}
            >
              成品
            </Tag>
          )}
        </div>
        <div style={{ fontSize: 12, color: T.steel, marginTop: 2 }}>
          {item.code}
          {item.category && (
            <span style={{ marginLeft: 8, color: T.stone }}>{item.category}</span>
          )}
        </div>
      </div>

      {/* 快捷操作 — hover 时显示 */}
      <div
        style={{ display: 'flex', gap: 2, flexShrink: 0, marginLeft: 8 }}
        onClick={(e) => e.stopPropagation()}
      >
        <Button
          type="text"
          size="small"
          icon={<EditOutlined style={{ fontSize: 13, color: T.steel }} />}
          onClick={(e) => { e.stopPropagation(); onEdit() }}
          style={{ minWidth: 28, height: 28 }}
        />
        <Popconfirm
          title={`确定删除「${item.name}」？`}
          onConfirm={(e) => { e?.stopPropagation(); onDelete() }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined style={{ fontSize: 13 }} />}
            onClick={(e) => e.stopPropagation()}
            style={{ minWidth: 28, height: 28 }}
          />
        </Popconfirm>
      </div>
    </div>
  )
}

// ── 右侧空状态 ──

function DetailEmpty() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        minHeight: 420,
        color: T.stone,
      }}
    >
      <InboxOutlined style={{ fontSize: 56, color: T.mute, marginBottom: 16 }} />
      <div style={{ fontSize: 15, fontWeight: 500, color: T.charcoal, marginBottom: 4 }}>
        选择左侧产出物
      </div>
      <div style={{ fontSize: 13, color: T.steel }}>
        查看库存详情与出入库流水
      </div>
    </div>
  )
}

// ── 右侧详情面板 ──

function DetailPanel({ material }: { material: IntermediateType }) {
  const { data, isLoading } = useQuery({
    queryKey: ['material-movements', material.id],
    queryFn: () => fetchMaterialMovementsClient(material.id),
    enabled: !!material.id,
  })

  return (
    <Spin spinning={isLoading}>
      {/* 头部：名称 + 元信息 + 操作 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 20,
          paddingBottom: 16,
          borderBottom: `1px solid ${T.hairline}`,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <h3 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: T.ink }}>
              {material.name}
            </h3>
            {material.is_product && (
              <Tag color="green" style={{ borderRadius: 4 }}>成品</Tag>
            )}
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: T.charcoal }}>
            <span>
              <span style={{ color: T.steel }}>编码</span> {material.code}
            </span>
            <span>
              <span style={{ color: T.steel }}>分类</span> {material.category || '-'}
            </span>
            <span>
              <span style={{ color: T.steel }}>单位</span> {material.default_unit || '-'}
            </span>
            {material.product_name && (
              <span>
                <span style={{ color: T.steel }}>关联产品</span> {material.product_name}
              </span>
            )}
          </div>
          {material.description && (
            <div style={{ fontSize: 13, color: T.stone, marginTop: 6 }}>{material.description}</div>
          )}
        </div>
      </div>

      {/* 库存概览 */}
      {data?.summary ? (
        <StockOverview
          summary={data.summary}
          unit={material.default_unit || data.material.default_unit || ''}
        />
      ) : !isLoading ? (
        <div
          style={{
            textAlign: 'center',
            padding: '32px 0',
            color: T.stone,
            fontSize: 13,
            background: T.surface,
            borderRadius: 10,
            marginBottom: 20,
          }}
        >
          暂无库存数据 — 该产出物尚未在任何批次中产出或消耗
        </div>
      ) : null}

      {/* 出入库流水 */}
      <MovementTable materialId={material.id} />
    </Spin>
  )
}

// ── 主页面 ──

function MaterialsContent() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [editItem, setEditItem] = useState<IntermediateType | null>(null)
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<IntermediateType | null>(null)
  const [filter, setFilter] = useState<'all' | 'intermediate' | 'product'>('all')

  const { data, isLoading } = useQuery({
    queryKey: ['materials', keyword],
    queryFn: () => fetchMaterialsClient({ keyword, page_size: 200 }),
  })

  const deleteMut = useMutation({
    mutationFn: deleteIntermediateType,
    onSuccess: (_data, deletedId) => {
      message.success('产出物已删除')
      if (selected && selected.id === deletedId) setSelected(null)
      queryClient.invalidateQueries({ queryKey: ['materials'] })
    },
    onError: (e: Error) => message.error(e.message),
  })

  // 按筛选条件过滤
  const filteredItems = useMemo(() => {
    const items = data?.items ?? []
    if (filter === 'product') return items.filter((i) => i.is_product)
    if (filter === 'intermediate') return items.filter((i) => !i.is_product)
    return items
  }, [data, filter])

  // 筛选项计数
  const allCount = data?.items?.length ?? 0
  const intermediateCount = data?.items?.filter((i) => !i.is_product).length ?? 0
  const productCount = data?.items?.filter((i) => i.is_product).length ?? 0

  const hasAutoSelected = useRef(false)
  // 首次加载或筛选导致当前选中不可见时，自动选择第一个
  useEffect(() => {
    if (filteredItems.length === 0) return
    const stillVisible = selected && filteredItems.some(it => it.id === selected.id)
    if (!hasAutoSelected.current || !stillVisible) {
      hasAutoSelected.current = true
      setSelected(filteredItems[0])
    }
  }, [filteredItems, selected])

  const handleSaved = useCallback(() => {
    setModalOpen(false)
    setEditItem(null)
    queryClient.invalidateQueries({ queryKey: ['materials'] })
    if (selected) {
      queryClient.invalidateQueries({ queryKey: ['material-movements', selected.id] })
    }
  }, [queryClient, selected])

  return (
    <div>
      {/* 页头 */}
      <div style={{ marginBottom: 20 }}>
        <h2
          style={{
            fontSize: 22,
            fontWeight: 700,
            margin: '0 0 4px',
            color: T.ink,
            letterSpacing: '-0.3px',
          }}
        >
          产出物管理
        </h2>
        <span style={{ color: T.steel, fontSize: 14 }}>
          管理中间体字典，追踪批次库存与物料追溯
        </span>
      </div>

      {/* 双栏布局 */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* ── 左侧面板 ── */}
        <div
          style={{
            width: 320,
            flexShrink: 0,
            background: T.canvas,
            borderRadius: 12,
            border: `1px solid ${T.hairline}`,
            overflow: 'hidden',
          }}
        >
          {/* 搜索 & 操作 */}
          <div style={{ padding: '14px 14px 0' }}>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <Input
                placeholder="搜索产出物..."
                allowClear
                size="middle"
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={(e) => setKeyword((e.target as HTMLInputElement).value)}
                style={{ flex: 1 }}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => { setEditItem(null); setModalOpen(true) }}
              >
                新增
              </Button>
            </div>

            {/* 筛选选项卡 */}
            <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
              {([
                { key: 'all', label: '全部', count: allCount },
                { key: 'intermediate', label: '中间体', count: intermediateCount },
                { key: 'product', label: '成品', count: productCount },
              ] as const).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setFilter(tab.key)}
                  style={{
                    padding: '4px 12px',
                    borderRadius: 6,
                    border: 'none',
                    fontSize: 12,
                    fontWeight: filter === tab.key ? 600 : 400,
                    color: filter === tab.key ? T.purple : T.charcoal,
                    background: filter === tab.key ? T.purpleLight : 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                    fontFamily: 'inherit',
                    lineHeight: '22px',
                  }}
                >
                  {tab.label}
                  <span style={{ marginLeft: 4, opacity: 0.6, fontSize: 11 }}>{tab.count}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 分隔线 */}
          <div style={{ height: 1, background: T.hairline, margin: '0 14px' }} />

          {/* 清单列表 */}
          <div style={{ maxHeight: 520, overflowY: 'auto', padding: '6px 8px' }}>
            {isLoading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin size="small" />
              </div>
            ) : filteredItems.length === 0 ? (
              <div style={{ padding: '32px 16px', textAlign: 'center' }}>
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={keyword ? '未找到匹配的产出物' : '暂无产出物'}
                />
              </div>
            ) : (
              filteredItems.map((item) => (
                <MaterialListItem
                  key={item.id}
                  item={item}
                  isSelected={selected?.id === item.id}
                  onClick={() => setSelected(item)}
                  onEdit={() => { setEditItem(item); setModalOpen(true) }}
                  onDelete={() => deleteMut.mutate(item.id)}
                />
              ))
            )}
          </div>

          {/* 底部计数 */}
          <div
            style={{
              padding: '8px 14px',
              fontSize: 11,
              color: T.stone,
              borderTop: `1px solid ${T.hairline}`,
              textAlign: 'right',
            }}
          >
            {filteredItems.length} 项
          </div>
        </div>

        {/* ── 右侧详情面板 ── */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            background: T.canvas,
            borderRadius: 12,
            border: `1px solid ${T.hairline}`,
            padding: 20,
            minHeight: 560,
          }}
        >
          {selected ? (
            <DetailPanel material={selected} />
          ) : (
            <DetailEmpty />
          )}
        </div>
      </div>

      {/* 表单弹窗 */}
      <MaterialFormModal
        open={modalOpen}
        editItem={editItem}
        onClose={() => { setModalOpen(false); setEditItem(null) }}
        onSaved={handleSaved}
      />
    </div>
  )
}

export function MaterialsPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <MaterialsContent />
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}
