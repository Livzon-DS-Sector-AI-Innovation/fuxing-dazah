'use client'

import { Descriptions, Drawer, Empty, Space, Tag } from 'antd'
import type { MsdsExtractionEntry } from '@/types/safety'
import { MSDS_DETAIL_GROUPS, UI, CARD_STYLE } from './msdsConstants'

function StatusPill({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color, background: bg, fontWeight: 600 }}>
      {label}
    </span>
  )
}

interface MsdsDetailDrawerProps {
  open: boolean
  onClose: () => void
  title?: string
  entry?: MsdsExtractionEntry | null
  groups?: typeof MSDS_DETAIL_GROUPS
  footer?: React.ReactNode
}

export default function MsdsDetailDrawer({
  open,
  onClose,
  title,
  entry,
  groups = MSDS_DETAIL_GROUPS,
  footer,
}: MsdsDetailDrawerProps) {
  if (!entry) {
    return <Drawer open={open} onClose={onClose} title={title ?? 'MSDS 详情'} width={720}>
      <Empty description="暂无数据" />
    </Drawer>
  }

  return (
    <Drawer open={open} onClose={onClose} title={title ?? 'MSDS 详情'} width={720} extra={footer}>
      {groups.map((group) => {
        const present = group.fields.filter((f) => entry[f.key as keyof MsdsExtractionEntry])
        if (present.length === 0) return null
        return (
          <div key={group.label} style={{ ...CARD_STYLE, padding: '12px 16px', marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 8 }}>
              {group.label}
            </div>
            <Descriptions column={1} size="small" bordered>
              {present.map((f) => (
                <Descriptions.Item key={f.key} label={f.label} labelStyle={{ width: 160, background: UI.surface, fontWeight: 600, fontSize: 12 }}>
                  <span style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{String(entry[f.key as keyof MsdsExtractionEntry])}</span>
                </Descriptions.Item>
              ))}
            </Descriptions>
          </div>
        )
      })}
    </Drawer>
  )
}
