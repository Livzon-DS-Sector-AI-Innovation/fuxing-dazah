'use client'

/**
 * 设备设施管理页 client（facilities-p1 票 01 / p2 票 01）——四 Tab：
 * 安全附件 / 消防器材 / 特种设备（「台账 | 监控」子区，监控=锅炉遥测链 p2）+
 * 校验任务。页级 PageHeader；台账 Tab 见 FacilitiesLedgerTab。
 */
import { useState } from 'react'
import { Segmented, Tabs } from 'antd'
import { PageHeader } from '@/components/ui-kit'
import FacilitiesLedgerTab from './FacilitiesLedgerTab'
import FacilityTaskCenterPanel from './FacilityTaskCenterPanel'
import TelemetryMonitorPanel from '@/components/safety/telemetry/TelemetryMonitorPanel'

function SpecialEquipmentTab() {
  const [section, setSection] = useState<'ledger' | 'monitor'>('ledger')
  return (
    <div>
      <div className="mb-3">
        <Segmented
          value={section}
          onChange={(v) => setSection(v as 'ledger' | 'monitor')}
          options={[
            { value: 'ledger', label: '台账' },
            { value: 'monitor', label: '监控' },
          ]}
        />
      </div>
      {section === 'ledger' ? (
        <FacilitiesLedgerTab
          ledger="special-equipment"
          title="特种设备"
          description="锅炉 / 压力容器等定期检验台账（锅炉监控链二期接入）"
        />
      ) : (
        <TelemetryMonitorPanel />
      )}
    </div>
  )
}

export default function FacilitiesPageClient() {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '现场管理']}
        title="设备设施管理"
        description="安全附件 / 消防器材 / 特种设备三台账直读与校验任务闭环督办"
      />
      <Tabs
        defaultActiveKey="accessories"
        items={[
          {
            key: 'accessories',
            label: '安全附件',
            children: (
              <FacilitiesLedgerTab
                ledger="accessories"
                title="安全附件"
                description="安全阀 / 爆破片 / 承压附件 / 安全用压力表等"
              />
            ),
          },
          {
            key: 'fire-equipment',
            label: '消防器材',
            children: (
              <FacilitiesLedgerTab
                ledger="fire-equipment"
                title="消防器材"
                description="灭火器 / 消火栓等；换药与报废到期为辅助锚点"
              />
            ),
          },
          {
            key: 'special-equipment',
            label: '特种设备',
            children: <SpecialEquipmentTab />,
          },
          { key: 'tasks', label: '校验任务', children: <FacilityTaskCenterPanel /> },
        ]}
      />
    </div>
  )
}
