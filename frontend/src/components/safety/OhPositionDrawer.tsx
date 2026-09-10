'use client'

// 岗位危害详情 Drawer（OhPositionDrawer）
// Descriptions + 危害因素 Tag 全量 + 「对应 PPE 建议」子表（联 oh_hazard_factors 字典：
// 危害因素 → 呼吸防护用品；无映射显示 muted「未维护」）。只读，无编辑。

import { Descriptions, Drawer, Empty, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { OhHazardFactor, OhPosition } from '@/types/safety'
import {
  CARD_STYLE,
  OH_POSITION_FILL_STATUS_UI,
  T,
  UI,
} from './ohConstants'

function Pill({ status }: { status?: string }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = OH_POSITION_FILL_STATUS_UI[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

interface OhPositionDrawerProps {
  open: boolean
  onClose: () => void
  position: OhPosition | null
  hazardFactors: OhHazardFactor[]
}

export default function OhPositionDrawer({
  open,
  onClose,
  position,
  hazardFactors,
}: OhPositionDrawerProps) {
  const factors = position?.hazard_factors ?? []

  const ppeRows: { factor: string; ppe: string }[] = factors
    .map((f) => {
      const matched = hazardFactors.find((h) => h.factor_name === f)
      return { factor: f, ppe: matched?.ppe_respiratory ?? '' }
    })

  const ppeColumns: ColumnsType<{ factor: string; ppe: string }> = [
    { title: '危害因素', dataIndex: 'factor', key: 'factor', width: 220, render: (v: string) => <Tag color="purple" style={{ marginInlineEnd: 0 }}>{v}</Tag> },
    {
      title: '呼吸防护用品', dataIndex: 'ppe', key: 'ppe',
      render: (v: string) => v
        ? <span style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{v}</span>
        : <span style={{ color: UI.muted, fontSize: 13 }}>未维护</span>,
    },
  ]

  return (
    <Drawer
      title={position ? `${position.position} — 岗位危害详情` : '岗位危害详情'}
      open={open}
      onClose={onClose}
      width={720}
    >
      {!position ? (
        <Empty description="暂无数据" />
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>岗位信息</div>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="部门">{position.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="岗位"><b>{position.position}</b></Descriptions.Item>
              <Descriptions.Item label="职务">{position.job_title || '-'}</Descriptions.Item>
              <Descriptions.Item label="填充状态"><Pill status={position.hazard_factors_status} /></Descriptions.Item>
            </Descriptions>
          </div>

          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>危害因素（全量）</div>
            {factors.length === 0 ? (
              <span style={{ color: UI.muted, fontSize: 13 }}>未登记危害因素</span>
            ) : (
              <Space size={[6, 6]} wrap>
                {factors.map((f) => (
                  <Tag key={f} style={{ marginInlineEnd: 0, background: T.lavender, color: '#391c57', borderColor: 'transparent', borderRadius: 6 }}>{f}</Tag>
                ))}
              </Space>
            )}
          </div>

          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>
              对应 PPE 建议
              <span style={{ color: UI.muted, fontWeight: 400, marginLeft: 8, fontSize: 12 }}>取自危害因素 PPE 映射字典</span>
            </div>
            {ppeRows.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无危害因素，无 PPE 映射" />
            ) : (
              <Table<{ factor: string; ppe: string }>
                rowKey="factor"
                size="small"
                columns={ppeColumns}
                dataSource={ppeRows}
                pagination={false}
              />
            )}
          </div>
        </Space>
      )}
    </Drawer>
  )
}
