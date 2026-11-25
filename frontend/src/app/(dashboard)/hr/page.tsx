'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Card, Row, Col } from 'antd'
import {
  TeamOutlined, BookOutlined, BankOutlined, LoginOutlined, LogoutOutlined,
  FileSearchOutlined, PrinterOutlined, AuditOutlined, SafetyCertificateOutlined,
  SettingOutlined, TrophyOutlined, ApartmentOutlined,
  FileDoneOutlined, } from '@ant-design/icons'

import { usePermission } from '@/hooks/usePermission'
import PageHeader from '@/components/hr/PageHeader'

/**
 * 功能入口卡片：仅作部分权限角色的落地导航（如纯培训角色进不了看板）。
 * 按权限码过滤——此前只过滤了招聘，纯评委等角色落地后会看到一排点进去 403 的卡片，
 * 反而没有自己的「评审投票」入口。
 */
const modules = [
  { key: 'profile', title: '员工档案', desc: '管理员工基本信息、入职离职、岗位变动等', icon: <TeamOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/profile', permission: 'hr:profile:read' },
  { key: 'headcount', title: '编制管理', desc: '各部门定编与在编对账', icon: <ApartmentOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/headcount', permission: 'hr:profile:read' },
  { key: 'certificates', title: '证件资料库', desc: '员工电子证件归档、缺件催收、调阅留痕', icon: <SafetyCertificateOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/certificates', permission: 'hr:certificate:read' },
  { key: 'departments', title: '部门管理', desc: '组织架构、部门信息维护', icon: <BankOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/departments', permission: 'hr:org:read' },
  { key: 'recruitment', title: '招聘管理', desc: '候选人筛选、简历管理、推荐等级评定', icon: <FileSearchOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/recruitment', permission: 'hr:recruitment:read' },
  { key: 'onboarding', title: '入职台账', desc: '员工入职记录管理', icon: <LoginOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/onboarding', permission: 'hr:onboarding:read' },
  { key: 'departure', title: '离职台账', desc: '员工离职记录管理', icon: <LogoutOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/departure', permission: 'hr:departure:read' },
  { key: 'labor-contracts', title: '劳动合同', desc: '合同签订、到期预警、续签审批、领取签字与归档', icon: <FileDoneOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/labor-contracts', permission: 'hr:contract:read' },
  { key: 'training', title: '培训管理', desc: '培训计划、课程安排、培训记录等', icon: <BookOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/training', permission: 'hr:training:read' },
  { key: 'performance', title: '绩效考核', desc: '月度绩效考核与项目评分', icon: <TrophyOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/performance', permission: 'hr:performance:read' },
  { key: 'title-judge', title: '职称评审投票', desc: '评委对申报人匿名投票', icon: <AuditOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/title-judge', permission: 'hr:title:judge' },
  { key: 'printing', title: '资料下载', desc: '花名册、个人培训登记表等文档批量下载', icon: <PrinterOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/printing', permission: 'hr:roster:read' },
  { key: 'settings', title: '系统配置', desc: '人事提醒、邮件、数据管理与岗位管理', icon: <SettingOutlined className="text-2xl text-[var(--color-primary)]" />, path: '/hr/settings', permission: 'hr:settings:manage' },
]

export default function HrPage() {
  const router = useRouter()
  const { isLoaded, hasPermission } = usePermission()

  // 有看板权限的直接进看板，不再经过板块卡片页
  useEffect(() => {
    if (isLoaded && hasPermission('hr:profile:read')) {
      router.replace('/hr/dashboard')
    }
  }, [isLoaded, hasPermission, router])

  // 权限加载中/跳转中不渲染卡片，避免有权限用户闪一下板块页
  if (isLoaded && hasPermission('hr:profile:read')) return null

  const visible = modules.filter((mod) => !mod.permission || hasPermission(mod.permission))

  return (
    <div className="space-y-4">
      <PageHeader title="人事管理" description="人员、岗位、培训等人事业务数据管理" />

      <Row gutter={[16, 16]}>
        {visible.map((mod) => (
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
