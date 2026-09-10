'use client'

// 职业健康管理 — 6 Tab 页面（Client 壳）
//
// 跨 Tab 联动：人员台账「体检记录」链接 → handleViewExams(personName)
//   → setActiveKey('exams') + setExamKeyword(personName)，
//   OhExamsPanel 接收新 keyword 自动填入搜索框并触发查询（平台内 Bitable link 语义等价跳转）。
// Tabs 切换不卸载已访问面板（antd 默认懒挂载、destroyOnHidden=false），保留各面板筛选状态。

import { useState } from 'react'
import { Tabs, Typography } from 'antd'
import {
  OhApplicationsPanel,
  OhExamsPanel,
  OhFollowupsPanel,
  OhHazardFactorsPanel,
  OhPersonsPanel,
  OhPositionsPanel,
} from '@/components/safety'

const { Title, Text } = Typography

export default function OccupationalHealthClient() {
  const [activeKey, setActiveKey] = useState('persons')
  const [examKeyword, setExamKeyword] = useState('')

  const handleViewExams = (personName: string) => {
    setExamKeyword(personName)
    setActiveKey('exams')
  }

  return (
    <div>
      <Title level={4} style={{ marginBottom: 4 }}>职业健康管理</Title>
      <Text type="secondary">人员台账 · 体检记录 · 岗位危害 · 危害因素PPE · 转岗离岗 · 异常随访（GBZ 188）</Text>
      <Tabs
        activeKey={activeKey}
        onChange={setActiveKey}
        style={{ marginTop: 8 }}
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
