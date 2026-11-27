import type { ReactNode } from 'react'
import styles from './PageHeading.module.css'

type PageHeadingProps = {
  title: ReactNode
  subtitle?: ReactNode
  className?: string
  /** 标题右侧的操作区，如「使用手册」入口。不传时布局与旧版一致。 */
  actions?: ReactNode
}

/** 页面级标题：用细微光晕、字阶和基线分隔建立清晰的信息层次。 */
export function PageHeading({ title, subtitle, className = '', actions }: PageHeadingProps) {
  return (
    <header className={`${styles.heading} ${className}`}>
      <div className={styles.eyebrow} aria-hidden="true" />
      <div className={styles.row}>
        <div className={styles.text}>
          <h1 className={styles.title}>{title}</h1>
          {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
        {actions && <div className={styles.actions}>{actions}</div>}
      </div>
    </header>
  )
}
