'use client'

// 员工档案表格编排壳：组装列定义（employee/columns）与行内弹窗（详情/异动/转正评估）。
// 40+ 列配置与弹窗逻辑已拆至 employee/ 子目录，本组件只负责装配。

import { useMemo, useState } from 'react'
import { Table } from 'antd'
import { Employee } from '@/types/hr'
import { usePermission } from '@/hooks/usePermission'
import styles from './lifecycleTable.module.css'
import EmployeeInfoModal from './EmployeeInfoModal'
import { applyColumnVisibility, buildEmployeeColumns } from './employee/columns'
import TransferRecordModal from './employee/TransferRecordModal'
import ProbationReviewModal from './employee/ProbationReviewModal'

// 未传列设置时的空集（模块级常量，引用稳定，不触发 useMemo 重算）
const EMPTY_HIDDEN: ReadonlySet<string> = new Set()
// 弹性列（未设 width 的列，如部门/职务）的最小宽度
const FLEX_COL_MIN = 96

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
  /** 用户在「列设置」里隐藏的列（key 集合）；默认常用列，见 employee/ColumnSettings */
  hiddenColumns?: ReadonlySet<string>
}

export default function EmployeeTable({
  employees,
  total,
  page,
  pageSize,
  onPageChange,
  onEdit,
  loading = false,
  syncMode = false,
  hiddenColumns }: EmployeeTableProps) {
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

  const allColumns = useMemo(() => buildEmployeeColumns({
    onDetail: (emp) => { setDetailEmp(emp); setDetailOpen(true) },
    onProbation: (emp) => { setProbationEmp(emp); setProbationOpen(true) },
    onEdit,
    onTransfer: (emp) => { setTransferEmp(emp); setTransferOpen(true) },
    canEditProfile,
    canTransfer,
    syncMode,
  }), [onEdit, canEditProfile, canTransfer, syncMode])
  const columns = useMemo(
    () => applyColumnVisibility(allColumns, hiddenColumns ?? EMPTY_HIDDEN),
    [allColumns, hiddenColumns],
  )
  // 横向宽度 = 固定列宽之和 + 弹性列（未设 width，如部门/职务）按最小宽度计：
  // 容器更宽时弹性列自动拉伸填满（常用列视图不出横向滚动条），列多放不下时才横向滚动
  const scrollX = useMemo(
    () => columns.reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : FLEX_COL_MIN), 0),
    [columns],
  )

  return (
    <div className="space-y-4">
      {/* 搜索/状态/筛选/列设置在页面工具栏（EmployeeProfileClient），此处仅渲染表格与弹窗 */}
      <div className="rounded-xl border border-[var(--color-hairline)] bg-white overflow-hidden">
        <Table className={styles.tableLg}
          columns={columns}
          dataSource={employees}
          rowKey="id"
          loading={loading}
          tableLayout="fixed"
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: onPageChange }}
          scroll={{ x: scrollX }}
        />
      </div>

      <EmployeeInfoModal employee={detailEmp} open={detailOpen} onClose={() => setDetailOpen(false)} />
      <TransferRecordModal open={transferOpen} employee={transferEmp} onClose={() => setTransferOpen(false)} />
      <ProbationReviewModal open={probationOpen} employee={probationEmp} onClose={() => setProbationOpen(false)} />
    </div>
  )
}
