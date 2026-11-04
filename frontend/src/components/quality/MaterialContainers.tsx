'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Select, Modal, Form, DatePicker, Popconfirm, Typography, Card, Row, Col, AutoComplete, Tabs, Upload,
} from 'antd'
import { PlusOutlined, SearchOutlined, DownloadOutlined, ScanOutlined, BookOutlined, HistoryOutlined, ShoppingCartOutlined, CheckOutlined, ImportOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import { theme } from 'antd'
import { useCrossTabSignal } from './useCrossTabSignal'
import { MATERIAL_CONTAINER_STATUS_META } from '@/types/quality'
import type { MaterialContainerItem, MaterialContainerStatus, MaterialDictItem, MaterialMovementItem, MaterialRequestItem, MaterialSummaryItem, MonthlyReportItem, PurchaseSuggestion, SlowMovingItem, StocktakeSheet, SupplierItem } from '@/types/quality'
import {
  fetchMaterialContainers, generateMaterialContainers, moveMaterialContainer,
  updateMaterialContainerStatus, downloadContainerLabels, batchMoveMaterialContainers,
  fetchMaterialDict, createMaterialDict, updateMaterialDict, deleteMaterialDict,
  fetchMaterialSummary, fetchMaterialMovements, exportMaterialMovements,
  fetchPurchaseSuggestions, exportPurchaseSuggestions,
  fetchMaterialTodayStats, fetchContainerDetail, fetchMaterialTrend,
  fetchSuppliers, createSupplier, updateSupplier, deleteSupplier,
  fetchStocktakes, createStocktake, fetchStocktakeDetail, exportStocktake,
  fetchMonthlyReport, exportMonthlyReport,
  downloadImportTemplate, importMaterialDict, importMaterialContainers,
  fetchSlowMoving, updateContainerLocation, fetchMaterialRequests,
} from '@/actions/quality'

const STATUS_ORDER: MaterialContainerStatus[] = ['labeled', 'in_warehouse', 'qualified', 'issued', 'returned', 'void']

const OP_TYPE_META: Record<string, { label: string; color: string }> = {
  in: { label: '入库登记', color: 'green' },
  out: { label: '领料出库', color: 'blue' },
  return: { label: '退库', color: 'purple' },
  reprint: { label: '标签补印', color: 'gold' },
  status: { label: '状态流转', color: 'default' },
}

export default function MaterialContainers() {
  const { message } = App.useApp()
  const { token } = theme.useToken()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<MaterialContainerItem[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [batchDraft, setBatchDraft] = useState('')
  const [batchFilter, setBatchFilter] = useState<string | undefined>()
  const [materialFilter, setMaterialFilter] = useState<string | undefined>()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [genForm] = Form.useForm()
  const [genLoading, setGenLoading] = useState(false)
  const [genRequests, setGenRequests] = useState<MaterialRequestItem[]>([])
  const genMaterialCode = Form.useWatch('material_code', genForm)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [labelLoading, setLabelLoading] = useState(false)
  // 字典与概览
  const [dict, setDict] = useState<MaterialDictItem[]>([])
  const [dictOpen, setDictOpen] = useState(false)
  const [dictForm] = Form.useForm()
  const [editingDict, setEditingDict] = useState<MaterialDictItem | null>(null)
  const [summary, setSummary] = useState<MaterialSummaryItem[]>([])
  // 台账弹窗
  const [mvOpen, setMvOpen] = useState(false)
  const [mvData, setMvData] = useState<MaterialMovementItem[]>([])
  const [mvTotal, setMvTotal] = useState(0)
  const [mvPage, setMvPage] = useState(1)
  const [mvQ, setMvQ] = useState<string | undefined>()
  // 采购清单弹窗
  const [purOpen, setPurOpen] = useState(false)
  const [purData, setPurData] = useState<PurchaseSuggestion[]>([])
  // 今日出入库统计
  const [todayStats, setTodayStats] = useState<{ today_in: number; today_out: number }>({ today_in: 0, today_out: 0 })
  // 容器详情弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailData, setDetailData] = useState<{ container: MaterialContainerItem; movements: MaterialMovementItem[] } | null>(null)
  // 作废原因弹窗
  const [voidTarget, setVoidTarget] = useState<MaterialContainerItem | null>(null)
  const [voidRemark, setVoidRemark] = useState('')
  // 台账操作类型筛选
  const [mvOpType, setMvOpType] = useState<string | undefined>()
  // 供应商弹窗
  const [supOpen, setSupOpen] = useState(false)
  const [supData, setSupData] = useState<SupplierItem[]>([])
  const [supForm] = Form.useForm()
  const [editingSup, setEditingSup] = useState<SupplierItem | null>(null)
  // 盘点弹窗
  const [stOpen, setStOpen] = useState(false)
  const [stSheets, setStSheets] = useState<StocktakeSheet[]>([])
  const [stCreateOpen, setStCreateOpen] = useState(false)
  const [stScope, setStScope] = useState<string | undefined>()
  const [stDetail, setStDetail] = useState<{
    sheet: StocktakeSheet
    items: { id: string; container_no: string; result: string; material_name: string | null; created_at: string }[]
    missing: { container_no: string; material_name: string }[]
  } | null>(null)
  // 月度报表弹窗
  const [mrOpen, setMrOpen] = useState(false)
  const [mrMonth, setMrMonth] = useState(dayjs().format('YYYY-MM'))
  const [mrData, setMrData] = useState<MonthlyReportItem[]>([])
  // 导入弹窗
  const [impOpen, setImpOpen] = useState(false)
  // 呆滞弹窗
  const [slowOpen, setSlowOpen] = useState(false)
  const [slowData, setSlowData] = useState<SlowMovingItem[]>([])
  // 库位编辑
  const [locEditing, setLocEditing] = useState<string | null>(null)
  const [locValue, setLocValue] = useState('')
  // 领用趋势弹窗
  const [trendOpen, setTrendOpen] = useState(false)
  const [trendCode, setTrendCode] = useState<string | undefined>()
  const [trendData, setTrendData] = useState<{ trend: { month: string; in: number; out: number }[]; monthly_avg_out: number; suggested_min_stock: number | null } | null>(null)
  const [trendLoading, setTrendLoading] = useState(false)

  const load = useCallback(async (p: number, status?: string, batch?: string, materialCode?: string) => {
    setLoading(true)
    try {
      const res = await fetchMaterialContainers(p, status, batch, materialCode)
      setData(res.data)
      setTotal(res.meta.total)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  const loadSummary = useCallback(async () => {
    try {
      const res = await fetchMaterialSummary()
      setSummary(res.data)
    } catch {
      // 概览失败静默（列表仍可用）
    }
  }, [])

  const loadDict = useCallback(async (q?: string) => {
    try {
      const res = await fetchMaterialDict(q, 1)
      setDict(res.data)
    } catch {
      // 字典失败静默
    }
  }, [])

  const loadSuppliers = useCallback(async (q?: string) => {
    try {
      const res = await fetchSuppliers(q)
      setSupData(res.data)
    } catch {
      // 供应商失败静默
    }
  }, [])

  const loadTodayStats = useCallback(async () => {
    try {
      const res = await fetchMaterialTodayStats()
      setTodayStats(res.data)
    } catch {
      // 统计失败静默
    }
  }, [])

  useEffect(() => { (async () => { await load(1, statusFilter, batchFilter, materialFilter) })() }, [statusFilter, batchFilter, materialFilter, load])
  // 扫码台/其他标签页操作后自动刷新（跨页面状态同步）
  useCrossTabSignal('material-changed', () => {
    void load(page, statusFilter, batchFilter, materialFilter)
    void loadSummary()
    void loadTodayStats()
  })
  useEffect(() => { (async () => { await loadSummary() })() }, [loadSummary])
  useEffect(() => { (async () => { await loadTodayStats() })() }, [loadTodayStats])
  useEffect(() => { (async () => { await loadDict() })() }, [loadDict])
  useEffect(() => { (async () => { await loadSuppliers() })() }, [loadSuppliers])

  const dictOptions = useMemo(() => dict.map((d) => ({
    value: d.code,
    label: `${d.code} · ${d.name}`,
    name: d.name,
    vendor: d.vendor_name,
    validMonths: d.valid_months,
  })), [dict])

  const onDictSelect = (code: string) => {
    const hit = dictOptions.find((o) => o.value === code)
    if (hit) {
      const patch: Record<string, unknown> = { material_name: hit.name, vendor_code: hit.vendor ?? undefined }
      // 字典配置了效期月数且用户未手动选复验期时，自动计算（今天+N月）
      if (hit.validMonths && !genForm.getFieldValue('expiry_date')) {
        patch.expiry_date = dayjs().add(hit.validMonths, 'month')
      }
      genForm.setFieldsValue(patch)
    }
  }

  const openDetail = async (no: string) => {
    try {
      const res = await fetchContainerDetail(no)
      setDetailData(res.data)
      setDetailOpen(true)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取容器详情失败')
    }
  }

  const openGenerate = () => {
    try {
      const memory = localStorage.getItem('material-gen-memory')
      if (memory) {
        const m = JSON.parse(memory)
        genForm.setFieldsValue({
          material_code: m.material_code, material_name: m.material_name,
          vendor_code: m.vendor_code || undefined, inbound_batch_no: m.inbound_batch_no,
          count: 1,
        })
      }
    } catch { /* 忽略 */ }
    setGenerateOpen(true)
    // 挂单候选：未结单的请验单（放行/拒收/让步/作废后不可挂）
    void fetchMaterialRequests().then((res) => {
      setGenRequests(res.data.filter((r) => ['pending_sample', 'sampled', 'in_test'].includes(r.status)))
    }).catch(() => { /* 请验单拉取失败不影响赋码 */ })
  }

  const onGenerate = async () => {
    const values = await genForm.validateFields()
    setGenLoading(true)
    try {
      const res = await generateMaterialContainers({
        material_code: values.material_code,
        material_name: values.material_name,
        vendor_code: values.vendor_code || undefined,
        inbound_batch_no: values.inbound_batch_no,
        expiry_date: values.expiry_date ? values.expiry_date.format('YYYY-MM-DD') : undefined,
        count: values.count,
        material_request_id: values.material_request_id || undefined,
      })
      const nos = res.data.map((c) => c.container_no)
      const blob = await downloadContainerLabels(nos)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `物料标签-${values.material_code}-${nos.length}张.pdf`
      a.click()
      URL.revokeObjectURL(url)
      message.success(`${res.message}，标签已开始下载`)
      try {
        localStorage.setItem('material-gen-memory', JSON.stringify({
          material_code: values.material_code, material_name: values.material_name,
          vendor_code: values.vendor_code || '', inbound_batch_no: values.inbound_batch_no,
        }))
      } catch { /* 隐私模式等场景忽略 */ }
      setGenerateOpen(false)
      genForm.resetFields()
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '赋码失败')
    } finally {
      setGenLoading(false)
    }
  }

  const onMove = async (row: MaterialContainerItem, op: 'in' | 'out' | 'return') => {
    try {
      const res = await moveMaterialContainer(row.container_no, op)
      message.success(res.message)
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '操作失败')
    }
  }

  const onStatus = async (row: MaterialContainerItem, status: 'in_warehouse' | 'qualified' | 'void', remark?: string) => {
    try {
      const res = await updateMaterialContainerStatus(row.container_no, status, remark)
      message.success(res.message)
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '状态变更失败')
    }
  }

  const onBatchMove = async (op: 'in' | 'out') => {
    try {
      const res = await batchMoveMaterialContainers(selectedKeys, op)
      message.success(res.message)
      if (res.data?.failed) {
        const details = res.data.results.filter((r) => !r.ok).slice(0, 3)
        message.warning(`失败 ${res.data.failed} 个：${details.map((d) => `${d.container_no}（${d.detail}）`).join('；')}`)
      }
      setSelectedKeys([])
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '批量操作失败')
    }
  }

  const onDownloadSelected = async () => {
    if (!selectedKeys.length) {
      message.warning('请先勾选容器')
      return
    }
    setLabelLoading(true)
    try {
      const blob = await downloadContainerLabels(selectedKeys, true)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `物料标签-${selectedKeys.length}张.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '标签生成失败')
    } finally {
      setLabelLoading(false)
    }
  }

  // ── 字典管理 ──
  const onSaveDict = async () => {
    const values = await dictForm.validateFields()
    try {
      if (editingDict) {
        await updateMaterialDict(editingDict.id, values)
        message.success('物料已更新')
      } else {
        await createMaterialDict(values)
        message.success('物料已新增')
      }
      dictForm.resetFields()
      setEditingDict(null)
      loadDict()
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    }
  }

  const onDeleteDict = async (item: MaterialDictItem) => {
    try {
      await deleteMaterialDict(item.id)
      message.success('已删除')
      loadDict()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  const loadTrend = async (code?: string) => {
    if (!code) { setTrendData(null); return }
    setTrendLoading(true)
    try {
      const res = await fetchMaterialTrend(code, 6)
      setTrendData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取领用趋势失败')
    } finally {
      setTrendLoading(false)
    }
  }

  const openSuppliers = () => {
    setEditingSup(null)
    supForm.resetFields()
    setSupOpen(true)
  }

  const onSaveSupplier = async () => {
    const values = await supForm.validateFields()
    try {
      if (editingSup) {
        await updateSupplier(editingSup.id, values)
        message.success('供应商已更新')
      } else {
        await createSupplier(values)
        message.success('供应商已新增')
      }
      supForm.resetFields()
      setEditingSup(null)
      loadSuppliers()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    }
  }

  const onDeleteSupplier = async (item: SupplierItem) => {
    try {
      await deleteSupplier(item.id)
      message.success('已删除')
      loadSuppliers()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  const loadStocktakes = useCallback(async () => {
    try {
      const res = await fetchStocktakes()
      setStSheets(res.data)
    } catch {
      // 静默
    }
  }, [])

  const openStocktakes = () => {
    setStOpen(true)
    void loadStocktakes()
  }

  const onCreateStocktake = async () => {
    try {
      const res = await createStocktake({ scope_material_code: stScope, remark: '扫码盘点' })
      message.success(res.message)
      setStCreateOpen(false)
      setStScope(undefined)
      loadStocktakes()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '创建盘点单失败')
    }
  }

  const openStDetail = async (sheet: StocktakeSheet) => {
    try {
      const res = await fetchStocktakeDetail(sheet.id)
      setStDetail(res.data as never)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取盘点详情失败')
    }
  }

  const onExportStocktake = async (sheet: StocktakeSheet) => {
    try {
      const blob = await exportStocktake(sheet.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `盘点差异-${sheet.sheet_no}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '盘点导出失败')
    }
  }

  const loadMonthlyReport = async (month: string) => {
    try {
      const res = await fetchMonthlyReport(month)
      setMrData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取月度报表失败')
    }
  }

  const openMonthly = () => {
    setMrOpen(true)
    void loadMonthlyReport(mrMonth)
  }

  const onExportMonthly = async () => {
    try {
      const blob = await exportMonthlyReport(mrMonth)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `物料月度汇总-${mrMonth}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '月度报表导出失败')
    }
  }

  const onDownloadImportTemplate = async (kind: 'dict' | 'containers') => {
    try {
      const blob = await downloadImportTemplate(kind)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `导入模板-${kind === 'dict' ? '物料字典' : '容器'}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '模板下载失败')
    }
  }

  const onImportDict = async (file: File) => {
    try {
      const res = await importMaterialDict(file)
      message.success(res.message)
      if (res.data.skipped.length) {
        message.warning(`跳过 ${res.data.skipped.length} 条：${res.data.skipped.slice(0, 3).join('；')}${res.data.skipped.length > 3 ? '…' : ''}`)
      }
      loadDict()
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '物料字典导入失败')
    }
    return false
  }

  const onImportContainers = async (file: File) => {
    try {
      const res = await importMaterialContainers(file)
      message.success(res.message)
      if (res.data.skipped.length) {
        message.warning(`跳过 ${res.data.skipped.length} 条：${res.data.skipped.slice(0, 3).join('；')}${res.data.skipped.length > 3 ? '…' : ''}`)
      }
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '容器导入失败')
    }
    return false
  }

  const openSlowMoving = async () => {
    setSlowOpen(true)
    try {
      const res = await fetchSlowMoving(30)
      setSlowData(res.data.items)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取呆滞库存失败')
    }
  }

  const onSaveLocation = async (no: string) => {
    try {
      await updateContainerLocation(no, locValue.trim())
      message.success('库位已更新')
      setLocEditing(null)
      load(page, statusFilter, batchFilter, materialFilter)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '库位更新失败')
    }
  }

  const openTrend = () => {
    setTrendOpen(true)
    if (trendCode) { void loadTrend(trendCode) }
  }

  const applySuggestedStock = async () => {
    if (!trendCode || trendData?.suggested_min_stock == null) return
    const hit = dict.find((d) => d.code === trendCode)
    if (!hit) { message.warning('该物料不在字典中，无法应用阈值'); return }
    try {
      await updateMaterialDict(hit.id, { min_stock: trendData.suggested_min_stock })
      message.success(`已将 ${hit.name} 安全库存阈值更新为 ${trendData.suggested_min_stock} 瓶`)
      loadDict()
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '应用阈值失败')
    }
  }

  // ── 台账 ──
  const loadMovements = useCallback(async (p: number, q?: string, opType?: string) => {
    try {
      const res = await fetchMaterialMovements(p, q, opType)
      setMvData(res.data)
      setMvTotal(res.meta.total)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取台账失败')
    }
  }, [message])

  useEffect(() => { if (mvOpen) { (async () => { await loadMovements(1, mvQ, mvOpType) })() } }, [mvOpen, mvQ, mvOpType, loadMovements])

  const onExportMovements = async () => {
    try {
      const blob = await exportMaterialMovements(mvQ, mvOpType)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '物料出入库台账.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '台账导出失败')
    }
  }

  // ── 采购清单 ──
  const openPurchase = async () => {
    setPurOpen(true)
    try {
      const res = await fetchPurchaseSuggestions()
      setPurData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取采购建议失败')
    }
  }

  const onExportPurchase = async () => {
    try {
      const blob = await exportPurchaseSuggestions()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '采购建议清单.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '采购建议导出失败')
    }
  }

  const columns = [
    { title: '容器号', dataIndex: 'container_no', key: 'container_no', width: 210, render: (v: string) => (
      <Typography.Text code style={{ cursor: 'pointer' }} onClick={() => openDetail(v)}>{v}</Typography.Text>
    ) },
    { title: '物料名称', dataIndex: 'material_name', key: 'material_name' },
    { title: '物料代码', dataIndex: 'material_code', key: 'material_code', width: 100 },
    { title: '进厂批号', dataIndex: 'inbound_batch_no', key: 'inbound_batch_no', width: 140 },
    { title: '入库日期', dataIndex: 'inbound_date', key: 'inbound_date', width: 105, render: (v: string | null) => v || '-' },
    { title: '库位', dataIndex: 'location', key: 'location', width: 100, render: (v: string | null) => v || '-' },
    { title: '复验期', dataIndex: 'expiry_date', key: 'expiry_date', width: 140, render: (v: string | null) => {
      if (!v) return '-'
      const exp = dayjs(v)
      const days = exp.diff(dayjs(), 'day')
      if (days < 0) return <><Typography.Text>{v}</Typography.Text> <Tag color="red">已过期</Tag></>
      if (days <= 90) return <><Typography.Text>{v}</Typography.Text> <Tag color="orange">临效期 {days} 天</Tag></>
      return v
    } },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 95,
      render: (v: MaterialContainerStatus) => {
        const meta = MATERIAL_CONTAINER_STATUS_META[v]
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '操作', key: 'actions', width: 240,
      render: (_: unknown, row: MaterialContainerItem) => (
        <Space size="small">
          {canManage && row.status === 'labeled' && (
            <Popconfirm title="确认入库登记？" onConfirm={() => onMove(row, 'in')}>
              <Button size="small" type="primary" icon={<ScanOutlined />}>入库</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'in_warehouse' && (
            <Popconfirm title="确认标记合格？（阶段1人工操作，后续放行联动）" onConfirm={() => onStatus(row, 'qualified')}>
              <Button size="small" type="primary" icon={<CheckOutlined />}>合格</Button>
            </Popconfirm>
          )}
          {canManage && (row.status === 'in_warehouse' || row.status === 'qualified') && (
            <Popconfirm title="确认领料出库？" onConfirm={() => onMove(row, 'out')}>
              <Button size="small" danger>出库</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'issued' && (
            <Popconfirm title="确认退库登记？（退库后可重新入库）" onConfirm={() => onMove(row, 'return')}>
              <Button size="small">退库</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'labeled' && (
            <Button size="small" type="link" danger onClick={() => { setVoidTarget(row); setVoidRemark('') }}>作废</Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      {/* 今日出入库统计 */}
      <Space size={16} style={{ marginBottom: 4 }}>
        <Typography.Text type="secondary">今日入库 <Typography.Text strong>{todayStats.today_in}</Typography.Text> 笔</Typography.Text>
        <Typography.Text type="secondary">今日出库 <Typography.Text strong>{todayStats.today_out}</Typography.Text> 笔</Typography.Text>
      </Space>

      {/* 库存概览统计卡 */}
      {summary.length > 0 && (
        <Row gutter={[12, 12]}>
          {summary.map((s) => (
            <Col key={s.material_code} xs={24} sm={12} md={8} lg={6}>
              <Card
                size="small"
                title={`${s.material_name}（${s.material_code}）`}
                extra={
                  <Space size={4}>
                    {s.below_stock && <Tag color="red">库存不足</Tag>}
                    {s.expired > 0 && <Tag color="red">过期 {s.expired}</Tag>}
                    {s.near_expiry > 0 && <Tag color="orange">临效 {s.near_expiry}</Tag>}
                  </Space>
                }
                onClick={() => { setMaterialFilter(s.material_code); setPage(1) }}
                hoverable
              >
                <Space size={8} wrap>
                  <Typography.Text>可用 <Typography.Text strong>{s.available}</Typography.Text></Typography.Text>
                  <Typography.Text type="secondary">在库待验 {s.in_warehouse}</Typography.Text>
                  <Typography.Text type="secondary">合格 {s.qualified}</Typography.Text>
                  <Typography.Text type="secondary">已领出 {s.issued}</Typography.Text>
                  {s.min_stock != null && (
                    <Typography.Text type="secondary">阈值 {s.min_stock}</Typography.Text>
                  )}
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* 状态流转图例 */}
      <Space wrap size={4} style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary">状态流转：</Typography.Text>
        {STATUS_ORDER.map((st) => (
          <Tag key={st} color={MATERIAL_CONTAINER_STATUS_META[st].color}>
            {MATERIAL_CONTAINER_STATUS_META[st].label}
          </Tag>
        ))}
        <Typography.Text type="secondary">
          （已赋码→入库→合格→领出；领出可退库；自动判定扫码台按此流转）
        </Typography.Text>
      </Space>

      <Space wrap>
        <Input
          placeholder="进厂批号搜索" allowClear style={{ width: 160 }}
          prefix={<SearchOutlined />}
          value={batchDraft}
          onChange={(e) => setBatchDraft(e.target.value)}
          onPressEnter={() => { setBatchFilter(batchDraft || undefined); setPage(1) }}
        />
        {materialFilter && (
          <Tag closable color="blue" onClose={() => { setMaterialFilter(undefined); setPage(1) }}>
            物料: {materialFilter}
          </Tag>
        )}
        <Select
          placeholder="状态筛选" allowClear style={{ width: 130 }}
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1) }}
          options={STATUS_ORDER.map((s) => ({ label: MATERIAL_CONTAINER_STATUS_META[s].label, value: s }))}
        />
        <Button type="primary" onClick={() => { setBatchFilter(batchDraft || undefined); setPage(1) }}>搜索</Button>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { openGenerate() }}>批量赋码</Button>
        )}
        <Button icon={<DownloadOutlined />} loading={labelLoading} onClick={onDownloadSelected}>下载标签</Button>
        {canManage && (
          <Popconfirm title={`确认批量入库登记（${selectedKeys.length} 个容器）？`} onConfirm={() => onBatchMove('in')}>
            <Button type="primary" disabled={!selectedKeys.length}>批量入库</Button>
          </Popconfirm>
        )}
        {canManage && (
          <Popconfirm title={`确认批量领料出库（${selectedKeys.length} 个容器）？`} onConfirm={() => onBatchMove('out')}>
            <Button danger disabled={!selectedKeys.length}>批量出库</Button>
          </Popconfirm>
        )}
        {canManage && (
          <Button icon={<BookOutlined />} onClick={() => { setEditingDict(null); dictForm.resetFields(); setDictOpen(true) }}>物料字典</Button>
        )}
        <Button icon={<HistoryOutlined />} onClick={() => { setMvPage(1); setMvQ(undefined); setMvOpen(true) }}>出入库台账</Button>
        <Button icon={<ShoppingCartOutlined />} onClick={openPurchase}>采购清单</Button>
        <Button onClick={openTrend}>领用趋势</Button>
        <Button onClick={openStocktakes}>盘点</Button>
        <Button onClick={openMonthly}>月度报表</Button>
        {canManage && <Button icon={<ImportOutlined />} onClick={() => setImpOpen(true)}>导入</Button>}
        <Button onClick={openSlowMoving}>呆滞分析</Button>
        {canManage && (
          <Button onClick={openSuppliers}>供应商</Button>
        )}
      </Space>

      <Table
        rowKey="container_no"
        scroll={{ x: 1250 }}
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => setPage(p) }}
        size="small"
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: (keys) => setSelectedKeys(keys as string[]) }}
      />

      {/* 批量赋码弹窗 */}
      <Modal
        title="批量赋码（生成唯一容器号 + 标签）"
        open={generateOpen}
        onCancel={() => setGenerateOpen(false)}
        onOk={onGenerate}
        confirmLoading={genLoading}
        okText="赋码并下载标签"
      >
        <Form form={genForm} layout="vertical" initialValues={{ count: 1 }}>
          <Form.Item name="material_code" label="物料代码（字典选择或输入新代码）" rules={[{ required: true, message: '请选择或输入物料代码' }]}>
            <Select
              showSearch
              placeholder="搜索或输入新物料代码"
              options={dictOptions}
              onSelect={(v) => onDictSelect(v)}
              filterOption={(input, option) =>
                (option?.label as string).toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
          <Form.Item name="material_name" label="物料名称" rules={[{ required: true, message: '请输入物料名称' }]}>
            <Input placeholder="盐酸万古霉素原料" />
          </Form.Item>
          <Form.Item name="vendor_code" label="供应商（可选，字典选择或输入）">
            <AutoComplete
              placeholder="选择或输入供应商代码"
              options={supData.map((sp) => ({ value: sp.code, label: `${sp.code} · ${sp.name}` }))}
              filterOption={(input, option) => (option?.label as string).toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
          <Form.Item name="inbound_batch_no" label="进厂批号" rules={[{ required: true, message: '请输入进厂批号' }]}>
            <Input placeholder="IN-20261010-01" />
          </Form.Item>
          <Form.Item name="material_request_id" label="挂到请验单（可选，放行时联动本批容器状态）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择物料匹配的未结单请验单"
              options={genRequests
                .filter((r) => !genMaterialCode || r.material_code === genMaterialCode)
                .map((r) => ({
                  value: r.id,
                  label: `${r.request_no}｜${r.material_name}｜${r.inbound_batch_no}`,
                }))}
            />
          </Form.Item>
          <Form.Item name="expiry_date" label="复验期（可选）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="count" label="本批容器数量" rules={[{ required: true }]}>
            <Input type="number" min={1} max={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 物料字典管理弹窗 */}
      <Modal
        title="物料字典"
        open={dictOpen}
        onCancel={() => setDictOpen(false)}
        footer={null}
        width={720}
      >
        <Form form={dictForm} layout="inline" style={{ marginBottom: 12, rowGap: 8 }} onFinish={onSaveDict}>
          <Form.Item name="code" label="代码" rules={[{ required: !editingDict, message: '必填' }]}>
            <Input disabled={!!editingDict} style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}>
            <Input style={{ width: 150 }} />
          </Form.Item>
          <Form.Item name="category" label="类别">
            <Select
              style={{ width: 100 }} allowClear
              options={['原料', '辅料', '包材', '溶剂'].map((c) => ({ value: c, label: c }))}
            />
          </Form.Item>
          <Form.Item name="vendor_name" label="供应商">
            <Input style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="min_stock" label="安全库存">
            <Input type="number" min={0} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item name="valid_months" label="效期月数">
            <Input type="number" min={1} max={120} style={{ width: 80 }} placeholder="自动算复验期" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">{editingDict ? '保存' : '新增'}</Button>
              {editingDict && <Button onClick={() => { setEditingDict(null); dictForm.resetFields() }}>取消</Button>}
            </Space>
          </Form.Item>
        </Form>
        <Table
          rowKey="id"
          size="small"
          scroll={{ x: 800 }}
          dataSource={dict}
          pagination={false}
          columns={[
            { title: '代码', dataIndex: 'code', width: 110 },
            { title: '名称', dataIndex: 'name' },
            { title: '类别', dataIndex: 'category', width: 70, render: (v: string | null) => v || '-' },
            { title: '供应商', dataIndex: 'vendor_name', width: 110, render: (v: string | null) => v || '-' },
            { title: '安全库存', dataIndex: 'min_stock', width: 80, render: (v: number | null) => v ?? '-' },
            {
              title: '操作', key: 'actions', width: 120,
              render: (_: unknown, item: MaterialDictItem) => (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => {
                    setEditingDict(item)
                    dictForm.setFieldsValue({
                      code: item.code, name: item.name, category: item.category ?? undefined,
                      vendor_name: item.vendor_name ?? undefined, min_stock: item.min_stock ?? undefined,
                      valid_months: item.valid_months ?? undefined,
                    })
                  }}>编辑</Button>
                  <Popconfirm title="确认删除该物料？" onConfirm={() => onDeleteDict(item)}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Modal>

      {/* 出入库台账弹窗 */}
      <Modal
        title="出入库台账"
        open={mvOpen}
        onCancel={() => setMvOpen(false)}
        footer={null}
        width={860}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Input.Search
            placeholder="物料代码/名称搜索" allowClear style={{ width: 200 }}
            onSearch={(v) => { setMvQ(v || undefined); setMvPage(1) }}
          />
          <Select
            placeholder="操作类型" allowClear style={{ width: 130 }}
            value={mvOpType}
            onChange={(v) => { setMvOpType(v); setMvPage(1) }}
            options={[
              { label: '入库登记', value: 'in' },
              { label: '领料出库', value: 'out' },
              { label: '退库', value: 'return' },
              { label: '状态流转', value: 'status' },
              { label: '标签补印', value: 'reprint' },
            ]}
          />
          <Button icon={<DownloadOutlined />} onClick={onExportMovements}>导出 Excel</Button>
        </Space>
        <Table
          rowKey="id"
          size="small"
          scroll={{ x: 900 }}
          dataSource={mvData}
          pagination={{ current: mvPage, pageSize: 50, total: mvTotal, onChange: (p) => { setMvPage(p); loadMovements(p, mvQ) } }}
          columns={[
            { title: '时间', dataIndex: 'op_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
            { title: '容器号', dataIndex: 'container_no', width: 200, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            { title: '物料', dataIndex: 'material_name', width: 140, render: (v: string | null) => v || '-' },
            { title: '操作', dataIndex: 'op_type', width: 90, render: (v: string) => <Tag color={OP_TYPE_META[v]?.color}>{OP_TYPE_META[v]?.label ?? v}</Tag> },
            { title: '状态变化', key: 'status', width: 160, render: (_: unknown, r: MaterialMovementItem) => `${r.from_status} ${r.to_status}` },
            { title: '关联单据', dataIndex: 'related_doc', width: 110, render: (v: string | null) => v || '-' },
          ]}
        />
      </Modal>
      {/* 容器详情弹窗（生命周期时间线） */}
      <Modal
        title={`容器详情 ${detailData?.container.container_no ?? ''}`}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={620}
      >
        {detailData && (
          <>
            <Space wrap size={12} style={{ marginBottom: 12 }}>
              <Typography.Text strong>{detailData.container.material_name}</Typography.Text>
              <Typography.Text type="secondary">代码 {detailData.container.material_code}</Typography.Text>
              <Typography.Text type="secondary">进厂批号 {detailData.container.inbound_batch_no}</Typography.Text>
              <Typography.Text type="secondary">入库日期 {detailData.container.inbound_date ?? '-'}</Typography.Text>
              <Typography.Text type="secondary">库位 {detailData.container.location ?? '-'}</Typography.Text>
              <Typography.Text type="secondary">复验期 {detailData.container.expiry_date ?? '-'}</Typography.Text>
              <Tag color={MATERIAL_CONTAINER_STATUS_META[detailData.container.status]?.color}>
                {MATERIAL_CONTAINER_STATUS_META[detailData.container.status]?.label}
              </Tag>
            </Space>
            <Space size={8} style={{ marginBottom: 8 }}>
            {locEditing === detailData.container.container_no ? (
              <>
                <Input
                  size="small"
                  style={{ width: 140 }}
                  placeholder="库位（如 A-01-03）"
                  value={locValue}
                  onChange={(e) => setLocValue(e.target.value)}
                />
                <Button size="small" type="primary" onClick={() => onSaveLocation(detailData.container.container_no)}>保存</Button>
                <Button size="small" onClick={() => setLocEditing(null)}>取消</Button>
              </>
            ) : (
              canManage && (
                <Button size="small" onClick={() => { setLocEditing(detailData.container.container_no); setLocValue(detailData.container.location ?? '') }}>
                  修改库位
                </Button>
              )
            )}
          </Space>
          <Typography.Text type="secondary">生命周期流水：</Typography.Text>
            <div style={{ marginTop: 8, maxHeight: 320, overflowY: 'auto' }}>
              {detailData.movements.length === 0
                ? <Typography.Text type="secondary">暂无流转记录</Typography.Text>
                : detailData.movements.map((m) => (
                    <div key={m.id} style={{ paddingBlock: 3 }}>
                      <Typography.Text type="secondary">{dayjs(m.op_at).format('YYYY-MM-DD HH:mm')}</Typography.Text>
                      <Tag color={OP_TYPE_META[m.op_type]?.color} style={{ marginLeft: 8 }}>
                        {OP_TYPE_META[m.op_type]?.label ?? m.op_type}
                      </Tag>
                      <Typography.Text type="secondary">{m.from_status} {m.to_status}</Typography.Text>
                      {m.remark && <Typography.Text type="secondary">｜{m.remark}</Typography.Text>}
                    </div>
                  ))}
            </div>
          </>
        )}
      </Modal>

      {/* 作废原因弹窗 */}
      <Modal
        title={`作废容器 ${voidTarget?.container_no ?? ''}`}
        open={!!voidTarget}
        onCancel={() => setVoidTarget(null)}
        onOk={async () => {
          if (!voidTarget) return
          if (!voidRemark.trim()) { message.warning('请填写作废原因'); return }
          await onStatus(voidTarget, 'void', voidRemark.trim())
          setVoidTarget(null)
        }}
        okText="确认作废"
        okButtonProps={{ danger: true }}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          作废后该容器不可再流转，操作留痕。请填写原因：
        </Typography.Paragraph>
        <Input.TextArea rows={2} maxLength={200} value={voidRemark} onChange={(e) => setVoidRemark(e.target.value)} placeholder="如：标签污损/数量不符/重复赋码" />
      </Modal>

      {/* 供应商主数据弹窗 */}
      <Modal
        title="供应商主数据"
        open={supOpen}
        onCancel={() => setSupOpen(false)}
        footer={null}
        width={760}
      >
        <Form form={supForm} layout="inline" style={{ marginBottom: 12, rowGap: 8 }} onFinish={onSaveSupplier}>
          <Form.Item name="code" label="代码" rules={[{ required: !editingSup, message: '必填' }]}>
            <Input disabled={!!editingSup} style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}>
            <Input style={{ width: 150 }} />
          </Form.Item>
          <Form.Item name="contact" label="联系人">
            <Input style={{ width: 100 }} />
          </Form.Item>
          <Form.Item name="phone" label="电话">
            <Input style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="qual_expiry_date" label="资质效期">
            <DatePicker style={{ width: 130 }} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">{editingSup ? '保存' : '新增'}</Button>
              {editingSup && <Button onClick={() => { setEditingSup(null); supForm.resetFields() }}>取消</Button>}
            </Space>
          </Form.Item>
        </Form>
        <Table
          rowKey="id"
          size="small"
          scroll={{ x: 800 }}
          dataSource={supData}
          pagination={false}
          columns={[
            { title: '代码', dataIndex: 'code', width: 110 },
            { title: '名称', dataIndex: 'name' },
            { title: '联系人', dataIndex: 'contact', width: 90, render: (v: string | null) => v || '-' },
            { title: '电话', dataIndex: 'phone', width: 130, render: (v: string | null) => v || '-' },
            { title: '资质效期', dataIndex: 'qual_expiry_date', width: 130, render: (v: string | null) => {
              if (!v) return '-'
              const days = dayjs(v).diff(dayjs(), 'day')
              if (days < 0) return <><Typography.Text>{v}</Typography.Text> <Tag color="red">已过期</Tag></>
              if (days <= 90) return <><Typography.Text>{v}</Typography.Text> <Tag color="orange">临期 {days} 天</Tag></>
              return v
            } },
            {
              title: '操作', key: 'actions', width: 120,
              render: (_: unknown, item: SupplierItem) => (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => {
                    setEditingSup(item)
                    supForm.setFieldsValue({
                      code: item.code, name: item.name, contact: item.contact ?? undefined,
                      phone: item.phone ?? undefined,
                      qual_expiry_date: item.qual_expiry_date ? dayjs(item.qual_expiry_date) : undefined,
                    })
                  }}>编辑</Button>
                  <Popconfirm title={`确认删除供应商 ${item.code}？`} onConfirm={() => onDeleteSupplier(item)}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Modal>

      {/* 盘点管理弹窗 */}
      <Modal
        title="库存盘点"
        open={stOpen}
        onCancel={() => setStOpen(false)}
        footer={null}
        width={820}
      >
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" onClick={() => setStCreateOpen(true)}>新建盘点单</Button>
          <Typography.Text type="secondary">扫码请到「扫码操作台」选盘点模式</Typography.Text>
        </Space>
        <Table
          rowKey="id"
          size="small"
          scroll={{ x: 950 }}
          dataSource={stSheets}
          pagination={false}
          columns={[
            { title: '盘点单号', dataIndex: 'sheet_no', width: 170, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            { title: '范围', dataIndex: 'scope_material_code', width: 120, render: (v: string | null) => v || '全部物料' },
            { title: '系统在库', dataIndex: 'expected_count', width: 90 },
            { title: '实扫', dataIndex: 'scanned_count', width: 80 },
            { title: '盘亏', dataIndex: 'missing_count', width: 80, render: (v: number) => <Typography.Text type={v > 0 ? 'danger' : undefined}>{v}</Typography.Text> },
            { title: '盘盈', dataIndex: 'extra_count', width: 80, render: (v: number) => <Typography.Text type={v > 0 ? 'warning' : undefined}>{v}</Typography.Text> },
            { title: '异常', dataIndex: 'anomaly_count', width: 80, render: (v: number) => <Typography.Text type={v > 0 ? 'danger' : undefined}>{v}</Typography.Text> },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (v: string) => ({ in_progress: <Tag color="processing">进行中</Tag>, completed: <Tag color="success">已完成</Tag>, void: <Tag>已作废</Tag> } as Record<string, React.ReactNode>)[v] ?? v,
            },
            {
              title: '操作', key: 'actions', width: 140,
              render: (_: unknown, item: StocktakeSheet) => (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => openStDetail(item)}>详情</Button>
                  <Button size="small" type="link" onClick={() => onExportStocktake(item)}>导出</Button>
                </Space>
              ),
            },
          ]}
        />
      </Modal>

      {/* 新建盘点单 */}
      <Modal
        title="新建盘点单"
        open={stCreateOpen}
        onCancel={() => setStCreateOpen(false)}
        onOk={onCreateStocktake}
        okText="创建"
        width={420}
      >
        <Typography.Paragraph type="secondary">
          盘点口径：在库待验 + 合格（实物在库）。不选范围 = 全部物料。
        </Typography.Paragraph>
        <Select
          placeholder="盘点范围物料（可选）" allowClear style={{ width: '100%' }}
          value={stScope}
          onChange={(v) => setStScope(v)}
          options={summary.map((sm) => ({ value: sm.material_code, label: `${sm.material_name}（${sm.material_code}）` }))}
        />
      </Modal>

      {/* 盘点详情 */}
      <Modal
        title={`盘点详情 ${stDetail?.sheet.sheet_no ?? ''}`}
        open={!!stDetail}
        onCancel={() => setStDetail(null)}
        footer={null}
        width={720}
      >
        {stDetail && (
          <>
            <Space size={16} style={{ marginBottom: 12 }}>
              <Typography.Text>系统在库 <strong>{stDetail.sheet.expected_count}</strong></Typography.Text>
              <Typography.Text>实扫 <strong>{stDetail.sheet.scanned_count}</strong></Typography.Text>
              <Typography.Text type="danger">盘亏 <strong>{stDetail.sheet.missing_count}</strong></Typography.Text>
              <Typography.Text type="warning">盘盈 <strong>{stDetail.sheet.extra_count}</strong></Typography.Text>
              <Typography.Text type="danger">异常 <strong>{stDetail.sheet.anomaly_count}</strong></Typography.Text>
            </Space>
            {stDetail.missing.length > 0 && (
              <>
                <Typography.Text type="danger" strong>盘亏清单（系统在库但未扫到）：</Typography.Text>
                <div style={{ maxHeight: 160, overflowY: 'auto', marginBlock: 6 }}>
                  {stDetail.missing.map((m) => (
                    <div key={m.container_no} style={{ paddingBlock: 2 }}>
                      <Tag color="red">盘亏</Tag>
                      <Typography.Text code>{m.container_no}</Typography.Text>
                      <Typography.Text type="secondary"> {m.material_name}</Typography.Text>
                    </div>
                  ))}
                </div>
              </>
            )}
            <Typography.Text type="secondary">扫码明细：</Typography.Text>
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {stDetail.items.map((i) => (
                <div key={i.id} style={{ paddingBlock: 2 }}>
                  <Tag color={i.result === 'matched' ? 'green' : i.result === 'not_found' ? 'red' : 'orange'}>
                    {{ matched: '在库匹配', out_of_scope: '盘盈', not_found: '异常' }[i.result] ?? i.result}
                  </Tag>
                  <Typography.Text code>{i.container_no}</Typography.Text>
                  <Typography.Text type="secondary"> {i.material_name ?? '-'}（{dayjs(i.created_at).format('HH:mm')}）</Typography.Text>
                </div>
              ))}
            </div>
          </>
        )}
      </Modal>

      {/* 月度报表弹窗 */}
      <Modal
        title="物料月度汇总"
        open={mrOpen}
        onCancel={() => setMrOpen(false)}
        footer={null}
        width={820}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <DatePicker
            picker="month"
            value={dayjs(mrMonth)}
            allowClear={false}
            onChange={(d) => { const m = d ? d.format('YYYY-MM') : dayjs().format('YYYY-MM'); setMrMonth(m); void loadMonthlyReport(m) }}
          />
          <Button icon={<DownloadOutlined />} onClick={onExportMonthly}>导出 Excel</Button>
        </Space>
        <Table
          rowKey="material_code"
          size="small"
          scroll={{ x: 800 }}
          dataSource={mrData}
          pagination={false}
          locale={{ emptyText: '该月暂无出入库记录' }}
          columns={[
            { title: '物料代码', dataIndex: 'material_code', width: 120 },
            { title: '物料名称', dataIndex: 'material_name' },
            { title: '入库', dataIndex: 'in_count', width: 80 },
            { title: '出库', dataIndex: 'out_count', width: 80 },
            { title: '退库', dataIndex: 'return_count', width: 80 },
            { title: '状态流转', dataIndex: 'status_count', width: 90 },
            { title: '当前可用', dataIndex: 'available', width: 90, render: (v: number) => <Typography.Text strong>{v}</Typography.Text> },
          ]}
        />
      </Modal>

      {/* 导入弹窗 */}
      <Modal
        title="Excel 批量导入"
        open={impOpen}
        onCancel={() => setImpOpen(false)}
        footer={null}
        width={640}
      >
        <Tabs
          items={[
            {
              key: 'dict',
              label: '物料字典',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Typography.Text type="secondary">列：代码/名称/类别/供应商/包装规格/安全库存/效期月数/备注；代码重复自动跳过</Typography.Text>
                  <Space>
                    <Button size="small" onClick={() => onDownloadImportTemplate('dict')}>下载模板</Button>
                    <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={onImportDict}>
                      <Button size="small" type="primary">选择文件导入</Button>
                    </Upload>
                  </Space>
                </Space>
              ),
            },
            {
              key: 'containers',
              label: '存量容器',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Typography.Text type="secondary">列：容器号(MC-开头)/物料代码/物料名称/供应商代码/进厂批号/入库日期/复验期/库位/状态；重复与非法状态自动跳过</Typography.Text>
                  <Space>
                    <Button size="small" onClick={() => onDownloadImportTemplate('containers')}>下载模板</Button>
                    <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={onImportContainers}>
                      <Button size="small" type="primary">选择文件导入</Button>
                    </Upload>
                  </Space>
                </Space>
              ),
            },
          ]}
        />
      </Modal>

      {/* 呆滞分析弹窗 */}
      <Modal
        title="呆滞库存（在库且入库超 30 天）"
        open={slowOpen}
        onCancel={() => setSlowOpen(false)}
        footer={null}
        width={760}
      >
        <Space size={16} style={{ marginBottom: 12 }}>
          <Typography.Text>呆滞总数 <strong>{slowData.length}</strong></Typography.Text>
          <Typography.Text type="warning">超 60 天 <strong>{slowData.filter((x) => x.age_days >= 60 && x.age_days < 90).length}</strong></Typography.Text>
          <Typography.Text type="danger">超 90 天 <strong>{slowData.filter((x) => x.age_days >= 90).length}</strong></Typography.Text>
        </Space>
        <Table
          rowKey="container_no"
          size="small"
          scroll={{ x: 850 }}
          dataSource={slowData}
          pagination={{ pageSize: 20 }}
          locale={{ emptyText: '暂无呆滞库存' }}
          columns={[
            { title: '容器号', dataIndex: 'container_no', width: 200, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            { title: '物料', dataIndex: 'material_name', width: 150 },
            { title: '进厂批号', dataIndex: 'inbound_batch_no', width: 140 },
            { title: '入库日期', dataIndex: 'inbound_date', width: 110 },
            { title: '库位', dataIndex: 'location', width: 90, render: (v: string | null) => v || '-' },
            {
              title: '账龄', dataIndex: 'age_days', width: 100,
              render: (v: number) => <Tag color={v >= 90 ? 'red' : v >= 60 ? 'orange' : 'default'}>{v} 天</Tag>,
            },
          ]}
        />
      </Modal>

      {/* 领用趋势弹窗 */}
      <Modal
        title="领用趋势（近 6 个月出入库）"
        open={trendOpen}
        onCancel={() => setTrendOpen(false)}
        footer={null}
        width={560}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            placeholder="选择物料" style={{ width: 240 }}
            showSearch
            value={trendCode}
            onChange={(v) => { setTrendCode(v); void loadTrend(v) }}
            options={summary.map((s) => ({ value: s.material_code, label: `${s.material_name}（${s.material_code}）` }))}
          />
        </Space>
        {trendLoading && <Typography.Text type="secondary">加载中…</Typography.Text>}
        {trendData && (
          <>
            {trendData.trend.map((t) => {
              const maxOut = Math.max(...trendData.trend.map((x) => x.out), 1)
              return (
                <div key={t.month} style={{ display: 'flex', alignItems: 'center', marginBlock: 3 }}>
                  <Typography.Text type="secondary" style={{ width: 70 }}>{t.month}</Typography.Text>
                  <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: `${(t.out / maxOut) * 100}%`, minWidth: t.out > 0 ? 18 : 0, height: 16, background: token.colorPrimary, borderRadius: 3, textAlign: 'center', color: token.colorWhite, fontSize: 11, lineHeight: '16px', transition: 'width .2s' }}>
                      {t.out > 0 ? t.out : ''}
                    </div>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>出库 {t.out}</Typography.Text>
                  </div>
                </div>
              )
            })}
            <div style={{ marginTop: 12, padding: 10, background: token.colorBgLayout, borderRadius: 6 }}>
              <Typography.Text>
                月均领用 <Typography.Text strong>{trendData.monthly_avg_out}</Typography.Text> 瓶
                {trendData.suggested_min_stock != null && (
                  <>
                    ｜建议安全库存阈值 <Typography.Text strong type="warning">{trendData.suggested_min_stock}</Typography.Text> 瓶（月均×2）
                  </>
                )}
              </Typography.Text>
              {trendData.suggested_min_stock != null && canManage && (
                <Button size="small" type="primary" ghost style={{ marginLeft: 12 }} onClick={applySuggestedStock}>
                  应用到字典
                </Button>
              )}
            </div>
          </>
        )}
        {!trendLoading && !trendData && (
          <Typography.Text type="secondary">选择物料后展示近 6 个月领用趋势与阈值建议</Typography.Text>
        )}
      </Modal>

      {/* 采购清单弹窗 */}
      <Modal
        title="采购建议清单（可用库存低于安全库存阈值）"
        open={purOpen}
        onCancel={() => setPurOpen(false)}
        footer={null}
        width={760}
      >
        <Space style={{ marginBottom: 12 }}>
          <Button icon={<DownloadOutlined />} onClick={onExportPurchase}>导出 Excel</Button>
        </Space>
        <Table
          rowKey="material_code"
          size="small"
          scroll={{ x: 750 }}
          dataSource={purData}
          pagination={false}
          locale={{ emptyText: '暂无采购建议（各物料库存充足或未设置安全库存阈值）' }}
          columns={[
            { title: '物料代码', dataIndex: 'material_code', width: 110 },
            { title: '物料名称', dataIndex: 'material_name' },
            { title: '供应商', dataIndex: 'vendor_name', width: 120, render: (v: string | null) => v || '-' },
            { title: '包装规格', dataIndex: 'pack_spec', width: 100, render: (v: string | null) => v || '-' },
            { title: '可用库存', dataIndex: 'available', width: 90, render: (v: number) => <Typography.Text type="danger">{v}</Typography.Text> },
            { title: '安全库存', dataIndex: 'min_stock', width: 90 },
            { title: '建议采购量', dataIndex: 'gap', width: 100, render: (v: number) => <Typography.Text strong type="warning">{v}</Typography.Text> },
          ]}
        />
      </Modal>
    </>
  )
}
