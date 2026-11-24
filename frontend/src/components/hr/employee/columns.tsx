'use client'

// 员工档案表格列定义（40+ 列与飞书「员工信息表」源表保持一致）。
// 从 EmployeeTable 拆出：列配置纯数据化，操作列回调和权限由外部注入。

import { Button, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { AuditOutlined, EditOutlined, EyeOutlined, SwapOutlined } from '@ant-design/icons'
import Link from 'next/link'
import { Employee } from '@/types/hr'
import { EMPLOYEE_STATUS_TAG_COLORS } from '@/lib/hr'

const statusColorMap = EMPLOYEE_STATUS_TAG_COLORS

/** 操作列与行内入口依赖的回调/权限，由 EmployeeTable 注入 */
export interface EmployeeColumnHandlers {
  onDetail: (employee: Employee) => void
  /** 发起转正评估（仅试用期员工显示） */
  onProbation: (employee: Employee) => void
  onEdit: (employee: Employee) => void
  onTransfer: (employee: Employee) => void
  canEditProfile: boolean
  canTransfer: boolean
  /** 多维表格同步模式：隐藏会改写档案的编辑/异动入口 */
  syncMode: boolean
}

// 「状态」为系统按离职日期/员工性质派生，源表本身无此列。源表没有的字段见详情弹窗「系统附加」。
export function buildEmployeeColumns(h: EmployeeColumnHandlers): ColumnsType<Employee> {
  const { onDetail, onProbation, onEdit, onTransfer, canEditProfile, canTransfer, syncMode } = h

  // 列宽原则：常用列视图（默认）要在 1366 宽的屏幕上不出横向滚动条——
  // 固定列按内容所需收紧，「部门」「职务」两列不设宽度、随容器伸缩（见 EmployeeTable 的 scroll.x 计算）。
  return [
    {
      title: '工号',
      dataIndex: 'employee_number',
      key: 'employee_number',
      width: 104,
      ellipsis: true,
      fixed: 'left' as const },
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 76,
      fixed: 'left' as const,
      // 姓名直达完整档案（证件 / 安全考试 / 转正历史）；此前入口只有操作列里的一个图标
      render: (name: string, record: Employee) => (
        <Tooltip title="查看完整档案（证件 / 安全考试 / 转正历史）">
          <Link href={`/hr/profile/${record.id}`} className="text-[var(--color-anchor)] hover:underline">
            {name}
          </Link>
        </Tooltip>
      ) },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      // 弹性列：不设宽度，吃掉剩余空间
      ellipsis: true },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 100,
      ellipsis: true },
    {
      title: '职务',
      dataIndex: 'duty',
      key: 'duty',
      // 弹性列：不设宽度，吃掉剩余空间
      ellipsis: true },
    {
      title: '职能分类',
      dataIndex: 'job_category',
      key: 'job_category',
      width: 100 },
    {
      title: '职级',
      dataIndex: 'level',
      key: 'level',
      // 72：容纳「实习生」这类 Tag，避免折成两行
      width: 72,
      ellipsis: true },
    {
      title: '岗位职级',
      dataIndex: 'report_grade',
      key: 'report_grade',
      width: 110 },
    {
      title: '员工性质',
      dataIndex: 'status_category',
      key: 'status_category',
      width: 92,
      ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 118,
      render: (status: string, record: Employee) => {
        if (status === '试用期' && record.computed_probation_days_left != null) {
          const d = record.computed_probation_days_left
          return (
            <Tag color={d < 0 ? 'error' : statusColorMap[status]}>
              {d < 0 ? `试用期·超${Math.abs(d)}天` : `试用期·剩${d}天`}
            </Tag>
          )
        }
        return <Tag color={statusColorMap[status] || 'default'}>{status}</Tag>
      } },
    {
      title: '域账号',
      dataIndex: 'domain_account',
      key: 'domain_account',
      width: 110 },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 70 },
    {
      title: '年龄',
      dataIndex: 'computed_age',
      key: 'age',
      width: 70,
      render: (_: unknown, record: Employee) => record.computed_age ?? '-',
    },
    {
      title: '出生日期',
      dataIndex: 'birth_year',
      key: 'birth_date',
      width: 110,
      render: (_: unknown, r: Employee) => r.birth_year
        ? `${r.birth_year}-${String(r.birth_month ?? 1).padStart(2, '0')}-${String(r.birth_day ?? 1).padStart(2, '0')}`
        : '-' },
    {
      title: '民族',
      dataIndex: 'ethnicity',
      key: 'ethnicity',
      width: 80 },
    {
      title: '籍贯',
      dataIndex: 'native_place',
      key: 'native_place',
      width: 100 },
    {
      title: '婚姻状况',
      dataIndex: 'marital_status',
      key: 'marital_status',
      width: 90 },
    {
      title: '户口类型',
      dataIndex: 'household_type',
      key: 'household_type',
      width: 90 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 64 },
    {
      title: '学位类型',
      dataIndex: 'degree_type',
      key: 'degree_type',
      width: 100 },
    {
      title: '学习形式',
      dataIndex: 'classification',
      key: 'classification',
      width: 90 },
    {
      title: '毕业院校',
      dataIndex: 'school',
      key: 'school',
      width: 150 },
    {
      title: '专业',
      dataIndex: 'major',
      key: 'major',
      width: 120 },
    {
      title: '毕业时间',
      dataIndex: 'graduation_date',
      key: 'graduation_date',
      width: 110 },
    {
      title: '人力资源分析',
      dataIndex: 'hr_analysis',
      key: 'hr_analysis',
      width: 110 },
    {
      title: '联系电话',
      dataIndex: 'phone',
      key: 'phone',
      width: 120,
      ellipsis: true },
    {
      title: '居住地址',
      dataIndex: 'current_address',
      key: 'current_address',
      width: 180, ellipsis: true },
    {
      title: '身份证号',
      dataIndex: 'id_card',
      key: 'id_card',
      width: 170 },
    {
      title: '身份证有效期',
      dataIndex: 'id_card_expiry',
      key: 'id_card_expiry',
      width: 120 },
    {
      title: '紧急联系人-姓名',
      dataIndex: 'emergency_contact_name',
      key: 'emergency_contact_name',
      width: 130 },
    {
      title: '紧急联系人-联系电话',
      dataIndex: 'emergency_contact_phone',
      key: 'emergency_contact_phone',
      width: 150 },
    {
      title: '紧急联系人-关系',
      dataIndex: 'emergency_contact_relation',
      key: 'emergency_contact_relation',
      width: 130 },
    {
      title: '参加工作时间',
      dataIndex: 'work_start_date',
      key: 'work_start_date',
      width: 120 },
    {
      title: '入职日期',
      dataIndex: 'hire_date',
      key: 'hire_date',
      width: 104,
      ellipsis: true },
    {
      title: '离职日期',
      dataIndex: 'departure_date',
      key: 'departure_date',
      width: 110 },
    {
      title: '离职原因',
      dataIndex: 'departure_reason',
      key: 'departure_reason',
      width: 110 },
    {
      title: '司龄',
      dataIndex: 'computed_tenure',
      key: 'company_tenure',
      width: 100,
      render: (_: unknown, record: Employee) => record.computed_tenure ?? record.company_tenure ?? '-',
    },
    {
      title: '合同开始日期',
      dataIndex: 'contract_start_date',
      key: 'contract_start_date',
      width: 120 },
    {
      title: '合同结束日期',
      dataIndex: 'contract_end_date',
      key: 'contract_end_date',
      width: 120 },
    {
      title: '证书',
      dataIndex: 'certificates',
      key: 'certificates',
      width: 150, ellipsis: true,
      render: (v: string) => v || '-' },
    {
      title: '任命与岗位调动',
      dataIndex: 'transfer_history',
      key: 'transfer_history',
      width: 200, ellipsis: true,
      render: (v: string) => v || '-' },
    {
      title: '操作',
      key: 'action',
      // 完整档案入口已挪到姓名链接，操作列只剩图标；同步模式仅剩「详情」，宽度随可见按钮数自适应
      width: syncMode ? 60 : 118,
      fixed: 'right' as const,
      render: (_, record: Employee) => (
        <Space size={2}>
          <Tooltip title="详情">
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              aria-label="查看详情"
              onClick={() => onDetail(record)}
            />
          </Tooltip>
          {canEditProfile && record.status === '试用期' && (
            <Tooltip title="发起转正评估">
              <Button
                type="text" size="small" icon={<AuditOutlined />}
                aria-label="发起转正评估"
                onClick={() => onProbation(record)}
              />
            </Tooltip>
          )}
          {canEditProfile && !syncMode && (
            <Tooltip title="编辑">
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                aria-label="编辑"
                onClick={() => onEdit(record)}
              />
            </Tooltip>
          )}
          {canTransfer && !syncMode && (
            <Tooltip title="异动记录">
              <Button type="text" size="small" icon={<SwapOutlined />} aria-label="异动记录"
                onClick={() => onTransfer(record)} />
            </Tooltip>
          )}
        </Space>
      ) },
  ]
}

/**
 * 按用户的列设置过滤列。此前是「当前页数据里该列全空就隐藏」——翻页时列会跳动，
 * 而且默认摊开 42 列（横向 4800px）。现在默认是「常用列」，想看全部在列设置里点「全部列」。
 * 操作列恒显示。
 */
export function applyColumnVisibility(columns: ColumnsType<Employee>, hiddenKeys: ReadonlySet<string>): ColumnsType<Employee> {
  if (!hiddenKeys.size) return columns
  return columns.filter((col) => {
    const key = col.key as string
    return key === 'action' || !hiddenKeys.has(key)
  })
}
