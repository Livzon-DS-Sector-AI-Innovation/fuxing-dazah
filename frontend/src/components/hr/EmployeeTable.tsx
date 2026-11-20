'use client'

// 员工档案表格编排壳：组装列定义（employee/columns）与行内弹窗（详情/异动/转正评估）。
// 40+ 列配置与弹窗逻辑已拆至 employee/ 子目录，本组件只负责装配。

import { useState } from 'react'
import { Table } from 'antd'
import { Employee } from '@/types/hr'
import { usePermission } from '@/hooks/usePermission'
import styles from './lifecycleTable.module.css'
import EmployeeInfoModal from './EmployeeInfoModal'
import { buildEmployeeColumns, filterVisibleColumns } from './employee/columns'
import TransferRecordModal from './employee/TransferRecordModal'
import ProbationReviewModal from './employee/ProbationReviewModal'

interface EmployeeTableProps {
  employees: Employee[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onEdit: (employee: Employee) => void
  loading?: boolean
  /** 多维表格同步模式：档案在飞书维护，隐藏会改写档案的编辑/异动入口 */
  syncMode?: boolean
}

export default function EmployeeTable({
  employees,
  total,
  page,
  pageSize,
  onPageChange,
  onEdit,
  loading = false,
  syncMode = false }: EmployeeTableProps) {
  const { hasPermission } = usePermission()
  // 员工档案基础信息不开放给培训管理员等无档案编辑权限的角色
  const canEditProfile = hasPermission('hr:profile:update')
  const canTransfer = hasPermission('hr:profile:transfer')

  const [detailOpen, setDetailOpen] = useState(false)
  const [detailEmp, setDetailEmp] = useState<Employee | null>(null)
  const [probationOpen, setProbationOpen] = useState(false)
  const [probationEmp, setProbationEmp] = useState<Employee | null>(null)
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferEmp, setTransferEmp] = useState<Employee | null>(null)

  const columns = filterVisibleColumns(
    buildEmployeeColumns({
      onDetail: (emp) => { setDetailEmp(emp); setDetailOpen(true) },
      onProbation: (emp) => { setProbationEmp(emp); setProbationOpen(true) },
      onEdit,
      onTransfer: (emp) => { setTransferEmp(emp); setTransferOpen(true) },
      canEditProfile,
      canTransfer,
      syncMode,
    }),
    employees,
  )

  return (
    <div className="space-y-4">
      {/* 搜索/状态/筛选工具栏已上提至页面 Tab 栏（EmployeeProfileClient），此处仅渲染表格与弹窗 */}
      <div className="rounded-xl border border-[var(--color-hairline)] bg-white overflow-hidden">
        <Table className={styles.tableLg}
          columns={columns}
          dataSource={employees}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: onPageChange }}
          scroll={{ x: 4800 }}
        />
      </div>

      <EmployeeInfoModal employee={detailEmp} open={detailOpen} onClose={() => setDetailOpen(false)} />
      <TransferRecordModal open={transferOpen} employee={transferEmp} onClose={() => setTransferOpen(false)} />
      <ProbationReviewModal open={probationOpen} employee={probationEmp} onClose={() => setProbationOpen(false)} />
    </div>
  )
}
