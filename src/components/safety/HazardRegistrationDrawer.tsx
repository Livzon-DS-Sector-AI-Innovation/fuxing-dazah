'use client'

import { Drawer } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import HazardInspectionFlow from './HazardInspectionFlow'

interface Props {
  open: boolean
  onClose: () => void
  onDone: () => void
}

export default function HazardRegistrationDrawer({ open, onClose, onDone }: Props) {
  return (
    <Drawer
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SearchOutlined style={{ color: '#5645d4' }} />
          <span style={{ fontSize: 16, fontWeight: 600 }}>隐患登记</span>
        </span>
      }
      open={open}
      onClose={onClose}
      placement="right"
      width={800}
      destroyOnClose
      styles={{ body: { padding: '16px 24px 24px' } }}
    >
      <HazardInspectionFlow variant="drawer" onDone={onDone} />
    </Drawer>
  )
}
