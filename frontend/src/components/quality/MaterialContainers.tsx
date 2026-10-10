'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Select, Modal, Form, DatePicker, Popconfirm, Typography, Card, Row, Col, Segmented,
} from 'antd'
import { PlusOutlined, SearchOutlined, DownloadOutlined, ScanOutlined, BookOutlined, HistoryOutlined, ShoppingCartOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import { MATERIAL_CONTAINER_STATUS_META } from '@/types/quality'
import type { MaterialContainerItem, MaterialContainerStatus, MaterialDictItem, MaterialMovementItem, MaterialSummaryItem, PurchaseSuggestion } from '@/types/quality'
import type { InputRef } from 'antd'
import {
  fetchMaterialContainers, generateMaterialContainers, moveMaterialContainer,
  updateMaterialContainerStatus, downloadContainerLabels, batchMoveMaterialContainers,
  fetchMaterialDict, createMaterialDict, updateMaterialDict, deleteMaterialDict,
  fetchMaterialSummary, fetchMaterialMovements, exportMaterialMovements,
  fetchPurchaseSuggestions, exportPurchaseSuggestions,
} from '@/actions/quality'

const STATUS_ORDER: MaterialContainerStatus[] = ['labeled', 'in_warehouse', 'qualified', 'issued', 'returned', 'void']

const OP_TYPE_META: Record<string, { label: string; color: string }> = {
  in: { label: '入库登记', color: 'green' },
  out: { label: '领料出库', color: 'blue' },
  status: { label: '状态流转', color: 'default' },
}

export default function MaterialContainers() {
  const { message } = App.useApp()
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
  // 扫码操作台（USB 扫码枪=键盘输入+回车，也支持手工输号）
  const [scanMode, setScanMode] = useState<'in' | 'out'>('in')
  const [scanValue, setScanValue] = useState('')
  const [scanBusy, setScanBusy] = useState(false)
  const [scanResults, setScanResults] = useState<{ no: string; ok: boolean; detail: string; at: string }[]>([])
  const scanInputRef = useRef<InputRef>(null)

  const handleScan = async (raw: string) => {
    // 兼容富文本二维码：从扫描内容中提取容器号（首行 MC-xxx）
    const matched = raw.match(/MC-[A-Za-z0-9-]+/)
    const no = matched ? matched[0] : raw.trim()
    if (!no) return
    if (no !== raw.trim() && !matched) {
      message.warning('未识别到容器号（MC-物料代码-日期-流水）')
      setScanValue('')
      return
    }
    setScanBusy(true)
    try {
      const res = await moveMaterialContainer(no, scanMode)
      setScanResults((prev) => [{
        no,
        ok: true,
        detail: `已${scanMode === 'in' ? '入库登记' : '领料出库'}（${res.data.material_name}）`,
        at: dayjs().format('HH:mm:ss'),
      }, ...prev].slice(0, 20))
      message.success(`✅ ${no} ${scanMode === 'in' ? '入库' : '出库'}成功`)
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      const detail = (err instanceof Error ? err.message : String(err)) || '操作失败'
      setScanResults((prev) => [{ no, ok: false, detail, at: dayjs().format('HH:mm:ss') }, ...prev].slice(0, 20))
      message.error(`❌ ${no}：${detail}`)
    } finally {
      setScanBusy(false)
      setScanValue('')
      // 连续扫码：保持焦点
      scanInputRef.current?.focus()
    }
  }

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

  useEffect(() => { (async () => { await load(1, statusFilter, batchFilter, materialFilter) })() }, [statusFilter, batchFilter, materialFilter, load])
  useEffect(() => { (async () => { await loadSummary() })() }, [loadSummary])
  useEffect(() => { (async () => { await loadDict() })() }, [loadDict])

  const dictOptions = useMemo(() => dict.map((d) => ({
    value: d.code,
    label: `${d.code} · ${d.name}`,
    name: d.name,
    vendor: d.vendor_name,
  })), [dict])

  const onDictSelect = (code: string) => {
    const hit = dictOptions.find((o) => o.value === code)
    if (hit) {
      genForm.setFieldsValue({ material_name: hit.name, vendor_code: hit.vendor ?? undefined })
    }
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

  const onMove = async (row: MaterialContainerItem, op: 'in' | 'out') => {
    try {
      const res = await moveMaterialContainer(row.container_no, op)
      message.success(res.message)
      load(page, statusFilter, batchFilter, materialFilter)
      loadSummary()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '操作失败')
    }
  }

  const onStatus = async (row: MaterialContainerItem, status: 'in_warehouse' | 'qualified' | 'void') => {
    try {
      const res = await updateMaterialContainerStatus(row.container_no, status)
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
      const blob = await downloadContainerLabels(selectedKeys)
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

  // ── 台账 ──
  const loadMovements = useCallback(async (p: number, q?: string) => {
    try {
      const res = await fetchMaterialMovements(p, q)
      setMvData(res.data)
      setMvTotal(res.meta.total)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取台账失败')
    }
  }, [message])

  useEffect(() => { if (mvOpen) { (async () => { await loadMovements(1, mvQ) })() } }, [mvOpen, mvQ, loadMovements])

  const onExportMovements = async () => {
    try {
      const blob = await exportMaterialMovements(mvQ)
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
    { title: '容器号', dataIndex: 'container_no', key: 'container_no', width: 210, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    { title: '物料名称', dataIndex: 'material_name', key: 'material_name' },
    { title: '物料代码', dataIndex: 'material_code', key: 'material_code', width: 100 },
    { title: '进厂批号', dataIndex: 'inbound_batch_no', key: 'inbound_batch_no', width: 140 },
    { title: '入库日期', dataIndex: 'inbound_date', key: 'inbound_date', width: 105, render: (v: string | null) => v || '-' },
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
              <Button size="small" icon={<ScanOutlined />}>入库</Button>
            </Popconfirm>
          )}
          {canManage && (row.status === 'in_warehouse' || row.status === 'qualified') && (
            <Popconfirm title="确认领料出库？" onConfirm={() => onMove(row, 'out')}>
              <Button size="small" danger>出库</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'in_warehouse' && (
            <Popconfirm title="确认标记合格？（阶段1人工操作，后续放行联动）" onConfirm={() => onStatus(row, 'qualified')}>
              <Button size="small" type="primary" ghost>合格</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'labeled' && (
            <Popconfirm title="确认作废该容器？" onConfirm={() => onStatus(row, 'void')}>
              <Button size="small" type="link" danger>作废</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      {/* 扫码操作台：USB 扫码枪（或手工输号）连续处理入库/出库 */}
      {canManage && (
        <Card size="small" title="🔫 扫码操作台" style={{ maxWidth: 720 }}>
          <Space wrap>
            <Segmented
              value={scanMode}
              onChange={(v) => { setScanMode(v as 'in' | 'out'); setScanResults([]) }}
              options={[
                { label: '入库登记', value: 'in' },
                { label: '领料出库', value: 'out' },
              ]}
            />
            <Input
              ref={scanInputRef}
              placeholder="扫码枪扫描容器二维码，或手工输入容器号回车"
              style={{ width: 360 }}
              value={scanValue}
              disabled={scanBusy}
              prefix={<ScanOutlined />}
              onChange={(e) => setScanValue(e.target.value)}
              onPressEnter={() => handleScan(scanValue)}
              allowClear
            />
          </Space>
          {scanResults.length > 0 && (
            <div style={{ marginTop: 8, maxHeight: 200, overflowY: 'auto' }}>
              {scanResults.map((r, i) => (
                <div key={`${r.no}-${r.at}-${i}`} style={{ paddingBlock: 2 }}>
                  <Tag color={r.ok ? 'green' : 'red'}>{r.ok ? '成功' : '失败'}</Tag>
                  <Typography.Text code>{r.no}</Typography.Text>
                  <Typography.Text type="secondary"> {r.detail}（{r.at}）</Typography.Text>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

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
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setGenerateOpen(true)}>批量赋码</Button>
        )}
        <Button icon={<DownloadOutlined />} loading={labelLoading} onClick={onDownloadSelected}>下载标签</Button>
        {canManage && (
          <Popconfirm title={`确认批量入库登记（${selectedKeys.length} 个容器）？`} onConfirm={() => onBatchMove('in')}>
            <Button disabled={!selectedKeys.length}>批量入库</Button>
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
      </Space>

      <Table
        rowKey="container_no"
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
          <Form.Item name="vendor_code" label="供应商（可选）">
            <Input placeholder="SUP-001" />
          </Form.Item>
          <Form.Item name="inbound_batch_no" label="进厂批号" rules={[{ required: true, message: '请输入进厂批号' }]}>
            <Input placeholder="IN-20261010-01" />
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
          <Button icon={<DownloadOutlined />} onClick={onExportMovements}>导出 Excel</Button>
        </Space>
        <Table
          rowKey="id"
          size="small"
          dataSource={mvData}
          pagination={{ current: mvPage, pageSize: 50, total: mvTotal, onChange: (p) => { setMvPage(p); loadMovements(p, mvQ) } }}
          columns={[
            { title: '时间', dataIndex: 'op_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
            { title: '容器号', dataIndex: 'container_no', width: 200, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            { title: '物料', dataIndex: 'material_name', width: 140, render: (v: string | null) => v || '-' },
            { title: '操作', dataIndex: 'op_type', width: 90, render: (v: string) => <Tag color={OP_TYPE_META[v]?.color}>{OP_TYPE_META[v]?.label ?? v}</Tag> },
            { title: '状态变化', key: 'status', width: 160, render: (_: unknown, r: MaterialMovementItem) => `${r.from_status} → ${r.to_status}` },
            { title: '关联单据', dataIndex: 'related_doc', width: 110, render: (v: string | null) => v || '-' },
          ]}
        />
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
