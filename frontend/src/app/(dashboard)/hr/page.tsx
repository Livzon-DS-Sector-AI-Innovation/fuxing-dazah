'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Modal, Timeline, Tag } from 'antd'
import {
  TeamOutlined, BookOutlined, BankOutlined, LoginOutlined, LogoutOutlined,
  UserDeleteOutlined, FileSearchOutlined, PrinterOutlined,
  AuditOutlined, ClockCircleOutlined, SwapOutlined, FileProtectOutlined,
} from '@ant-design/icons'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

const modules = [
  { key: 'profile', title: '员工档案', desc: '管理员工基本信息、入职离职、岗位变动等', icon: <TeamOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/profile' },
  { key: 'departments', title: '部门管理', desc: '组织架构、部门信息维护', icon: <BankOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/departments' },
  { key: 'recruitment', title: '招聘管理', desc: '候选人筛选、简历管理、推荐等级评定', icon: <FileSearchOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/recruitment' },
  { key: 'onboarding', title: '入职台账', desc: '员工入职记录管理', icon: <LoginOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/onboarding' },
  { key: 'departure', title: '离职台账', desc: '员工离职记录管理', icon: <LogoutOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/departure' },
  { key: 'offboarding', title: '离职管理', desc: '员工离职流程、离职记录管理', icon: <UserDeleteOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/offboarding' },
  { key: 'training', title: '培训管理', desc: '培训计划、课程安排、培训记录等', icon: <BookOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/training' },
  { key: 'printing', title: '资料打印', desc: '花名册、个人培训登记表等文档批量下载', icon: <PrinterOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/printing' },
]

const statCards = [
  { key: 'pending_onboard', title: '待审批入职', path: '/hr/onboarding-apply', icon: <AuditOutlined />, color: '#faad14', field: 'pending_onboarding' },
  { key: 'pending_offboard', title: '待审批离职', path: '/hr/onboarding-apply', icon: <LogoutOutlined />, color: '#cf1322', field: 'pending_offboarding' },
  { key: 'probation', title: '试用期到期(30天)', path: '/hr/probation', icon: <ClockCircleOutlined />, color: '#ff7a45', field: 'probation_expiring' },
  { key: 'transfer', title: '近期异动(30天)', path: '', icon: <SwapOutlined />, color: '#1677ff', field: 'recent_transfers' },
  { key: 'contract', title: '合同到期(60天)', path: '', icon: <FileProtectOutlined />, color: '#fa8c16', field: 'contracts_expiring' },
]

export default function HrPage() {
  const [stats, setStats] = useState<Record<string, any>>({})
  const [transferModal, setTransferModal] = useState(false)
  const [contractModal, setContractModal] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/dashboard-stats`, { credentials: 'include' })
      .then(r => r.json()).then(d => setStats(d.data || {})).catch(() => {})
  }, [])

  const transfers = stats.recent_transfer_list || []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">人事管理</h1>
        <p className="text-[14px] text-[var(--color-steel)]">人员、岗位、培训等人事业务数据管理</p>
      </div>

      {/* 提醒卡片 */}
      <Row gutter={[12, 12]}>
        {statCards.map(s => {
          const card = (
            <Card hoverable size="small" className="text-center">
              <Statistic
                value={stats[s.field] ?? '...'}
                styles={{ value: { color: s.color, fontSize: 28 } }}
                prefix={s.icon}
                suffix={<span className="text-sm text-gray-400">{s.title}</span>}
              />
            </Card>
          )
          return (
            <Col xs={12} sm={6} key={s.key}>
              {s.key === 'transfer' ? (
                <div onClick={() => setTransferModal(true)} className="cursor-pointer">{card}</div>
              ) : s.key === 'contract' ? (
                <div onClick={() => setContractModal(true)} className="cursor-pointer">{card}</div>
              ) : (
                <Link href={s.path}>{card}</Link>
              )}
            </Col>
          )
        })}
      </Row>

      {/* 异动明细弹窗 */}
      <Modal title={`近期异动 (${stats.recent_transfers || 0})`} open={transferModal}
        onCancel={() => setTransferModal(false)} footer={null} width={600}>
        {transfers.length > 0 ? (
          <Timeline items={transfers.map((t: any) => ({
            color: t.transfer_type === '晋升' ? 'green' : t.transfer_type === '降职' ? 'red' : 'blue',
            children: (
              <div>
                <span className="font-medium">{t.name}</span>
                <Tag color={t.transfer_type === '晋升' ? 'green' : t.transfer_type === '降职' ? 'red' : 'blue'} className="ml-2">{t.transfer_type}</Tag>
                <div className="text-gray-500 text-sm mt-1">{t.from_department || '—'} → {t.to_department || '—'} · {t.effective_date}</div>
              </div>
            ),
          }))} />
        ) : <p className="text-gray-400 text-center py-8">近期无异动</p>}
      </Modal>

      {/* 合同到期弹窗 */}
      <Modal title={`合同即将到期 (${stats.contracts_expiring || 0})`} open={contractModal}
        onCancel={() => setContractModal(false)} footer={null} width={700}>
        {(stats.contract_list || []).length > 0 ? (
          <table className="w-full text-sm">
            <thead><tr className="bg-gray-50">
              <th className="p-2 text-left">姓名</th><th className="p-2 text-left">工号</th>
              <th className="p-2 text-left">部门</th><th className="p-2 text-left">岗位</th>
              <th className="p-2 text-left">合同到期日</th><th className="p-2 text-left">剩余天数</th>
            </tr></thead>
            <tbody>
              {(stats.contract_list || []).map((c: any, i: number) => {
                const days = c.contract_end_date ? Math.ceil((new Date(c.contract_end_date).getTime() - Date.now()) / 86400000) : 0
                return (
                  <tr key={i} className="border-t">
                    <td className="p-2">{c.name}</td><td className="p-2">{c.employee_number}</td>
                    <td className="p-2">{c.department}</td><td className="p-2">{c.position}</td>
                    <td className="p-2">{c.contract_end_date}</td>
                    <td className="p-2"><Tag color={days <= 30 ? 'red' : 'orange'}>{days}天</Tag></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : <p className="text-gray-400 text-center py-8">暂无即将到期合同</p>}
      </Modal>

      {/* 功能入口 */}
      <Row gutter={[16, 16]}>
        {modules.map((mod) => (
          <Col xs={24} sm={12} lg={8} key={mod.key}>
            <Link href={mod.path}>
              <Card hoverable className="h-full cursor-pointer transition-shadow hover:shadow-md">
                <div className="flex items-start gap-4">
                  <div className="mt-1">{mod.icon}</div>
                  <div>
                    <h3 className="text-[16px] font-semibold text-[var(--color-charcoal)] mb-1">{mod.title}</h3>
                    <p className="text-[14px] text-[var(--color-steel)] leading-relaxed">{mod.desc}</p>
                  </div>
                </div>
              </Card>
            </Link>
          </Col>
        ))}
      </Row>
    </div>
  )
}
