'use client'

// 职业健康管理 — 6 Tab 页面（Client 壳）
//
// 页级 PageHeader（ui-kit）+ Tabs；各 Tab 内区块用 SectionCard、统计行用 StatCard（见各 Panel）。
// 跨 Tab 联动：人员台账「体检记录」链接 → handleViewExams(personName)
//   → setActiveKey('exams') + setExamKeyword(personName)，
//   OhExamsPanel 接收新 keyword 自动填入搜索框并触发查询（平台内 Bitable link 语义等价跳转）。
// Tabs 切换不卸载已访问面板（antd 默认懒挂载、destroyOnHidden=false），保留各面板筛选状态。

import { useState } from 'react'
import { Tabs } from 'antd'
import { PageHeader } from '@/components/ui-kit'
import {
  OhApplicationsPanel,
  OhExamsPanel,
  OhFollowupsPanel,
  OhHazardFactorsPanel,
  OhPersonsPanel,
  OhPositionsPanel,
} from '@/components/safety'

export default function OccupationalHealthClient() {
  const [activeKey, setActiveKey] = useState('persons')
  const [examKeyword, setExamKeyword] = useState('')

  const handleViewExams = (personName: string) => {
    setExamKeyword(personName)
    setActiveKey('exams')
  }

  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '职业健康管理']}
        title="职业健康管理"
        description="职业健康人员档案、体检与危害因素监测态势"
      />
      <Tabs
        activeKey={activeKey}
        onChange={setActiveKey}
        items={[
          { key: 'persons', label: '人员台账', children: <OhPersonsPanel onViewExams={handleViewExams} /> },
          {
            key: 'exams',
            label: '体检记录',
            children: (
              <OhExamsPanel
                key={examKeyword || 'exams-default'}
                initialKeyword={examKeyword}
                onConsumedKeyword={() => setExamKeyword('')}
              />
            ),
          },
          { key: 'positions', label: '岗位危害', children: <OhPositionsPanel /> },
          { key: 'hazardFactors', label: '危害因素PPE', children: <OhHazardFactorsPanel /> },
          { key: 'applications', label: '转岗离岗申请', children: <OhApplicationsPanel /> },
          { key: 'followups', label: '异常随访', children: <OhFollowupsPanel /> },
        ]}
      />
    </div>
  )
}
