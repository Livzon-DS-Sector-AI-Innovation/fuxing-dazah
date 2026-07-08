'use client'

import { useMemo, useRef, useState } from 'react'
import { App, Button, Input, InputNumber, Modal, Select, Space, Table, Tag, DatePicker } from 'antd'
import { PlusOutlined, CopyOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import {
  BatchCreateItem,
  GasDetectorBatchCreateItem,
  BatchCreateRowResult,
  InstrumentRecord,
  GasDetectorRecord,
} from '@/types/meter'
import {
  batchCreateInstruments,
  batchCreateGasDetectors,
  getInstruments,
  getGasDetectors,
} from '@/actions/meter'
import { DepartmentSelect } from './DepartmentSelect'
import dayjs from 'dayjs'

// ── 行数据 ──

type RowItem = BatchCreateItem & GasDetectorBatchCreateItem & { _key: number }

function emptyInstrumentRow(dept: string, key: number): RowItem {
  return {
    _key: key,
    department: dept,
    instrument_name: '',
    asset_number: null,
    model_spec: null,
    measurement_range: null,
    accuracy_grade: null,
    serial_number: null,
    calibration_cycle_months: null,
    location: null,
    manufacturer: null,
    status: null,
    color_marking: null,
    calibration_date: null,
    calibration_unit: null,
    calibration_result: null,
    next_calibration_date: null,
  }
}

function emptyGasDetectorRow(dept: string, key: number): RowItem {
  return {
    _key: key,
    department: dept,
    instrument_name: '',
    detection_model: null,
    measurement_range: null,
    product_number: null,
    installation_type: null,
    installation_location: null,
    medium: null,
    calibration_factor: null,
    manufacturer_supplier: null,
    calibration_date: null,
    calibration_result: null,
    detection_unit: null,
    next_calibration_date: null,
    manufacturer: null,
  }
}

// ── Props ──

interface Props {
  open: boolean
  source: 'instrument' | 'gas_detector'
  onClose: () => void
}

// ── 工具：从 row 中 pick 指定 keys ──

function pickRow(row: RowItem, keys: string[]): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const k of keys) result[k] = (row as unknown as Record<string, unknown>)[k] ?? null
  return result
}

// ── 组件 ──

