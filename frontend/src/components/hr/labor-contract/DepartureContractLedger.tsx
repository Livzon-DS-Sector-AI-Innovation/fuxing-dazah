'use client'

// 离职合同台账（P3）：离职人员合同单独管理，与在职台账分开（两本台账不交叉）。
// 需求第二章四块内容：人员信息 / 合同信息（历次起止、签订次数、最后一份期限）/
// 离职信息（终止方式、终止日期、审批依据）/ 手续状态（流程单号、证明开具送达、原件回收与归档）。
// 按部门、离职时间、终止方式筛选，可导出「离职人员合同情况说明」。仅 HR（后端限全量数据范围）。

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  App,
  Button,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import { DownloadOutlined, EditOutlined, EyeOutlined, UploadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import {
  archiveDepartureContract,
  exportDepartureContracts,
  fetchDepartureContractFilterOptions,
  fetchDepartureContracts,
  fetchDepartureFilterOptionsAction,
  updateDepartureContractProcedure,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr/download'
import { useDebouncedCallback } from '@/hooks/hr'
import { usePermission } from '@/hooks/usePermission'
import PageHeader from '@/components/hr/PageHeader'
import ContractDetailDrawer from '@/components/hr/ContractDetailDrawer'
import type {
  DepartureContractFilterOptions,
  DepartureContractProcedureInput,
  DepartureContractView,
} from '@/types/hr'

const CERT_COLORS: Record<DepartureContractView['certificate_status'], string> = {
  pending: 'default',
  issued: 'blue',
  delivering: 'orange',
  signed: 'green',
}
const ORIGINAL_COLORS: Record<DepartureContractView['contract_original_status'], string> = {
  unrecovered: 'orange',
  recovered: 'green',
  waived: 'default',
}

interface ProcedureValues {
  termination_type?: string
  approval_ref?: string
  separation_process_no?: string
  contract_original_status: NonNullable<DepartureContractView['contract_original_status']>
}

function reasonsText(r: DepartureContractView): string {
  const value = r.offboarding_reason
  if (Array.isArray(value)) return value.join('、') || '-'
  return value || '-'
}

export default function DepartureContractLedger() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:contract:manage')
  const [rows, setRows] = useState<DepartureContractView[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [department, setDepartment] = useState<string | undefined>()
  const [leaveRange, setLeaveRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [terminationType, setTerminationType] = useState<string | undefined>()
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [departments, setDepartures] = useState<string[]>([])
  const [filterOptions, setFilterOptions] = useState<DepartureContractFilterOptions | null>(null)
  const [exporting, setExporting] = useState(false)
  const seqRef = useRef(0)
  const pageSize = 20

  // 合同详情抽屉（扫描件预览/下载/版本）
  const [detailId, setDetailId] = useState<string | null>(null)
  // 人工项维护（终止方式更正 / 审批依据 / 流程单号 / 原件回收）
  const [procedureTarget, setProcedureTarget] = useState<DepartureContractView | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<ProcedureValues>()
  // 扫描件归档（无合同行时后端按离职记录合同信息建档）
  const [archiveTarget, setArchiveTarget] = useState<DepartureContractView | null>(null)
  const [archiveFiles, setArchiveFiles] = useState<UploadFile[]>([])
  const [archiveRemark, setArchiveRemark] = useState('')
  const [archiving, setArchiving] = useState(false)

  /** 当前列表的筛选参数（不含分页） */
  const filterParams = useCallback(() => ({
    department,
    date_from: leaveRange?.[0]?.format('YYYY-MM-DD'),
    date_to: leaveRange?.[1]?.format('YYYY-MM-DD'),
    termination_type: terminationType as DepartureContractView['termination_type'] | undefined,
    keyword: keyword || undefined,
  }), [department, leaveRange, terminationType, keyword])

  // 事件驱动的刷新（翻页 / 维护或归档后）：可以直接进 loading
  const load = useCallback(
    async (targetPage = page) => {
      // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
      const seq = ++seqRef.current
      setLoading(true)
      try {
        const res = await fetchDepartureContracts({ ...filterParams(), page: targetPage, page_size: pageSize })
        if (seq !== seqRef.current) return
        setRows(res.data)
        setTotal(res.meta.total)
      } catch (err) {
        if (seq === seqRef.current) message.error(err instanceof Error ? err.message : '加载离职合同台账失败')
      } finally {
        if (seq === seqRef.current) setLoading(false)
      }
    },
    [filterParams, page, message],
  )

  // 筛选变化重新拉取第一页：setState 全部在 await 之后，不在 effect 里同步触发级联渲染
  // （回到第一页由筛选控件的 onChange 负责）
  useEffect(() => {
    const seq = ++seqRef.current
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetchDepartureContracts({ ...filterParams(), page: 1, page_size: pageSize })
        if (cancelled || seq !== seqRef.current) return
        setRows(res.data)
        setTotal(res.meta.total)
      } catch (err) {
        if (!cancelled) message.error(err instanceof Error ? err.message : '加载离职合同台账失败')
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterParams])

  // 筛选字典 + 部门下拉（沿用离职台账的现有取值聚合，跟随飞书源表）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const [optionsRes, deptRes] = await Promise.allSettled([
        fetchDepartureContractFilterOptions(),
        fetchDepartureFilterOptionsAction(),
      ])
      if (cancelled) return
      setFilterOptions(optionsRes.status === 'fulfilled' ? optionsRes.value.data : null)
      setDepartures(deptRes.status === 'fulfilled' ? (deptRes.value.departments || []) : [])
    })()
    return () => { cancelled = true }
  }, [])

  const applyKeyword = (val: string) => {
    // 只更新筛选状态：拉取由上面的 effect 负责
    setKeyword(val.trim())
    setPage(1)
  }
  const { run: debouncedKeyword } = useDebouncedCallback(applyKeyword, 300)

  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await exportDepartureContracts(filterParams())
      downloadBase64File(res.base64, res.filename || '离职人员合同情况说明.xlsx')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const openProcedure = (r: DepartureContractView) => {
    form.setFieldsValue({
      termination_type: r.termination_type_overridden ? r.termination_type : undefined,
      approval_ref: r.approval_ref || undefined,
      // 已有办结单编号时不回填（那是办结单的，不是补录值）
      separation_process_no: r.process_no_source === 'manual' ? (r.separation_process_no ?? undefined) : undefined,
      contract_original_status: r.contract_original_status,
    })
    setProcedureTarget(r)
  }

  const handleProcedureSave = async () => {
    if (!procedureTarget) return
    let values: ProcedureValues
    try {
      values = await form.validateFields()
    } catch {
      return // 校验失败只走行内提示
    }
    setSaving(true)
    try {
      const payload: DepartureContractProcedureInput = {
        termination_type: values.termination_type ?? '',
        approval_ref: values.approval_ref ?? '',
        separation_process_no: values.separation_process_no ?? '',
        contract_original_status: values.contract_original_status,
      }
      await updateDepartureContractProcedure(procedureTarget.id, payload)
      message.success('已保存')
      setProcedureTarget(null)
      void load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const openArchive = (r: DepartureContractView) => {
    setArchiveFiles([])
    setArchiveRemark('')
    setArchiveTarget(r)
  }

  const handleArchive = async () => {
    const file = archiveFiles[0]?.originFileObj as File | undefined
    if (!archiveTarget) return
    if (!file) { message.warning('请选择合同扫描件（图片/PDF）'); return }
    setArchiving(true)
    try {
      const res = await archiveDepartureContract(archiveTarget.id, file, archiveRemark)
      message.success(res.message || '已归档')
      setArchiveTarget(null)
      void load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '归档失败')
    } finally {
      setArchiving(false)
    }
  }

  const latestContractId = (r: DepartureContractView) =>
    r.contracts.length ? r.contracts[r.contracts.length - 1].id : null

  const manualChoices = (filterOptions?.termination_types || []).filter((o) => o.value !== 'none')

  return (
    <div className="space-y-4">
      <PageHeader
        title="离职合同台账"
        description="离职人员的合同终止记录、原件与材料单独管理，与在职台账分开；离职人员合同不再参与到期预警"
        actions={
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => void handleExport()}>
            导出合同情况说明
          </Button>
        }
      />

      <div className="flex flex-wrap gap-3 items-center">
        <Select
          placeholder="部门"
          value={department}
          onChange={(v) => { setDepartment(v); setPage(1) }}
          showSearch
          allowClear
          optionFilterProp="label"
          style={{ width: 200 }}
          options={departments.map((d) => ({ value: d, label: d }))}
        />
        <DatePicker.RangePicker
          value={leaveRange}
          onChange={(range) => { setLeaveRange(range as [Dayjs, Dayjs] | null); setPage(1) }}
          allowClear
        />
        <Select
          placeholder="合同终止方式"
          value={terminationType}
          onChange={(v) => { setTerminationType(v); setPage(1) }}
          allowClear
          style={{ width: 190 }}
          options={manualChoices.map((o) => ({ value: o.value, label: o.label }))}
        />
        <Input
          placeholder="搜索姓名/工号"
          value={keywordInput}
          onChange={(e) => { setKeywordInput(e.target.value); debouncedKeyword(e.target.value) }}
          onPressEnter={(e) => applyKeyword((e.target as HTMLInputElement).value)}
          allowClear
          style={{ width: 200 }}
        />
      </div>

      <Table<DepartureContractView>
        rowKey="id"
        size="middle"
        loading={loading}
        dataSource={rows}
        scroll={{ x: 1157 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 人`,
          onChange: (p) => { setPage(p); void load(p) },
        }}
        expandable={{
          expandedRowRender: (r) => (
            <Descriptions
              size="small"
              bordered
              column={{ xs: 1, md: 2, xl: 3 }}
              items={[
                { key: 'p', label: '员工性质', children: r.employee_category || '-' },
                { key: 'pos', label: '岗位', children: r.position || '-' },
                {
                  key: 'count', label: '合同签订次数',
                  children: r.contract_count_known ? `${r.contract_count} 份` : (r.has_contract ? '离职台账登记 1 份' : '无合同记录'),
                },
                { key: 'term', label: '最后一份期限', children: r.term_label_last || '-' },
                { key: 'periods', label: '历次合同起止', children: r.contract_periods_text || '-', span: 3 },
                { key: 'leave', label: '离职日期', children: r.offboarding_date || '-' },
                { key: 'type', label: '离职类型', children: r.offboarding_type },
                { key: 'reason', label: '离职原因', children: reasonsText(r) },
                {
                  key: 'term_type', label: '合同终止/解除方式',
                  children: (
                    <Space size={4}>
                      <span>{r.termination_type_label}</span>
                      {r.termination_type_overridden && <Tag color="purple">人工更正</Tag>}
                    </Space>
                  ),
                },
                { key: 'term_date', label: '合同终止日期', children: r.termination_date || '-' },
                {
                  key: 'approval', label: '审批依据',
                  children: r.approval_refs.length ? r.approval_refs.join('；') : '-',
                },
                {
                  key: 'process', label: '离职流程单号',
                  children: (
                    <Space size={4}>
                      <span>{r.separation_process_no || '-'}</span>
                      {r.process_no_source === 'case' && <Tag>办结单</Tag>}
                      {r.process_no_source === 'manual' && <Tag color="blue">补录</Tag>}
                    </Space>
                  ),
                },
                {
                  key: 'cert', label: '离职证明',
                  children: <Tag color={CERT_COLORS[r.certificate_status]}>{r.certificate_status_label}</Tag>,
                },
                {
                  key: 'original', label: '合同原件',
                  children: <Tag color={ORIGINAL_COLORS[r.contract_original_status]}>{r.contract_original_status_label}</Tag>,
                },
                {
                  key: 'archive', label: '扫描件',
                  children: (
                    <Tooltip title={r.archive_status === 'archived' ? '扫描件在合同详情里预览/下载' : undefined}>
                      <Tag color={r.archive_status === 'archived' ? 'green' : 'orange'}>{r.archive_status_label}</Tag>
                    </Tooltip>
                  ),
                },
              ]}
            />
          ),
        }}
        columns={[
          {
            title: '姓名 / 工号', width: 130,
            render: (_, r) => (
              <div>
                <div className="font-medium">{r.name}</div>
                <div className="text-xs text-gray-500">{r.employee_number || '无工号'}</div>
              </div>
            ),
          },
          // 列宽合计 1157：岗位、合同终止日期等次要信息放在行内展开的详情里，1440 宽度下不横向滚动
          { title: '部门', dataIndex: 'department', width: 108, ellipsis: { showTitle: true } },
          { title: '离职日期', dataIndex: 'offboarding_date', width: 104, render: (v) => v || '-' },
          {
            title: '历次合同起止', width: 205,
            render: (_, r) => (
              <Tooltip title={r.contract_periods_text || undefined}>
                <span className="text-[13px]">{r.contract_periods_text || '无合同记录'}</span>
              </Tooltip>
            ),
            ellipsis: true,
          },
          {
            title: '终止方式', width: 160,
            render: (_, r) => (
              <Tooltip title={r.termination_type_overridden ? 'HR 人工更正过；在「维护」里清空后按离职日期与离职类型自动判定' : r.termination_date ? `合同终止日期 ${r.termination_date}` : undefined}>
                <span>
                  {r.termination_type_label}
                  {r.termination_type_overridden && <Tag color="purple" className="ml-1">更正</Tag>}
                </span>
              </Tooltip>
            ),
          },
          {
            title: '手续状态', width: 250,
            render: (_, r) => (
              <Space size={4}>
                <Tooltip title="离职证明开具 / 送达">
                  <Tag color={CERT_COLORS[r.certificate_status]}>证明{r.certificate_status_label}</Tag>
                </Tooltip>
                <Tooltip title="合同原件回收">
                  <Tag color={ORIGINAL_COLORS[r.contract_original_status]}>原件{r.contract_original_status_label}</Tag>
                </Tooltip>
                <Tag color={r.archive_status === 'archived' ? 'green' : 'orange'}>{r.archive_status_label}</Tag>
              </Space>
            ),
          },
          {
            title: '操作', width: 200, fixed: 'right',
            render: (_, r) => (
              <Space size={0}>
                <Tooltip title="上传合同扫描件">
                  <Button type="link" size="small" icon={<UploadOutlined />} onClick={() => openArchive(r)}>
                    归档
                  </Button>
                </Tooltip>
                <Tooltip title="维护终止方式 / 审批依据 / 流程单号 / 原件回收">
                  <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openProcedure(r)}>
                    维护
                  </Button>
                </Tooltip>
                <Tooltip title="合同详情（扫描件预览 / 下载 / 版本）">
                  <Button
                    type="link" size="small" icon={<EyeOutlined />}
                    disabled={!latestContractId(r)}
                    onClick={() => setDetailId(latestContractId(r))}
                  >
                    详情
                  </Button>
                </Tooltip>
              </Space>
            ),
          },
        ]}
      />

      <ContractDetailDrawer
        contractId={detailId}
        canManage={canManage}
        onClose={() => setDetailId(null)}
        onChanged={() => void load()}
      />

      {/* 人工项维护：终止方式更正 / 审批依据 / 流程单号 / 原件回收 */}
      <Modal
        title={`维护合同台账 — ${procedureTarget?.name || ''}`}
        open={!!procedureTarget}
        okText="保存"
        confirmLoading={saving}
        onCancel={() => setProcedureTarget(null)}
        onOk={() => void handleProcedureSave()}
        destroyOnHidden
      >
        <Form<ProcedureValues> form={form} layout="vertical" className="pt-2">
          <Form.Item
            name="termination_type"
            label="合同终止/解除方式"
            extra={
              procedureTarget
                ? `留空 = 自动判定（当前：${procedureTarget.termination_type_label}）`
                : undefined
            }
          >
            <Select
              allowClear
              placeholder="按离职日期与离职类型自动判定"
              options={manualChoices.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Form.Item>
          <Form.Item name="approval_ref" label="审批依据" extra="审批实例 / 流程单号；有飞书审批实例时系统会自动带出">
            <Input maxLength={128} allowClear placeholder="如：离职审批单号" />
          </Form.Item>
          <Form.Item
            name="separation_process_no"
            label="离职流程单号"
            extra={
              procedureTarget?.process_no_source === 'case'
                ? `已有离职办结单 ${procedureTarget.separation_process_no}，以办结单编号为准；这里只在没有办结单时补录`
                : '有离职办结单时以办结单编号为准'
            }
          >
            <Input maxLength={64} allowClear placeholder="历史流程单号可在此补录" />
          </Form.Item>
          <Form.Item
            name="contract_original_status"
            label="合同原件回收状态"
            rules={[{ required: true, message: '请选择原件回收状态' }]}
          >
            <Select
              options={(filterOptions?.original_statuses || []).map((o) => ({ value: o.value, label: o.label }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 扫描件归档：一份合同一个合并文件；无合同行时后端按离职记录合同信息建档 */}
      <Modal
        title={`归档合同扫描件 — ${archiveTarget?.name || ''}`}
        open={!!archiveTarget}
        okText="上传归档"
        confirmLoading={archiving}
        okButtonProps={{ disabled: archiveFiles.length === 0 }}
        onCancel={() => setArchiveTarget(null)}
        onOk={() => void handleArchive()}
        destroyOnHidden
      >
        <div className="space-y-3 pt-2">
          <div className="text-[13px] text-gray-500">
            逐页合并为一份扫描件（图片/PDF，≤20MB）。
            {archiveTarget && !archiveTarget.has_contract_rows
              ? '该人员不在合同表：上传后按离职记录的合同起止日期建一份已终止合同并归档。'
              : '已有扫描件时上传为新版本，旧版本保留可查。'}
          </div>
          <Upload
            accept=".jpg,.jpeg,.png,.webp,.bmp,.pdf"
            maxCount={1}
            fileList={archiveFiles}
            beforeUpload={() => false}
            onChange={({ fileList }) => setArchiveFiles(fileList)}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <Input
            placeholder="备注（选填）"
            maxLength={512}
            value={archiveRemark}
            onChange={(e) => setArchiveRemark(e.target.value)}
          />
        </div>
      </Modal>
    </div>
  )
}
