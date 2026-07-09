'use client'

import { useCallback, useEffect, useState, type Key } from 'react'
import { App, Table, Button, Space, Input, Select, Tag, Tooltip, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, FileTextOutlined, UploadOutlined, DownloadOutlined, FileExcelOutlined, ImportOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { GasDetectorRecord, GasDetectorFilter, GasDetectorFilterOptions } from '@/types/meter'
import { deleteGasDetector, getGasDetectors, exportGasDetectorReports, exportGasDetectorsExcel, getGasDetectorFilterOptions } from '@/actions/meter'
import { GasDetectorDrawer } from './GasDetectorDrawer'
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
  return ({ setSelectedKeys, selectedKeys }: { setSelectedKeys: (keys: Key[]) => void; selectedKeys: Key[] }) => (
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

/** 筛选字段名 → GasDetectorFilter 参数 key 的映射 */
const GAS_DETECTOR_FILTER_KEY: Record<string, keyof GasDetectorFilter> = {
  department: 'department',
  instrument_name: 'instrument_name',
  detection_model: 'detection_model',
  product_number: 'product_number',
  installation_type: 'installation_type',
  installation_location: 'installation_location',
  medium: 'medium',
  calibration_factor: 'calibration_factor',
  manufacturer_supplier: 'manufacturer_supplier',
  manufacturer: 'manufacturer',
  detection_unit: 'detection_unit',
  calibration_result: 'calibration_result',
}

export function GasDetectorTable() {
  const { message } = App.useApp()
  const [data, setData] = useState<GasDetectorRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<GasDetectorRecord | null>(null)
  const [reportDialogOpen, setReportDialogOpen] = useState(false)
  const [reportRecord, setReportRecord] = useState<GasDetectorRecord | null>(null)
  const [batchUploadOpen, setBatchUploadOpen] = useState(false)
  const [batchCreateOpen, setBatchCreateOpen] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [exporting, setExporting] = useState(false)
  const [exportingExcel, setExportingExcel] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)

  // 列头筛选状态（服务端筛选）
  const [columnFilters, setColumnFilters] = useState<Record<string, string | undefined>>({})
  const [filterOptions, setFilterOptions] = useState<GasDetectorFilterOptions>({
    department: [], instrument_name: [], detection_model: [], product_number: [],
    installation_type: [], installation_location: [], medium: [], calibration_factor: [],
    manufacturer_supplier: [], manufacturer: [], detection_unit: [], calibration_result: [],
  })

  // 首次加载时获取全表筛选选项
  useEffect(() => {
    getGasDetectorFilterOptions()
      .then(opts => setFilterOptions(prev => ({ ...prev, ...opts })))
      .catch(() => message.error('获取筛选选项失败'))
  }, [message])

  const setColumnFilter = useCallback((field: string, value: string | undefined) => {
    setColumnFilters(prev => ({ ...prev, [field]: value }))
    setPage(1)
  }, [])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: GasDetectorFilter = { page, page_size: pageSize }
      if (keyword) params.keyword = keyword
      // 合并列头筛选条件
      for (const [field, value] of Object.entries(columnFilters)) {
        const key = GAS_DETECTOR_FILTER_KEY[field]
        if (key && value) (params as Record<string, unknown>)[key] = value
      }
      const res = await getGasDetectors(params)
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
      await deleteGasDetector(id)
      message.success('删除成功')
      fetchData()
    } catch {
      message.error('删除失败')
    }
  }

  const handleEdit = (record: GasDetectorRecord) => {
    setEditingRecord(record)
    setDrawerOpen(true)
  }

  const handleCreate = () => {
    setEditingRecord(null)
    setDrawerOpen(true)
  }

  const handleDrawerClose = () => {
    setDrawerOpen(false)
    setEditingRecord(null)
    fetchData()
  }

  const handleExportReports = async () => {
    if (selectedRowKeys.length === 0) { message.warning('请先选择要导出的探测器'); return }
    setExporting(true)
    try {
      const result = await exportGasDetectorReports(selectedRowKeys as string[])
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
      const filterParams: GasDetectorFilter = {}
      if (keyword) filterParams.keyword = keyword
      for (const [field, value] of Object.entries(columnFilters)) {
        const key = GAS_DETECTOR_FILTER_KEY[field]
        if (key && value) (filterParams as Record<string, unknown>)[key] = value
      }
      const result = await exportGasDetectorsExcel(filterParams)
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

  const columns: TableColumnsType<GasDetectorRecord> = [
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
      title: '器具名称', dataIndex: 'instrument_name', width: 180, ellipsis: true,
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
      title: '检测型号', dataIndex: 'detection_model', width: 140, ellipsis: true,
      filteredValue: columnFilters.detection_model ? [columnFilters.detection_model] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.detection_model,
        columnFilters.detection_model,
        (v) => setColumnFilter('detection_model', v),
        '选择检测型号',
      ),
      onFilter: () => true,
    },
    { title: '量程', dataIndex: 'measurement_range', width: 120, ellipsis: true },
    {
      title: '产品编号', dataIndex: 'product_number', width: 120,
      filteredValue: columnFilters.product_number ? [columnFilters.product_number] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.product_number,
        columnFilters.product_number,
        (v) => setColumnFilter('product_number', v),
        '选择产品编号',
      ),
      onFilter: () => true,
    },
    {
      title: '安装方式', dataIndex: 'installation_type', width: 90,
      filteredValue: columnFilters.installation_type ? [columnFilters.installation_type] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.installation_type,
        columnFilters.installation_type,
        (v) => setColumnFilter('installation_type', v),
        '选择安装方式',
      ),
      onFilter: () => true,
      render: (v: string) => v === '固定式' ? <Tag color="blue">固定式</Tag> : v === '便携式' ? <Tag color="green">便携式</Tag> : v || '-',
    },
    {
      title: '安装位置', dataIndex: 'installation_location', width: 180, ellipsis: true,
      filteredValue: columnFilters.installation_location ? [columnFilters.installation_location] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.installation_location,
        columnFilters.installation_location,
        (v) => setColumnFilter('installation_location', v),
        '选择安装位置',
      ),
      onFilter: () => true,
    },
    {
      title: '使用介质', dataIndex: 'medium', width: 120, ellipsis: true,
      filteredValue: columnFilters.medium ? [columnFilters.medium] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.medium,
        columnFilters.medium,
        (v) => setColumnFilter('medium', v),
        '选择使用介质',
      ),
      onFilter: () => true,
    },
    {
      title: '标定系数', dataIndex: 'calibration_factor', width: 100, ellipsis: true,
      filteredValue: columnFilters.calibration_factor ? [columnFilters.calibration_factor] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.calibration_factor,
        columnFilters.calibration_factor,
        (v) => setColumnFilter('calibration_factor', v),
        '选择标定系数',
      ),
      onFilter: () => true,
    },
    {
      title: '传感器出厂日期', dataIndex: 'manufacturer_supplier', width: 140, ellipsis: true,
      filteredValue: columnFilters.manufacturer_supplier ? [columnFilters.manufacturer_supplier] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.manufacturer_supplier,
        columnFilters.manufacturer_supplier,
        (v) => setColumnFilter('manufacturer_supplier', v),
        '选择传感器出厂日期',
      ),
      onFilter: () => true,
    },
    {
      title: '制造单位', dataIndex: 'manufacturer', width: 140, ellipsis: true,
      filteredValue: columnFilters.manufacturer ? [columnFilters.manufacturer] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.manufacturer,
        columnFilters.manufacturer,
        (v) => setColumnFilter('manufacturer', v),
        '选择制造单位',
      ),
      onFilter: () => true,
    },
    {
      title: '检测单位', dataIndex: 'detection_unit', width: 120, ellipsis: true,
      filteredValue: columnFilters.detection_unit ? [columnFilters.detection_unit] : null,
      filterDropdown: renderFilterDropdown(
        filterOptions.detection_unit,
        columnFilters.detection_unit,
        (v) => setColumnFilter('detection_unit', v),
        '选择检测单位',
      ),
      onFilter: () => true,
    },
    {
      title: '检定时间', dataIndex: 'calibration_date', width: 110,
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
      title: '操作', key: 'actions', width: 160, fixed: 'right',
      render: (_: unknown, r: GasDetectorRecord) => (
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
            placeholder="搜索名称/型号/编号"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
            style={{ width: 260 }}
            allowClear
          />
          {/* 已激活筛选标签 */}
          {Object.entries(columnFilters).filter(([, v]) => v).map(([field, value]) => {
            const labels: Record<string, string> = {
              department: '部门', instrument_name: '器具名称', detection_model: '检测型号',
              product_number: '产品编号', installation_type: '安装方式',
              installation_location: '安装位置', medium: '介质',
              calibration_factor: '标定系数', manufacturer_supplier: '传感器出厂日期',
              manufacturer: '制造单位', detection_unit: '检测单位',
              calibration_result: '检定结论',
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
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增探测器</Button>
          <Button icon={<PlusOutlined />} onClick={() => setBatchCreateOpen(true)}>批量新增</Button>
          <Button icon={<UploadOutlined />} onClick={() => setBatchUploadOpen(true)}>批量上传报告</Button>
          <Button icon={<DownloadOutlined />} loading={exporting} disabled={selectedRowKeys.length === 0} onClick={handleExportReports}>
            批量导出报告{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}
          </Button>
          <Button icon={<FileExcelOutlined />} loading={exportingExcel} onClick={handleExportExcel}>导出Excel</Button>
          <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>导入台账</Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        scroll={{ x: 1500 }}
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

      <GasDetectorDrawer
        open={drawerOpen}
        record={editingRecord}
        onClose={handleDrawerClose}
      />

      <ReportDialog
        open={reportDialogOpen}
        record={reportRecord}
        source="gas_detector"
        onClose={() => { setReportDialogOpen(false); setReportRecord(null); fetchData() }}
      />

      <BatchUploadDialog
        open={batchUploadOpen}
        source="gas_detector"
        uploadHint="器具名称_产品编号.pdf"
        onClose={() => { setBatchUploadOpen(false); fetchData() }}
      />

      <BatchCreateModal
        open={batchCreateOpen}
        source="gas_detector"
        onClose={() => { setBatchCreateOpen(false); fetchData() }}
      />

      <LedgerImportModal
        open={importModalOpen}
        source="gas_detector"
        onClose={() => { setImportModalOpen(false); fetchData() }}
      />
    </div>
  )
}
