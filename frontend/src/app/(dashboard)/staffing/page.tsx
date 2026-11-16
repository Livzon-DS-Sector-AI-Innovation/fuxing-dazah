'use client'

import Link from 'next/link'
import { Card, Row, Col } from 'antd'
import {
  AimOutlined, TeamOutlined, LoginOutlined, LogoutOutlined,
} from '@ant-design/icons'

import { PermissionGuard } from '@/components/permission/PermissionGuard'

const modules = [
  { key: 'headcount', title: '编制管理', desc: '部门定编与在编实时对比、缺编一览（随档案同步自动拉取）', icon: <AimOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/staffing/headcount', permission: 'hr:profile:read' },
  { key: 'profile', title: '员工档案', desc: '员工基本信息、岗位变动、入职离职记录（飞书多维表格同步）', icon: <TeamOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/staffing/profile', permission: 'hr:profile:read' },
  { key: 'onboarding', title: '入职台账', desc: '员工入职记录、入职任务跟踪、试用期转正管理', icon: <LoginOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/staffing/onboarding', permission: 'hr:onboarding:read' },
  { key: 'departure', title: '离职台账', desc: '员工离职记录、离职证明生成与签收', icon: <LogoutOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/staffing/departure', permission: 'hr:departure:read' },
]

export default function StaffingPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">人员全周期管理</h1>
        <p className="text-[14px] text-[var(--color-steel)]">编制 → 入职 → 在职档案 → 离职，人员全生命周期数据管理</p>
      </div>

      <Row gutter={[16, 16]}>
        {modules.map((mod) => {
          const card = (
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
          )
          return (
            <Col xs={24} sm={12} lg={8} key={mod.key}>
              <PermissionGuard permission={mod.permission}>{card}</PermissionGuard>
            </Col>
          )
        })}
      </Row>
    </div>
  )
}