export function BatchCreateModal({ open, source, onClose }: Props) {
  const { message } = App.useApp()
  const isInstrument = source === 'instrument'

  const [department, setDepartment] = useState<string>('')
  const [rows, setRows] = useState<RowItem[]>([])
  const keyCounter = useRef(0)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<BatchCreateRowResult[] | null>(null)

  // ── 部门变更时重置行 ──

  const handleDeptChange = (dept: string) => {
    setDepartment(dept)
    setResult(null)
    const emptyFn = isInstrument ? emptyInstrumentRow : emptyGasDetectorRow
    const initial: RowItem[] = []
    for (let i = 0; i < 5; i++) initial.push(emptyFn(dept, ++keyCounter.current))
    setRows(initial)
    loadTemplates(dept)
  }

  // ── 更新单行某字段 ──

  const updateRow = (index: number, field: string, value: unknown) => {
    setRows(prev => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)))
  }

  // ── 添加行 / 复制上一行 ──

  const addRow = () => {
    const emptyFn = isInstrument ? emptyInstrumentRow : emptyGasDetectorRow
    setRows(prev => [...prev, emptyFn(department, ++keyCounter.current)])
  }

  const copyPrev = () => {
    if (rows.length === 0) return
    const last = rows[rows.length - 1]
    const reset = isInstrument
      ? { asset_number: null, instrument_name: '', serial_number: null }
      : { product_number: null, instrument_name: '' }
    setRows(prev => [...prev, { ...last, _key: ++keyCounter.current, ...reset }])
  }

  // ── 模板（从已有记录复制公共字段） ──

  const [templates, setTemplates] = useState<(InstrumentRecord | GasDetectorRecord)[]>([])

  const handleTemplateSelect = (id: string) => {
    if (!id) return
    const t = templates.find(r => r.id === id)
    if (!t) return
    if (isInstrument) {
      const inst = t as InstrumentRecord
      setRows(prev => prev.map(r => ({
        ...r,
        model_spec: inst.model_spec ?? r.model_spec,
        measurement_range: inst.measurement_range ?? r.measurement_range,
        accuracy_grade: inst.accuracy_grade ?? r.accuracy_grade,
        calibration_cycle_months: inst.calibration_cycle_months ?? r.calibration_cycle_months,
        manufacturer: inst.manufacturer ?? r.manufacturer,
        status: inst.status ?? r.status,
        color_marking: inst.color_marking ?? r.color_marking,
        calibration_unit: inst.calibration_unit ?? r.calibration_unit,
      })))
    } else {
      const gd = t as GasDetectorRecord
      setRows(prev => prev.map(r => ({
        ...r,
        detection_model: gd.detection_model ?? r.detection_model,
        measurement_range: gd.measurement_range ?? r.measurement_range,
        installation_type: gd.installation_type ?? r.installation_type,
        medium: gd.medium ?? r.medium,
        calibration_factor: gd.calibration_factor ?? r.calibration_factor,
        manufacturer_supplier: gd.manufacturer_supplier ?? r.manufacturer_supplier,
        detection_unit: gd.detection_unit ?? r.detection_unit,
        manufacturer: gd.manufacturer ?? r.manufacturer,
      })))
    }
    message.success('已套用模板字段')
  }

  const loadTemplates = async (dept: string) => {
    try {
      if (isInstrument) {
        const res = await getInstruments({ department: dept, page_size: 50 })
        setTemplates(res.items)
      } else {
        const res = await getGasDetectors({ department: dept, page_size: 50 })
        setTemplates(res.items)
      }
    } catch { setTemplates([]) }
  }

  // ── 提交 ──

  const handleSubmit = async () => {
    const valid = rows.filter(r => r.instrument_name.trim())
    if (valid.length === 0) { message.warning('请至少填写一条器具名称'); return }
    setSubmitting(true)
    try {
      if (isInstrument) {
        const instKeys = Object.keys(emptyInstrumentRow('', 0)).filter(k => k !== '_key')
        const items: BatchCreateItem[] = valid.map(r => ({
          ...pickRow(r, instKeys),
          department: r.department,
        } as BatchCreateItem))
        const data = await batchCreateInstruments(items)
        setResult(data.results)
        message.success(`新增 ${data.created} 条，跳过 ${data.skipped} 条`)
      } else {
        const gdKeys = Object.keys(emptyGasDetectorRow('', 0)).filter(k => k !== '_key')
        const items: GasDetectorBatchCreateItem[] = valid.map(r => ({
          ...pickRow(r, gdKeys),
          department: r.department,
        } as GasDetectorBatchCreateItem))
        const data = await batchCreateGasDetectors(items)
        setResult(data.results)
        message.success(`新增 ${data.created} 条，跳过 ${data.skipped} 条`)
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    setResult(null)
    setRows([])
    onClose()
  }

  // ── 表格列定义 ──

  const columns: TableColumnsType<RowItem> = useMemo(() => {
    if (isInstrument) {
      return [
        { title: '#', width: 40, render: (_: unknown, __: unknown, i: number) => <span style={{ color: '#999' }}>{i + 1}</span> },
        { title: '资产编号', width: 130, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.asset_number ?? ''} onChange={e => updateRow(i, 'asset_number', e.target.value || null)} placeholder="可选" /> },
        { title: <><span style={{ color: 'red' }}>*</span> 器具名称</>, width: 150, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.instrument_name} onChange={e => updateRow(i, 'instrument_name', e.target.value)} placeholder="必填" status={r.instrument_name ? '' : 'error'} /> },
        { title: '型号规格', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.model_spec ?? ''} onChange={e => updateRow(i, 'model_spec', e.target.value || null)} /> },
        { title: '测量范围', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.measurement_range ?? ''} onChange={e => updateRow(i, 'measurement_range', e.target.value || null)} /> },
        { title: '精度等级', width: 90, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.accuracy_grade ?? ''} onChange={e => updateRow(i, 'accuracy_grade', e.target.value || null)} /> },
        { title: '出厂编号', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.serial_number ?? ''} onChange={e => updateRow(i, 'serial_number', e.target.value || null)} /> },
        { title: '检定周期(月)', width: 100, render: (_: unknown, r: RowItem, i: number) => <InputNumber size="small" min={1} style={{ width: '100%' }} value={r.calibration_cycle_months as number | null} onChange={v => updateRow(i, 'calibration_cycle_months', v)} /> },
        { title: '使用地点', width: 130, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.location ?? ''} onChange={e => updateRow(i, 'location', e.target.value || null)} /> },
        { title: '制造商', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.manufacturer ?? ''} onChange={e => updateRow(i, 'manufacturer', e.target.value || null)} /> },
        { title: '状态', width: 80, render: (_: unknown, r: RowItem, i: number) => (
          <Select size="small" style={{ width: 80 }} value={(r as BatchCreateItem).status || undefined} onChange={v => updateRow(i, 'status', v || null)} allowClear placeholder="-">
            <Select.Option value="在用">在用</Select.Option>
            <Select.Option value="停用">停用</Select.Option>
          </Select>
        )},
        { title: '检定日期', width: 130, render: (_: unknown, r: RowItem, i: number) => <DatePicker size="small" style={{ width: '100%' }} value={r.calibration_date ? dayjs(r.calibration_date) : null} onChange={d => updateRow(i, 'calibration_date', d?.format('YYYY-MM-DD') ?? null)} /> },
        { title: '检定单位', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.calibration_unit ?? ''} onChange={e => updateRow(i, 'calibration_unit', e.target.value || null)} /> },
        { title: '检定结论', width: 90, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.calibration_result ?? ''} onChange={e => updateRow(i, 'calibration_result', e.target.value || null)} /> },
        { title: '下次检定日期', width: 130, render: (_: unknown, r: RowItem, i: number) => <DatePicker size="small" style={{ width: '100%' }} value={r.next_calibration_date ? dayjs(r.next_calibration_date) : null} onChange={d => updateRow(i, 'next_calibration_date', d?.format('YYYY-MM-DD') ?? null)} /> },
        { title: '备注', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.remark ?? ''} onChange={e => updateRow(i, 'remark', e.target.value || null)} placeholder="可选" /> },
      ]
    }
    // gas_detector
    return [
      { title: '#', width: 40, render: (_: unknown, __: unknown, i: number) => <span style={{ color: '#999' }}>{i + 1}</span> },
      { title: <><span style={{ color: 'red' }}>*</span> 器具名称</>, width: 150, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.instrument_name} onChange={e => updateRow(i, 'instrument_name', e.target.value)} placeholder="必填" status={r.instrument_name ? '' : 'error'} /> },
      { title: '检测型号', width: 130, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.detection_model ?? ''} onChange={e => updateRow(i, 'detection_model', e.target.value || null)} /> },
      { title: '量程', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.measurement_range ?? ''} onChange={e => updateRow(i, 'measurement_range', e.target.value || null)} /> },
      { title: '产品编号', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.product_number ?? ''} onChange={e => updateRow(i, 'product_number', e.target.value || null)} /> },
      { title: '安装方式', width: 100, render: (_: unknown, r: RowItem, i: number) => (
        <Select size="small" style={{ width: '100%' }} value={r.installation_type || undefined} onChange={v => updateRow(i, 'installation_type', v || null)} allowClear placeholder="-">
          <Select.Option value="固定式">固定式</Select.Option>
          <Select.Option value="便携式">便携式</Select.Option>
        </Select>
      )},
      { title: '安装位置', width: 150, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.installation_location ?? ''} onChange={e => updateRow(i, 'installation_location', e.target.value || null)} /> },
      { title: '使用介质', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.medium ?? ''} onChange={e => updateRow(i, 'medium', e.target.value || null)} /> },
      { title: '标定系数', width: 100, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.calibration_factor ?? ''} onChange={e => updateRow(i, 'calibration_factor', e.target.value || null)} /> },
      { title: '制造商/供应商', width: 150, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.manufacturer_supplier ?? ''} onChange={e => updateRow(i, 'manufacturer_supplier', e.target.value || null)} /> },
      { title: '制造单位', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.manufacturer ?? ''} onChange={e => updateRow(i, 'manufacturer', e.target.value || null)} /> },
      { title: '检定时间', width: 130, render: (_: unknown, r: RowItem, i: number) => <DatePicker size="small" style={{ width: '100%' }} value={r.calibration_date ? dayjs(r.calibration_date) : null} onChange={d => updateRow(i, 'calibration_date', d?.format('YYYY-MM-DD') ?? null)} /> },
      { title: '检测单位', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.detection_unit ?? ''} onChange={e => updateRow(i, 'detection_unit', e.target.value || null)} /> },
      { title: '检定结论', width: 90, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.calibration_result ?? ''} onChange={e => updateRow(i, 'calibration_result', e.target.value || null)} /> },
      { title: '下次检定时间', width: 130, render: (_: unknown, r: RowItem, i: number) => <DatePicker size="small" style={{ width: '100%' }} value={r.next_calibration_date ? dayjs(r.next_calibration_date) : null} onChange={d => updateRow(i, 'next_calibration_date', d?.format('YYYY-MM-DD') ?? null)} /> },
      { title: '备注', width: 120, render: (_: unknown, r: RowItem, i: number) => <Input size="small" value={r.remark ?? ''} onChange={e => updateRow(i, 'remark', e.target.value || null)} placeholder="可选" /> },
    ]
  }, [isInstrument])

  // ── 结果列 ──

  const resultCols: TableColumnsType<BatchCreateRowResult> = [
    { title: '#', dataIndex: 'index', width: 50, render: (v: number) => v + 1 },
    { title: '编号', dataIndex: 'asset_number', width: 130, render: (v: string | null) => v || '-' },
    { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color={s === 'created' ? 'green' : 'orange'}>{s === 'created' ? '成功' : '跳过'}</Tag> },
    { title: '说明', dataIndex: 'message', ellipsis: true, render: (v: string | null) => v || '-' },
  ]

  const title = isInstrument ? '批量新增标准计量器具' : '批量新增有毒有害可燃探测器'
  const scrollX = isInstrument ? 1720 : 1820

  // ── 模板标签 ──

  const templateLabel = isInstrument
    ? (t: InstrumentRecord | GasDetectorRecord) => {
        const inst = t as InstrumentRecord
        return `[${inst.asset_number}] ${inst.instrument_name}`
      }
    : (t: InstrumentRecord | GasDetectorRecord) => {
        const gd = t as GasDetectorRecord
        return `[${gd.product_number ?? '-'}] ${gd.instrument_name}`
      }

  return (
    <Modal
      title={title}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={isInstrument ? 1400 : 1500}
      destroyOnHidden
    >
      {!result ? (
        <Space orientation="vertical" style={{ width: '100%' }} size="small">
          <Space>
            <span>部门：</span>
            <DepartmentSelect
              value={department || undefined}
              onChange={handleDeptChange}
              source={source}
            />
            <Select
              placeholder="从已有记录复制模板"
              style={{ width: 300 }}
              onChange={handleTemplateSelect}
              disabled={!department}
              allowClear
              showSearch
              options={templates.map(t => ({ label: templateLabel(t), value: t.id }))}
              filterOption={(input, option) => (option?.label as string)?.toLowerCase().includes(input.toLowerCase())}
            />
          </Space>

          <Table<RowItem>
            rowKey="_key"
            columns={columns}
            dataSource={rows}
            size="small"
            scroll={{ x: scrollX, y: 400 }}
            pagination={false}
          />

          <Space>
            <Button icon={<PlusOutlined />} onClick={addRow}>添加行</Button>
            <Button icon={<CopyOutlined />} onClick={copyPrev} disabled={rows.length === 0}>复制上一行</Button>
            <span style={{ color: '#999', marginLeft: 8 }}>共 {rows.length} 行，{rows.filter(r => r.instrument_name.trim()).length} 行已填写</span>
            <div style={{ flex: 1 }} />
            <Button onClick={handleClose}>取消</Button>
            <Button type="primary" loading={submitting} onClick={handleSubmit} disabled={!department}>
              提交（{rows.filter(r => r.instrument_name.trim()).length} 条）
            </Button>
          </Space>
        </Space>
      ) : (
        <Table<BatchCreateRowResult>
          rowKey="index"
          columns={resultCols}
          dataSource={result}
          size="small"
          pagination={{ pageSize: 50 }}
        />
      )}
    </Modal>
  )
}
