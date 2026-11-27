'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import { Button, Modal } from 'antd'
import { ReadOutlined } from '@ant-design/icons'
import styles from './PageGuideButton.module.css'

export interface PageGuideStep {
  /** 一句话说清「点哪里、看到什么」 */
  text: string
  /** 可选：判据或易错点 */
  tip?: string
}

export interface PageGuide {
  /** 弹窗标题 */
  title: string
  /** 业务说明：这个页面是做什么的 */
  summary: string
  /** 面向哪种用户、解决什么需求 */
  audience: string
  /** 详细操作说明 */
  steps: PageGuideStep[]
  /** 注意事项 */
  notes?: string[]
}

/**
 * 页面使用手册入口：按当前路由在传入的手册表中精确查表，未登记的页面自动不渲染。
 *
 * 各模块用同名薄包装绑定自己的手册表，例如 components/<模块>/shared/PageGuideButton.tsx。
 */
export function PageGuideButton({ guides }: { guides: Record<string, PageGuide> }) {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)

  // 精确匹配，不要改成 startsWith —— /production 不能命中 /production/batches
  const guide = guides[pathname.replace(/\/$/, '')]
  if (!guide) return null

  const close = () => setOpen(false)

  return (
    <>
      <Button
        type="text"
        htmlType="button"
        className={styles.guideButton}
        icon={
          <span className={styles.iconBadge} aria-hidden="true">
            <ReadOutlined />
          </span>
        }
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span className={styles.guideLabel}>使用手册</span>
      </Button>
      <Modal
        open={open}
        onCancel={close}
        title={guide.title}
        centered
        destroyOnHidden
        width={{ xs: '92vw', sm: 560, lg: 720 }}
        mask={{ closable: false }}
        styles={{
          title: { fontSize: 18, fontWeight: 600, color: 'var(--color-ink)' },
          // body 需显式限定高度：antd 只让整个对话框滚动，不钉住的话「知道了」会被滚出屏幕
          body: { maxHeight: '65vh', overflowY: 'auto', fontSize: 16, lineHeight: 1.7 },
        }}
        footer={
          <Button type="primary" size="large" block onClick={close}>
            知道了
          </Button>
        }
      >
        <p className={styles.summary}>{guide.summary}</p>

        <p className={styles.audience}>
          <span className={styles.audienceLabel}>适用</span>
          {guide.audience}
        </p>

        <h3 className={styles.sectionTitle}>操作步骤</h3>
        <ol className={styles.steps}>
          {guide.steps.map((step, i) => (
            <li key={i}>
              <span className={styles.stepText}>{step.text}</span>
              {step.tip && <span className={styles.stepTip}>{step.tip}</span>}
            </li>
          ))}
        </ol>

        {guide.notes && guide.notes.length > 0 && (
          <>
            <h3 className={styles.sectionTitle}>注意事项</h3>
            <ul className={styles.notes}>
              {guide.notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </>
        )}
      </Modal>
    </>
  )
}
