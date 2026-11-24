'use client'

import { useState } from 'react'
import { Tabs } from 'antd'
import PageHeader from '@/components/hr/PageHeader'
import SystemSettingsClient, { SmtpSettingsCard } from '@/components/hr/SystemSettingsClient'
import UserDeptAccessClient from '@/components/hr/UserDeptAccessClient'
import { ReminderSettingsCard } from '@/components/hr'

// 系统配置按用途分四个页签：此前是「提醒 → 邮件 → 数据管理 → 部门权限」一条长页，
// 「一键清空全部」这类危险操作和邮件保存按钮同屏。
export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState('reminder')

  return (
    <div className="space-y-4">
      <PageHeader title="系统配置" description="人事提醒、邮件通知、数据管理与部门数据权限" />
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'reminder', label: '提醒配置', children: <ReminderSettingsCard /> },
          { key: 'mail', label: '邮件配置', children: <SmtpSettingsCard /> },
          { key: 'data', label: '数据管理', children: <SystemSettingsClient /> },
          { key: 'dept-access', label: '部门权限', children: <UserDeptAccessClient /> },
        ]}
      />
    </div>
  )
}
