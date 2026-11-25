'use client'

// 劳动合同台账（在职）：列表 + 筛选 + 录入/详情入口 + 行内快捷动作。
// 期限/状态标签由后端按签订次数自动计算下发，前端只读展示；
// 审批、盖章、领取、续签等流转动作在详情抽屉内操作（单入口，防误触）。

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Alert, Button, Input, Select, Space, Table, Tag, Tooltip } from 'antd'
import { FileAddOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import PageHeader from '@/components/hr/PageHeader'
import ContractDetailDrawer from '@/components/hr/ContractDetailDrawer'
import ContractFormModal from '@/components/hr/ContractFormModal'
import { LedgerImportModal } from '@/components/hr'
import { usePermission } from '@/hooks/usePermission'
import { fetchLaborContracts } from '@/actions/hr'
import type { LaborContract, LaborContractStatus } from '@/types/hr'

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'active', label: '生效中' },
  { value: 'pending_renewal,renewing', label: '公告期/续签办理中' },
  { value: 'expired_unrenewed', label: '到期未续签' },
  { value: 'terminated', label: '已终止' },
  { value: 'superseded', label: '已续签取代' },
]

const STATUS_TAG_COLORS: Record<LaborContractStatus, string> = {
  active: 'green',
  pending_renewal: 'orange',
  renewing: 'blue',
  superseded: 'default',
  terminated: 'red',
  expired_unrenewed: 'volcano',
}

function daysUntil(endDate?: string | null): number | null {
  if (!endDate) return null
  const diff = new Date(endDate).getTime() - Date.now()
  return Math.ceil(diff / 86400000)
}

function endDateText(row: LaborContract): string {
  if (!row.end_date) return '无固定期限'
  const days = daysUntil(row.end_date)
  if (row.status === 'active' && days !== null && days >= 0 && days <= 50) {
    return `${row.end_date}（${days} 天后到期）`
  }
  return row.end_date
}

export default function ContractLedgerClient() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:contract:manage')

  const [rows, setRows] = useState<LaborContract[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [expiringDays, setExpiringDays] = useState<number | undefined>()
  const [detailId, setDetailId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const seqRef = useRef(0)
  const pageSize = 20

  const load = useCallback(
    async (
      targetPage = page,
      override?: { status?: string; keyword?: string; expiringDays?: number },
    ) => {
      // override：搜索/筛选事件里 setState 后立刻拉取时，绕过 useCallback 旧闭包（stale closure）
      const seq = ++seqRef.current
      setLoading(true)
      try {
        const st = override?.status ?? status
        const kw = override?.keyword ?? keyword
        const ed = override?.expiringDays ?? expiringDays
        const r = await fetchLaborContracts({
          status: st,
          keyword: kw || undefined,
          expiring_days: ed,
          page: targetPage,
          page_size: pageSize,
        })
        if (seq !== seqRef.current) return // 过期响应丢弃
        setRows(r.data)
        setTotal(r.meta.total)
      } catch (e) {
        if (seq === seqRef.current) message.error(e instanceof Error ? e.message : '加载台账失败')
      } finally {
        if (seq === seqRef.current) setLoading(false)
      }
    },
    [message, page, status, keyword, expiringDays],
  )

  // 筛选变化回到第一页重新加载
  useEffect(() => {
    void load(1)
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, expiringDays])

  const columns: ColumnsType<LaborContract> = [
    {
      title: '姓名 / 工号',
      width: 150,
      render: (_, r) => (
        <div>
          <div className="font-medium">{r.name}</div>
          <div className="text-xs text-gray-500">{r.employee_number}</div>
        </div>
      ),
    },
    { title: '部门', dataIndex: 'department', width: 140,
      ellipsis: { showTitle: true } },
    { title: '岗位', dataIndex: 'position', width: 120,
      render: (v) => v || '-',
      ellipsis: { showTitle: true } },
    { title: '签订次序', dataIndex: 'seq_label', width: 130 },
    { title: '合同期限', dataIndex: 'term_label', width: 100 },
    {
      title: '起始 ~ 到期',
      width: 230,
      render: (_, r) => (
        <span className="text-[13px]">
          {r.start_date || '-'} ~ {endDateText(r)}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (_, r) => (
        <Tooltip title={r.terminated_reason || r.remark || undefined}>
          <Tag color={STATUS_TAG_COLORS[r.status] ?? 'default'}>{r.status_label}</Tag>
        </Tooltip>
      ),
    },
    {
      title: '手续进度',
      width: 150,
      render: (_, r) => {
        const marks: string[] = []
        if (r.dept_decision) marks.push(r.dept_decision_label || '')
        if (r.stamped_at) marks.push('已盖章')
        if (r.delivered_at) marks.push('已领取')
        if (r.sign_confirmed_at) marks.push('已签字')
        return <span className="text-xs text-gray-600">{marks.length ? marks.join(' · ') : '-'}</span>
      },
    },
    {
      title: '操作',
      width: 90,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => setDetailId(r.id)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="劳动合同台账"
        description="合同签订、到期预警、续签审批与领取签字全流程台账（期限按签订次数自动计算）"
        actions={
          canManage && (
            <Space>
              <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>
                Excel导入
              </Button>
              <Button type="primary" icon={<FileAddOutlined />} onClick={() => setFormOpen(true)}>
                录入合同
              </Button>
            </Space>
          )
        }
      />

      <Space wrap>
        <Select
          allowClear
          placeholder="状态筛选"
          style={{ width: 190 }}
          value={status}
          onChange={(v) => setStatus(v)}
          options={STATUS_FILTERS}
        />
        <Select
          allowClear
          placeholder="到期窗口"
          style={{ width: 150 }}
          value={expiringDays}
          onChange={(v) => setExpiringDays(v)}
          options={[
            { value: 50, label: '公告期（50 天内到期）' },
            { value: 90, label: '90 天内到期' },
            { value: 180, label: '半年内到期' },
          ]}
        />
        <Input.Search
          allowClear
          placeholder="姓名 / 工号"
          style={{ width: 200 }}
          onSearch={(v) => {
            const kw = v.trim()
            setKeyword(kw)
            setPage(1)
            void load(1, { keyword: kw })
          }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()} />
      </Space>

      {!canManage && (
        <Alert
          type="info"
          showIcon
          message="您只有查看权限；公告期合同的审批、续签、盖章/领取等操作需要「管理劳动合同」权限。"
        />
      )}

      <Table<LaborContract>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1100 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 份合同`,
          onChange: (p) => {
            setPage(p)
            void load(p)
          },
        }}
      />

      <ContractDetailDrawer
        contractId={detailId}
        canManage={canManage}
        onClose={() => setDetailId(null)}
        onChanged={() => void load()}
      />

      <LedgerImportModal
        open={importOpen}
        ledger="contract"
        label="劳动合同"
        onClose={() => setImportOpen(false)}
        onSuccess={() => {
          setImportOpen(false)
          void load(1)
        }}
      />

      <ContractFormModal
        open={formOpen}
        mode="create"
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setFormOpen(false)
          void load(1)
          setPage(1)
        }}
      />
    </div>
  )
}
