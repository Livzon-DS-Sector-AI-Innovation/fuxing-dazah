'use client'

// 员工档案「劳动合同」页签（一人一事一档）：历次合同 + 各份扫描件 + 归档状态，
// 与「证件档案」页签并列，数据与合同台账同源。展开一行即该份合同的电子档案区
// （版本 / 上传换版 / 原件预览下载 / 调阅记录）。

import { useCallback, useEffect, useState } from 'react'
import { App, Empty, Table, Tag } from 'antd'
import { fetchEmployeeContracts } from '@/actions/hr'
import type { EmployeeContractsView, LaborContract } from '@/types/hr'
import ContractArchivePanel from './ContractArchivePanel'

export default function EmployeeContractsPanel({ employeeNumber }: { employeeNumber: string }) {
  const { message } = App.useApp()
  const [view, setView] = useState<EmployeeContractsView | null>(null)
  const [loading, setLoading] = useState(true)

  // 首次加载：setState 全部在 await 之后，不在 effect 里同步触发级联渲染
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchEmployeeContracts(employeeNumber)
        if (!cancelled) setView(r.data)
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载劳动合同失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeNumber])

  // 归档后的刷新（事件驱动）
  const load = useCallback(async () => {
    try {
      const r = await fetchEmployeeContracts(employeeNumber)
      setView(r.data)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '加载劳动合同失败')
    }
  }, [employeeNumber, message])

  const contracts = view?.contracts || []

  return (
    <Table<LaborContract>
      rowKey="id"
      size="small"
      loading={loading}
      pagination={false}
      dataSource={contracts}
      locale={{ emptyText: <Empty description="暂无劳动合同记录" className="py-6" /> }}
      expandable={{
        expandedRowRender: (c) => (
          <ContractArchivePanel
            contractId={c.id}
            archiveStatus={c.archive_status}
            canManage={!!view?.can_archive}
            canAccessFile={!!view?.can_access_file}
            onChanged={() => void load()}
          />
        ),
      }}
      columns={[
        { title: '签订次序', dataIndex: 'seq_label', width: 130 },
        { title: '合同期限', dataIndex: 'term_label', width: 100 },
        {
          title: '起始 ~ 到期', width: 240,
          render: (_, c) => (
            <span className="text-[13px]">{c.start_date || '-'} ~ {c.end_date || '无固定期限'}</span>
          ),
        },
        { title: '签订日', dataIndex: 'sign_date', width: 110, render: (v) => v || '-' },
        { title: '状态', dataIndex: 'status_label', width: 110 },
        {
          title: '归档', width: 90,
          render: (_, c) => (
            <Tag color={c.archive_status === 'archived' ? 'green' : 'orange'}>
              {c.archive_status === 'archived' ? '已归档' : '未归档'}
            </Tag>
          ),
        },
      ]}
    />
  )
}
