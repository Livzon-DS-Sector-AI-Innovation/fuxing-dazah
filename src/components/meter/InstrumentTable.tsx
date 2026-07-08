'use client'

import { useCallback, useEffect, useState, type Key } from 'react'
import { App, Table, Button, Space, Input, Select, Tag, Tooltip, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, FileTextOutlined, UploadOutlined, DownloadOutlined, FileExcelOutlined, ImportOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { InstrumentRecord, InstrumentFilter, InstrumentFilterOptions } from '@/types/meter'
import { deleteInstrument, getInstruments, exportInstrumentReports, exportInstrumentsExcel, getInstrumentFilterOptions } from '@/actions/meter'
import { InstrumentDrawer } from './InstrumentDrawer'
import { ReportDialog } from './ReportDialog'
import { BatchUploadDialog } from './BatchUploadDialog'
import { BatchCreateModal } from './BatchCreateModal'
import { LedgerImportModal } from './LedgerImportModal'
import dayjs from 'dayjs'

/** 筛选下拉框通用渲染 */
function renderFilterDropdown(
  options: string[],
  selectedValue: string | undefined,
  setValue: (v: string | undefined) => void,
  placeholder: string,
) {
  return ({ setSelectedKeys, selectedKeys, confirm, clearFilters }: { setSelectedKeys: (keys: Key[]) => void; selectedKeys: Key[]; confirm: () => void; clearFilters?: () => void }) => (
    <div style={{ padding: 8, minWidth: 200 }}>
      <Select
        allowClear
        showSearch
        placeholder={placeholder}
        value={selectedKeys[0] ?? undefined}
        onChange={(value) => {
          const v = value as string | undefined
          setSelectedKeys(v ? [v] : [])
          setValue(v ?? undefined)
        }}
        style={{ width: '100%' }}
        options={options.map(v => ({ label: v, value: v }))}
        filterOption={(input, option) =>
          (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
        }
      />
    </div>
  )
}

/** 筛选字段名 → InstrumentFilter 参数 key 的映射 */
const INSTRUMENT_FILTER_KEY: Record<string, keyof InstrumentFilter> = {
  department: 'department',
  asset_number: 'asset_number',
  instrument_name: 'instrument_name',
  model_spec: 'model_spec',
  accuracy_grade: 'accuracy_grade',
  serial_number: 'serial_number',
  location: 'location',
  manufacturer: 'manufacturer',
  status: 'status',
  calibration_unit: 'calibration_unit',
  calibration_result: 'calibration_result',
  color_marking: 'color_marking',
}

export function InstrumentTable() {
  const { message } = App.useApp()
  const [data, setData] = useState<InstrumentRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<InstrumentRecord | null>(null)
  const [reportDialogOpen, setReportDialogOpen] = useState(false)
  const [reportRecord, setReportRecord] = useState<InstrumentRecord | null>(null)
  const [batchUploadOpen, setBatchUploadOpen] = useState(false)
  const [batchCreateOpen, setBatchCreateOpen] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [exporting, setExporting] = useState(false)
  const [exportingExcel, setExportingExcel] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)

  // 列头筛选状态（服务端筛选）
  const [columnFilters, setColumnFilters] = useState<Record<string, string | undefined>>({})
  const [filterOptions, setFilterOptions] = useState<InstrumentFilterOptions>({
    department: [], asset_number: [], instrument_name: [], model_spec: [],
    accuracy_grade: [], serial_number: [], location: [], manufacturer: [],
    status: [], calibration_unit: [], calibration_result: [], color_marking: [],
  })

  // 首次加载时获取全表筛选选项
  useEffect(() => {
    getInstrumentFilterOptions()
      .then(opts => setFilterOptions(opts))
      .catch(() => message.error('获取筛选选项失败'))
  }, [message])

  const setColumnFilter = useCallback((field: string, value: string | undefined) => {
    setColumnFilters(prev => ({ ...prev, [field]: value }))
    setPage(1)
  }, [])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: InstrumentFilter = { page, page_size: pageSize }
      if (keyword) params.keyword = keyword
      // 合并列头筛选条件
      for (const [field, value] of Object.entries(columnFilters)) {
        const key = INSTRUMENT_FILTER_KEY[field]
        if (key && value) (params as Record<string, unknown>)[key] = value
      }
      const res = await getInstruments(params)
      setData(res.items)
      setTotal(res.total)
    } catch {
      message.error('获取数据失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, columnFilters, message])

  useEffect(() => { fetchData() }, [fetchData])

  const handleDelete = async (id: string) => {
    try {
      await deleteInstrument(id)
      message.success('删除成功')
      fetchData()
    } catch {
      message.error('删除失败')
    }
  }

  const handleEdit = (record: InstrumentRecord) => {
    setEditingRecord(record)
    setDrawerOpen(true)
  }

  const handleCreate = () => {
    setEditingRecord(null)
    setDrawerOpen(true)
  }

  const handleExportReports = async () => {
    if (selectedRowKeys.length === 0) { message.warning('请先选择要导出的仪表'); return }
    setExporting(true)
    try {
      const result = await exportInstrumentReports(selectedRowKeys as string[])
      const byteChars = atob(result.blob)
      const byteNums = new Array(byteChars.length)
      for (let i = 0; i < byteChars.length; i++) byteNums[i] = byteChars.charCodeAt(i)
      const blob = new Blob([new Uint8Array(byteNums)], { type: 'application/zip' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = result.filename; a.click()
      window.URL.revokeObjectURL(url)
      message.success(`导出完成：${result.count} 份报告`)
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  const handleExportExcel = async () => {
    setExportingExcel(true)
    try {
      const filterParams: InstrumentFilter = {}
      if (keyword) filterParams.keyword = keyword
      for (const [field, value] of Object.entries(columnFilters)) {
        const key = INSTRUMENT_FILTER_KEY[field]
        if (key && value) (filterParams as Record<string, unknown>)[key] = value
      }
      const result = await exportInstrumentsExcel(filterParams)
      const byteChars = atob(result.blob)
      const byteNums = new Array(byteChars.length)
      for (let i = 0; i < byteChars.length; i++) byteNums[i] = byteChars.charCodeAt(i)
      const blob = new Blob([new Uint8Array(byteNums)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = result.filename; a.click()
      window.URL.revokeObjectURL(url)
      message.success('导出完成')
    } catch {
      message.error('导出失败')
    } finally {
      setExportingExcel(false)
    }
  }

  const handleDrawerClose = () => {
    setDrawerOpen(false)
    setEditingRecord(null)
    fetchData()
  }

  const statusTag = (status?: string) => {
    if (status === '在用') return <Tag color="green">在用</Tag>
    if (status === '超期') return <Tag color="orange">超期</Tag>
    if (status === '停用') return <Tag color="red">停用</Tag>
    return <Tag>{status || '-'}</Tag>
  }

  const columns: TableColumnsType<InstrumentRecord> = [
    {
      title: '部门', dataIndex: 'department', width: 120, ellipsis: true,
      filteredValue: columnFilters.department ? [columnFilters.department] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.department,
        columnFilters.department,
        (v) => setColumnFilter('department', v),
        '选择部门',
      ),
      onFilter: () => true,
    },
    {
      title: '资产编号', dataIndex: 'asset_number', width: 120,
      filteredValue: columnFilters.asset_number ? [columnFilters.asset_number] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.asset_number,
        columnFilters.asset_number,
        (v) => setColumnFilter('asset_number', v),
        '选择资产编号',
      ),
      onFilter: () => true,
    },
    {
      title: '器具名称', dataIndex: 'instrument_name', width: 160, ellipsis: true,
      filteredValue: columnFilters.instrument_name ? [columnFilters.instrument_name] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.instrument_name,
        columnFilters.instrument_name,
        (v) => setColumnFilter('instrument_name', v),
        '选择器具名称',
      ),
      onFilter: () => true,
    },
    {
      title: '型号规格', dataIndex: 'model_spec', width: 100, ellipsis: true,
      filteredValue: columnFilters.model_spec ? [columnFilters.model_spec] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.model_spec,
        columnFilters.model_spec,
        (v) => setColumnFilter('model_spec', v),
        '选择型号规格',
      ),
      onFilter: () => true,
    },
    { title: '测量范围', dataIndex: 'measurement_range', width: 120, ellipsis: true },
    {
      title: '精度等级', dataIndex: 'accuracy_grade', width: 80,
      filteredValue: columnFilters.accuracy_grade ? [columnFilters.accuracy_grade] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.accuracy_grade,
        columnFilters.accuracy_grade,
        (v) => setColumnFilter('accuracy_grade', v),
        '选择精度等级',
      ),
      onFilter: () => true,
    },
    { title: '检定周期(月)', dataIndex: 'calibration_cycle_months', width: 90 },
    {
      title: '彩色标志', dataIndex: 'color_marking', width: 80,
      filteredValue: columnFilters.color_marking ? [columnFilters.color_marking] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.color_marking,
        columnFilters.color_marking,
        (v) => setColumnFilter('color_marking', v),
        '选择彩色标志',
      ),
      onFilter: () => true,
    },
    {
      title: '器具编号', dataIndex: 'serial_number', width: 110, ellipsis: true,
      filteredValue: columnFilters.serial_number ? [columnFilters.serial_number] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.serial_number,
        columnFilters.serial_number,
        (v) => setColumnFilter('serial_number', v),
        '选择器具编号',
      ),
      onFilter: () => true,
    },
    {
      title: '使用地点', dataIndex: 'location', width: 200, ellipsis: true,
      filteredValue: columnFilters.location ? [columnFilters.location] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.location,
        columnFilters.location,
        (v) => setColumnFilter('location', v),
        '选择使用地点',
      ),
      onFilter: () => true,
    },
    {
      title: '制造商', dataIndex: 'manufacturer', width: 120, ellipsis: true,
      filteredValue: columnFilters.manufacturer ? [columnFilters.manufacturer] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.manufacturer,
        columnFilters.manufacturer,
        (v) => setColumnFilter('manufacturer', v),
        '选择制造商',
      ),
      onFilter: () => true,
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      filteredValue: columnFilters.status ? [columnFilters.status] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.status,
        columnFilters.status,
        (v) => setColumnFilter('status', v),
        '选择状态',
      ),
      onFilter: () => true,
      render: (_: unknown, r: InstrumentRecord) => statusTag(r.status),
    },
    {
      title: '检定日期', dataIndex: 'calibration_date', width: 110,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '下次检定', dataIndex: 'next_calibration_date', width: 110,
      render: (v: string) => {
        if (!v) return '-'
        const d = dayjs(v)
        const overdue = d.isBefore(dayjs())
        return <span style={{ color: overdue ? '#e03131' : undefined }}>{d.format('YYYY-MM-DD')}</span>
      },
    },
    {
      title: '检定单位', dataIndex: 'calibration_unit', width: 100, ellipsis: true,
      filteredValue: columnFilters.calibration_unit ? [columnFilters.calibration_unit] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.calibration_unit,
        columnFilters.calibration_unit,
        (v) => setColumnFilter('calibration_unit', v),
        '选择检定单位',
      ),
      onFilter: () => true,
    },
    {
      title: '检定结论', dataIndex: 'calibration_result', width: 80,
      filteredValue: columnFilters.calibration_result ? [columnFilters.calibration_result] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.calibration_result,
        columnFilters.calibration_result,
        (v) => setColumnFilter('calibration_result', v),
        '选择检定结论',
      ),
      onFilter: () => true,
    },
    {
      title: '备注', dataIndex: 'remark', width: 120, ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '报告', dataIndex: 'report_count', width: 60,
      render: (v: number) => v > 0 ? <Tag color="blue">{v}</Tag> : '-',
    },
    {
      title: '操作', key: 'actions', width: 120, fixed: 'right',
      render: (_: unknown, r: InstrumentRecord) => (
        <Space size="small">
          <Tooltip title="报告">
            <Button size="small" icon={<FileTextOutlined />} onClick={() => { setReportRecord(r); setReportDialogOpen(true) }} />
          </Tooltip>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)} />
          </Tooltip>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <Space wrap>
          <Input
            placeholder="搜索资产编号/名称/型号"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
            style={{ width: 260 }}
            allowClear
          />
          {/* 已激活筛选标签 */}
          {Object.entries(columnFilters).filter(([, v]) => v).map(([field, value]) => {
            const labels: Record<string, string> = {
              department: '部门', asset_number: '资产编号', instrument_name: '器具名称',
              model_spec: '型号', accuracy_grade: '精度', serial_number: '器具编号',
              location: '地点', manufacturer: '制造商', status: '状态',
              calibration_unit: '检定单位', calibration_result: '检定结论', color_marking: '彩色标志',
            }
            return (
              <Tag
                key={field}
                closable
                onClose={() => setColumnFilter(field, undefined)}
              >{labels[field] || field}: {value}</Tag>
            )
          })}
        </Space>
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增器具</Button>
          <Button icon={<PlusOutlined />} onClick={() => setBatchCreateOpen(true)}>批量新增</Button>
          <Button icon={<UploadOutlined />} onClick={() => setBatchUploadOpen(true)}>批量上传报告</Button>
          <Button icon={<DownloadOutlined />} loading={exporting} disabled={selectedRowKeys.length === 0} onClick={handleExportReports}>
            批量导出报告{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}
          </Button>
          <Button icon={<FileExcelOutlined />} loading={exportingExcel} onClick={handleExportExcel}>导出Excel</Button>
          <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>导入台账</Button>
          <BatchCreateModal open={batchCreateOpen} onClose={() => setBatchCreateOpen(false)} source="instrument" />
        </Space>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        scroll={{ x: 1600 }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        size="middle"
      />

      <InstrumentDrawer
        open={drawerOpen}
        record={editingRecord}
        onClose={handleDrawerClose}
      />

      <ReportDialog
        open={reportDialogOpen}
        record={reportRecord}
        source="instrument"
        onClose={() => { setReportDialogOpen(false); setReportRecord(null); fetchData() }}
      />

      <BatchUploadDialog
        open={batchUploadOpen}
        source="instrument"
        uploadHint="器具名称_器具编号.pdf"
        onClose={() => { setBatchUploadOpen(false); fetchData() }}
      />

      <LedgerImportModal
        open={importModalOpen}
        source="instrument"
        onClose={() => { setImportModalOpen(false); fetchData() }}
      />
    </div>
  )
}
