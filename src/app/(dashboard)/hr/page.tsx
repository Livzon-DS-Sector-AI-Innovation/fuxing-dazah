'use client'

import Link from 'next/link'
import { Card, Row, Col } from 'antd'
import {
  TeamOutlined,
  BookOutlined,
  BankOutlined,
  SolutionOutlined,
  LoginOutlined,
  LogoutOutlined,
  UserDeleteOutlined,
  FileSearchOutlined,
} from '@ant-design/icons'

const modules = [
  {
    key: 'profile',
    title: '员工档案',
    desc: '管理员工基本信息、入职离职、岗位变动等',
    icon: <TeamOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/profile',
  },
  {
    key: 'roster',
    title: '员工花名册',
    desc: '查看全体员工花名册信息',
    icon: <SolutionOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/roster',
  },
  {
    key: 'departments',
    title: '部门管理',
    desc: '组织架构、部门信息维护',
    icon: <BankOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/departments',
  },
  {
    key: 'recruitment',
    title: '招聘管理',
    desc: '候选人筛选、简历管理、推荐等级评定',
    icon: <FileSearchOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/recruitment',
  },
  {
    key: 'onboarding',
    title: '老厂入职台账',
    desc: '老厂员工入职记录管理与飞书同步',
    icon: <LoginOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/onboarding',
  },
  {
    key: 'departure',
    title: '老厂离职台账',
    desc: '老厂员工离职记录管理与飞书同步',
    icon: <LogoutOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/departure',
  },
  {
    key: 'offboarding',
    title: '离职管理',
    desc: '员工离职流程、离职记录管理',
    icon: <UserDeleteOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/offboarding',
  },
  {
    key: 'training',
    title: '培训管理',
    desc: '培训计划、课程安排、培训记录等',
    icon: <BookOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training',
  },
]

export default function HrPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          人事管理
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          人员、岗位、培训等人事业务数据管理
        </p>
      </div>

      <Row gutter={[16, 16]}>
        {modules.map((mod) => (
          <Col xs={24} sm={12} lg={8} key={mod.key}>
            <Link href={mod.path}>
              <Card
                hoverable
                className="h-full cursor-pointer transition-shadow hover:shadow-md"
              >
                <div className="flex items-start gap-4">
                  <div className="mt-1">{mod.icon}</div>
                  <div>
                    <h3 className="text-[16px] font-semibold text-[var(--color-charcoal)] mb-1">
                      {mod.title}
                    </h3>
                    <p className="text-[14px] text-[var(--color-steel)] leading-relaxed">
                      {mod.desc}
                    </p>
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
