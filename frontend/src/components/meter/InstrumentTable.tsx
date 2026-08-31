'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Table, Button, Space, Input, Tag, Tooltip, Popconfirm, Radio } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, FileTextOutlined, UploadOutlined, DownloadOutlined, FileExcelOutlined, ImportOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import type { FilterDropdownProps } from 'antd/es/table/interface'
import { InstrumentRecord, InstrumentFilter } from '@/types/meter'
import { deleteInstrument, getInstruments, exportInstrumentReports, exportInstrumentsExcel, searchInstrumentTypeahead, batchDeleteInstruments, getInstrumentIds } from '@/actions/meter'
import { renderTextFilterDropdown, renderMultiSelectFilterDropdown } from './FilterDropdown'
import { InstrumentDrawer } from './InstrumentDrawer'
import { ReportDialog } from './ReportDialog'
import { BatchUploadDialog } from './BatchUploadDialog'
import { BatchCreateModal } from './BatchCreateModal'
import { LedgerImportModal } from './LedgerImportModal'
import { InstrumentDateFilterModal } from './InstrumentDateFilterModal'
import dayjs from 'dayjs'

/** 筛选字段名 → InstrumentFilter 参数 key 的映射。
 *  文本列映射到 `*_like`（部分匹配，输入即过滤）；部门/状态走精确多选；日期/报告各走原逻辑。 */
const INSTRUMENT_FILTER_KEY: Record<string, keyof InstrumentFilter> = {
  department: 'department',
  asset_number: 'asset_number_like',
  instrument_name: 'instrument_name_like',
  model_spec: 'model_spec_like',
  measurement_range: 'measurement_range_like',
  accuracy_grade: 'accuracy_grade_like',
  serial_number: 'serial_number_like',
  location: 'location_like',
  manufacturer: 'manufacturer_like',
  status: 'status',
  calibration_unit: 'calibration_unit_like',
  calibration_result: 'calibration_result_like',
  color_marking: 'color_marking_like',
  calibration_date_before: 'calibration_date_before',
  calibration_date_after: 'calibration_date_after',
  next_calibration_before: 'next_calibration_before',
  next_calibration_after: 'next_calibration_after',
  report_count: 'has_report',
}

/** 部门/状态等分类列的选项，通过 typeahead（空关键字=全集）按需拉取，避免全量预载。 */
const fetchInstrumentDeptOptions = async () =>
  (await searchInstrumentTypeahead('department', '', 200)).items
const fetchInstrumentStatusOptions = async () =>
  (await searchInstrumentTypeahead('status', '', 200)).items

