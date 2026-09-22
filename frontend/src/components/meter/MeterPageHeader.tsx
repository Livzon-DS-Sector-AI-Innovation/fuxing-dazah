'use client'

import type { ReactNode } from 'react'
import { Button } from 'antd'
import { ArrowRightOutlined, DashboardOutlined } from '@ant-design/icons'
import styles from './MeterModule.module.css'

interface Props {
  title: string
  description: string
  eyebrow?: string
  action?: { label: string; onClick: () => void; icon?: ReactNode }
}

export function MeterPageHeader({ title, description, eyebrow = 'METER OPERATIONS', action }: Props) {
  return (
    <div className={styles.pageHeader}>
      <div className={styles.pageHeaderTitle}>
        <div className={styles.pageHeaderIcon}><DashboardOutlined /></div>
        <div>
          <div className={styles.eyebrow} style={{ color: '#8d88a7', marginBottom: 5 }}>{eyebrow}</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>
      {action && <div className={styles.pageHeaderActions}><Button type="primary" icon={action.icon ?? <ArrowRightOutlined />} onClick={action.onClick}>{action.label}</Button></div>}
    </div>
  )
}
