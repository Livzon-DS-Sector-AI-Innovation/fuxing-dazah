import type { ReactNode } from 'react'
import styles from './EnergyPageFrame.module.css'

type EnergyPageFrameProps = {
  children: ReactNode
  className?: string
}

/** 能源模块统一页面画布，保证标题、筛选区和数据表在不同入口保持一致的留白节奏。 */
export function EnergyPageFrame({ children, className = '' }: EnergyPageFrameProps) {
  return <main className={`${styles.frame} ${className}`}>{children}</main>
}