export function InstrumentTable() {
  const { message, modal } = App.useApp()
  const [data, setData] = useState<InstrumentRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [inputValue, setInputValue] = useState('')
  const kwTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<InstrumentRecord | null>(null)
  const [reportDialogOpen, setReportDialogOpen] = useState(false)
  const [reportRecord, setReportRecord] = useState<InstrumentRecord | null>(null)
  const [batchUploadOpen, setBatchUploadOpen] = useState(false)
  const [batchCreateOpen, setBatchCreateOpen] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [selectAllAcrossPages, setSelectAllAcrossPages] = useState(false)
  const [fetchingAllIds, setFetchingAllIds] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportingExcel, setExportingExcel] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [dateModalOpen, setDateModalOpen] = useState(false)
  const [dateModalField, setDateModalField] = useState<'calibration_date' | 'next_calibration_date'>('calibration_date')

  // 列头筛选状态（服务端筛选）
  const [columnFilters, setColumnFilters] = useState<Record<string, string | undefined>>({})
  const [dateFilters, setDateFilters] = useState<Record<string, string | undefined>>({})

  const setColumnFilter = useCallback((field: string, value: string | undefined) => {
    setColumnFilters(prev => ({ ...prev, [field]: value }))
    setPage(1)
  }, [])

  const setDateFilter = useCallback((field: string, value: string | undefined) => {
    setDateFilters(prev => ({ ...prev, [field]: value }))
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
        if (key && value) {
          if (key === 'has_report') (params as Record<string, unknown>)[key] = value === 'true'
          else (params as Record<string, unknown>)[key] = value
        }
      }
      // 合并日期筛选条件
      for (const [field, value] of Object.entries(dateFilters)) {
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
  }, [page, pageSize, keyword, columnFilters, dateFilters])

  // setTimeout 延后到下一 tick，避免 effect 内同步 setState 链（react-hooks/set-state-in-effect）
  useEffect(() => {
    const t = setTimeout(fetchData, 0)
    return () => clearTimeout(t)
  }, [fetchData])

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
        if (key && value) {
          if (key === 'has_report') (filterParams as Record<string, unknown>)[key] = value === 'true'
          else (filterParams as Record<string, unknown>)[key] = value
        }
      }
      for (const [field, value] of Object.entries(dateFilters)) {
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

  // 构建当前筛选参数
  const buildFilterParams = useCallback((): InstrumentFilter => {
    const params: InstrumentFilter = {}
    if (keyword) params.keyword = keyword
    for (const [field, value] of Object.entries(columnFilters)) {
      const key = INSTRUMENT_FILTER_KEY[field]
      if (key && value) {
        if (key === 'has_report') (params as Record<string, unknown>)[key] = value === 'true'
        else (params as Record<string, unknown>)[key] = value
      }
    }
    for (const [field, value] of Object.entries(dateFilters)) {
      const key = INSTRUMENT_FILTER_KEY[field]
      if (key && value) (params as Record<string, unknown>)[key] = value
    }
    return params
  }, [keyword, columnFilters, dateFilters])

  const handleSelectAllAcrossPages = async () => {
    if (selectAllAcrossPages) {
      setSelectAllAcrossPages(false)
      setSelectedRowKeys([])
      return
    }
    setFetchingAllIds(true)
    try {
      const ids = await getInstrumentIds(buildFilterParams())
      setSelectedRowKeys(ids)
      setSelectAllAcrossPages(true)
      message.success(`已选中 ${ids.length} 条记录`)
    } catch {
      message.error('获取全量 ID 失败')
    } finally {
      setFetchingAllIds(false)
    }
  }

  const handleBatchDelete = () => {
    const count = selectedRowKeys.length
    modal.confirm({
      title: '批量删除确认',
      content: `确定要删除选中的 ${count} 条记录吗？此操作不可撤销。`,
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const result = await batchDeleteInstruments(selectedRowKeys as string[])
          message.success(`成功删除 ${result.deleted_count} 条记录`)
          setSelectedRowKeys([])
          setSelectAllAcrossPages(false)
          fetchData()
        } catch {
          message.error('批量删除失败')
        }
      },
    })
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

  // 文本列：输入即过滤（部分匹配）
  const textFilter = (field: string, label: string) =>
    renderTextFilterDropdown({
      value: columnFilters[field],
      onChange: (v) => setColumnFilter(field, v),
      field,
      placeholder: `输入${label}搜索`,
      fetchTypeahead: (q) => searchInstrumentTypeahead(field, q),
    })

  // 分类列：按需拉取选项的多选
  const multiFilter = (field: string, label: string, fetch: () => Promise<string[]>) =>
    renderMultiSelectFilterDropdown({
      value: columnFilters[field],
      onChange: (v) => setColumnFilter(field, v),
      field,
      placeholder: `选择${label}`,
      fetchOptions: fetch,
    })

  const columns: TableColumnsType<InstrumentRecord> = [
    {
      title: '部门', dataIndex: 'department', width: 120, ellipsis: true,
      filteredValue: columnFilters.department ? columnFilters.department.split(',') : null,
      filterDropdown: multiFilter('department', '部门', fetchInstrumentDeptOptions),
      onFilter: () => true,
    },
    {
      title: '资产编号', dataIndex: 'asset_number', width: 120,
      filteredValue: columnFilters.asset_number ? columnFilters.asset_number.split(',') : null,
      filterDropdown: textFilter('asset_number', '资产编号'),
      onFilter: () => true,
    },
    {
      title: '器具名称', dataIndex: 'instrument_name', width: 160, ellipsis: true,
      filteredValue: columnFilters.instrument_name ? columnFilters.instrument_name.split(',') : null,
      filterDropdown: textFilter('instrument_name', '器具名称'),
      onFilter: () => true,
    },
    {
      title: '型号规格', dataIndex: 'model_spec', width: 100, ellipsis: true,
      filteredValue: columnFilters.model_spec ? columnFilters.model_spec.split(',') : null,
      filterDropdown: textFilter('model_spec', '型号规格'),
      onFilter: () => true,
    },
    { title: '测量范围', dataIndex: 'measurement_range', width: 120, ellipsis: true,
      filteredValue: columnFilters.measurement_range ? columnFilters.measurement_range.split(',') : null,
      filterDropdown: textFilter('measurement_range', '测量范围'),
      onFilter: () => true,
    },
    {
      title: '精度等级', dataIndex: 'accuracy_grade', width: 80,
      filteredValue: columnFilters.accuracy_grade ? columnFilters.accuracy_grade.split(',') : null,
      filterDropdown: textFilter('accuracy_grade', '精度等级'),
      onFilter: () => true,
    },
    { title: '检定周期(月)', dataIndex: 'calibration_cycle_months', width: 90 },
    {
      title: '彩色标志', dataIndex: 'color_marking', width: 80,
      filteredValue: columnFilters.color_marking ? columnFilters.color_marking.split(',') : null,
      filterDropdown: textFilter('color_marking', '彩色标志'),
      onFilter: () => true,
    },
    {
      title: '器具编号', dataIndex: 'serial_number', width: 110, ellipsis: true,
      filteredValue: columnFilters.serial_number ? columnFilters.serial_number.split(',') : null,
      filterDropdown: textFilter('serial_number', '器具编号'),
      onFilter: () => true,
    },
    {
      title: '使用地点', dataIndex: 'location', width: 200, ellipsis: true,
      filteredValue: columnFilters.location ? columnFilters.location.split(',') : null,
      filterDropdown: textFilter('location', '使用地点'),
      onFilter: () => true,
    },
    {
      title: '制造商', dataIndex: 'manufacturer', width: 120, ellipsis: true,
      filteredValue: columnFilters.manufacturer ? columnFilters.manufacturer.split(',') : null,
      filterDropdown: textFilter('manufacturer', '制造商'),
      onFilter: () => true,
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      filteredValue: columnFilters.status ? columnFilters.status.split(',') : null,
      filterDropdown: multiFilter('status', '状态', fetchInstrumentStatusOptions),
      onFilter: () => true,
      render: (_: unknown, r: InstrumentRecord) => statusTag(r.status),
    },
    {
      title: '检定日期', dataIndex: 'calibration_date', width: 110,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
      filteredValue: (dateFilters.calibration_date_after || dateFilters.calibration_date_before) ? [dateFilters.calibration_date_after || ''] : null,
      filterDropdown: () => (
        <div style={{ padding: 8, minWidth: 160 }}>
          <Button type="link" size="small" onClick={() => { setDateModalField('calibration_date'); setDateModalOpen(true) }}>
            日期筛选...
          </Button>
        </div>
      ),
      onFilter: () => true,
    },
    {
      title: '下次检定', dataIndex: 'next_calibration_date', width: 110,
      render: (v: string) => {
        if (!v) return '-'
        const d = dayjs(v)
        const overdue = d.isBefore(dayjs())
        return <span style={{ color: overdue ? '#e03131' : undefined }}>{d.format('YYYY-MM-DD')}</span>
      },
      filteredValue: (dateFilters.next_calibration_after || dateFilters.next_calibration_before) ? [dateFilters.next_calibration_after || ''] : null,
      filterDropdown: () => (
        <div style={{ padding: 8, minWidth: 160 }}>
          <Button type="link" size="small" onClick={() => { setDateModalField('next_calibration_date'); setDateModalOpen(true) }}>
            日期筛选...
          </Button>
        </div>
      ),
      onFilter: () => true,
    },
    {
      title: '检定单位', dataIndex: 'calibration_unit', width: 100, ellipsis: true,
      filteredValue: columnFilters.calibration_unit ? columnFilters.calibration_unit.split(',') : null,
      filterDropdown: textFilter('calibration_unit', '检定单位'),
      onFilter: () => true,
    },
    {
      title: '检定结论', dataIndex: 'calibration_result', width: 80,
      filteredValue: columnFilters.calibration_result ? columnFilters.calibration_result.split(',') : null,
      filterDropdown: textFilter('calibration_result', '检定结论'),
      onFilter: () => true,
    },
    {
      title: '备注', dataIndex: 'remark', width: 120, ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '报告', dataIndex: 'report_count', width: 80,
      filteredValue: columnFilters.report_count ? columnFilters.report_count.split(',') : null,
      render: (v: number) => v > 0 ? <Tag color="blue">有</Tag> : <Tag>无</Tag>,
      filterDropdown: ({ setSelectedKeys, selectedKeys }: FilterDropdownProps) => (
        <div style={{ padding: 8 }}>
          <Radio.Group
            value={selectedKeys[0]}
            onChange={e => {
              setSelectedKeys(e.target.value ? [e.target.value] : [])
              setColumnFilter('report_count', e.target.value || undefined)
            }}
          >
            <Radio.Button value="true">有</Radio.Button>
            <Radio.Button value="false">无</Radio.Button>
          </Radio.Group>
          <div style={{ marginTop: 8 }}>
            <a onClick={() => { setSelectedKeys([]); setColumnFilter('report_count', undefined) }}>重置</a>
          </div>
        </div>
      ),
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
            placeholder="搜索资产编号/名称/型号/制造商"
            prefix={<SearchOutlined />}
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value)
              if (kwTimer.current) clearTimeout(kwTimer.current)
              kwTimer.current = setTimeout(() => { setKeyword(e.target.value); setPage(1) }, 400)
            }}
            style={{ width: 260 }}
            allowClear
          />
          {/* 已激活筛选标签 */}
          {Object.entries(columnFilters).filter(([, v]) => v).flatMap(([field, value]) => {
            const labels: Record<string, string> = {
              department: '部门', asset_number: '资产编号', instrument_name: '器具名称',
              model_spec: '型号', measurement_range: '测量范围', accuracy_grade: '精度',
              serial_number: '器具编号', location: '地点', manufacturer: '制造商', status: '状态',
              calibration_unit: '检定单位', calibration_result: '检定结论', color_marking: '彩色标志',
            }
            // 仅部门/状态为逗号分隔的多选；文本列是自由输入，含逗号也不能拆
            const key = INSTRUMENT_FILTER_KEY[field]
            const values = (key === 'department' || key === 'status' ? value!.split(',') : [value!]).filter(Boolean)
            return values.map((v) => (
              <Tag
                key={`${field}-${v}`}
                closable
                onClose={() => {
                  const newVals = values.filter(x => x !== v)
                  setColumnFilter(field, newVals.length > 0 ? newVals.join(',') : undefined)
                }}
              >{labels[field] || field}: {v}</Tag>
            ))
          })}
          {/* 日期筛选标签 */}
          {dateFilters.calibration_date_after && (
            <Tag
              closable
              onClose={() => { setDateFilter('calibration_date_after', undefined); setDateFilter('calibration_date_before', undefined) }}
            >检定日期: {dateFilters.calibration_date_after}{dateFilters.calibration_date_before && dateFilters.calibration_date_before !== dateFilters.calibration_date_after ? ` ~ ${dateFilters.calibration_date_before}` : ''}</Tag>
          )}
          {dateFilters.next_calibration_after && (
            <Tag
              closable
              onClose={() => { setDateFilter('next_calibration_after', undefined); setDateFilter('next_calibration_before', undefined) }}
            >下次检定: {dateFilters.next_calibration_after}{dateFilters.next_calibration_before && dateFilters.next_calibration_before !== dateFilters.next_calibration_after ? ` ~ ${dateFilters.next_calibration_before}` : ''}</Tag>
          )}
        </Space>
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增器具</Button>
          <Button icon={<PlusOutlined />} onClick={() => setBatchCreateOpen(true)}>批量新增</Button>
          <Button icon={<UploadOutlined />} onClick={() => setBatchUploadOpen(true)}>批量上传报告</Button>
          <Popconfirm title={`确定导出选中的 ${selectedRowKeys.length} 份报告？`} onConfirm={handleExportReports}>
            <Button icon={<DownloadOutlined />} loading={exporting} disabled={selectedRowKeys.length === 0}>
              批量导出报告{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}
            </Button>
          </Popconfirm>
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={handleBatchDelete}
          >
            批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}
          </Button>
          {selectedRowKeys.length > 0 && total > pageSize && (
            <Button loading={fetchingAllIds} onClick={handleSelectAllAcrossPages}>
              {selectAllAcrossPages ? `取消全选 (${selectedRowKeys.length})` : `全选所有 ${total} 条`}
            </Button>
          )}
          <Popconfirm title="确定导出当前筛选结果？" onConfirm={handleExportExcel}>
            <Button icon={<FileExcelOutlined />} loading={exportingExcel}>导出Excel</Button>
          </Popconfirm>
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
          onChange: (keys) => {
            setSelectedRowKeys(keys)
            if (keys.length === 0) setSelectAllAcrossPages(false)
          },
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
        onClose={() => { setBatchUploadOpen(false); fetchData() }}
      />

      <LedgerImportModal
        open={importModalOpen}
        source="instrument"
        onClose={() => { setImportModalOpen(false); fetchData() }}
      />

      <InstrumentDateFilterModal
        open={dateModalOpen}
        initialField={dateModalField}
        columnFilters={columnFilters}
        keyword={keyword}
        onClose={() => setDateModalOpen(false)}
        onConfirm={(params) => {
          // 清空旧日期筛选
          setDateFilter('calibration_date_after', undefined)
          setDateFilter('calibration_date_before', undefined)
          setDateFilter('next_calibration_after', undefined)
          setDateFilter('next_calibration_before', undefined)
          // 应用新筛选
          if (params.field === 'calibration_date') {
            if (params.after) setDateFilter('calibration_date_after', params.after)
            if (params.before) setDateFilter('calibration_date_before', params.before)
          } else {
            if (params.after) setDateFilter('next_calibration_after', params.after)
            if (params.before) setDateFilter('next_calibration_before', params.before)
          }
          setDateModalOpen(false)
        }}
      />
    </div>
  )
}
