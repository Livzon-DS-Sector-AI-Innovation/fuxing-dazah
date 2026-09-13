import type { ReactNode } from 'react'
import styles from './PageHeading.module.css'

type PageHeadingProps = { title: ReactNode; subtitle?: ReactNode; className?: string }

/** 页面级标题：用细微光晕、字阶和基线分隔建立清晰的信息层次。 */
export function PageHeading({ title, subtitle, className = '' }: PageHeadingProps) {
  return (
    <header className={`${styles.heading} ${className}`}>
      <div className={styles.eyebrow} aria-hidden="true" />
      <h1 className={styles.title}>{title}</h1>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
    </header>
  )
}
