'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Segmented, Spin } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, EyeOutlined, FieldTimeOutlined, RadarChartOutlined, StopOutlined, WarningOutlined } from '@ant-design/icons'
import { MeterOverview } from '@/types/meter'
import { getMeterOverview } from '@/actions/meter'
import styles from './MeterModule.module.css'

type Source = 'instrument' | 'gas_detector'
const sourceLabel: Record<Source, string> = { instrument: '标准计量器具', gas_detector: '有毒有害可燃探测器' }

export function MeterOverviewPanel() {
  const { message } = App.useApp()
  const [source, setSource] = useState<Source>('instrument')
  const [data, setData] = useState<MeterOverview | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try { setData(await getMeterOverview(source)) } catch { message.error('获取仪表总览失败') } finally { setLoading(false) }
  }, [message, source])

  useEffect(() => { const timer = setTimeout(fetchData, 0); return () => clearTimeout(timer) }, [fetchData])

  const stats = data ?? { total: 0, in_use: 0, overdue: 0, stopped: 0, due_today: 0, due_7d: 0, due_30d: 0, due_90d: 0 }
  const safePercent = stats.total ? Math.round((stats.in_use / stats.total) * 100) : 0
  const barWidth = (value: number) => `${stats.total ? Math.max((value / stats.total) * 100, value ? 2 : 0) : 0}%`
  const metricCards = [
    { label: '设备总数', value: stats.total, note: `${sourceLabel[source]} · 实时同步`, icon: <RadarChartOutlined />, className: styles.accentPurple },
    { label: '正常在用', value: stats.in_use, note: `运行健康度 ${safePercent}%`, icon: <CheckCircleOutlined />, className: styles.accentTeal },
    { label: '检定超期', value: stats.overdue, note: stats.overdue ? '建议优先处理' : '当前无超期记录', icon: <WarningOutlined />, className: styles.accentCoral },
    { label: '已停用', value: stats.stopped, note: '不计入运行健康度', icon: <StopOutlined />, className: styles.accentAmber },
  ]

  return (
    <main className={styles.page}>
      <div className={styles.pageNarrow}>
        <section className={styles.hero}>
          <div className={styles.heroContent}>
            <div className={styles.eyebrow}><span className={styles.eyebrowDot} /> METER CONTROL CENTER</div>
            <h1 className={styles.title}>仪表中枢，掌握每一次检定。</h1>
            <p className={styles.subtitle}>将计量器具、气体探测器与检定节点集中到同一张运行地图，快速识别风险，提前安排校准。</p>
          </div>
          <div className={styles.orbital} aria-hidden="true"><div className={styles.orbitalCore} /></div>
        </section>

        <div className={styles.sectionHeading}>
          <div><h2 className={styles.sectionTitle}>运行快照</h2><p className={styles.sectionHint}>数据源：{sourceLabel[source]} · 最后刷新后自动更新</p></div>
          <Segmented className={styles.sourceSwitch} value={source} onChange={(value) => setSource(value as Source)} options={[{ label: '计量器具', value: 'instrument' }, { label: '气体探测器', value: 'gas_detector' }]} />
        </div>

        <section className={styles.metricGrid} aria-label="运行指标">
          {metricCards.map((card) => <article className={`${styles.metricCard} ${card.className}`} key={card.label}><div className={styles.metricTop}><span>{card.label}</span><span className={styles.metricIcon}>{card.icon}</span></div><div className={styles.metricValue}>{loading ? <Spin size="small" /> : card.value.toLocaleString()}</div><div className={styles.metricMeta}>{card.note}</div></article>)}
        </section>

        <section className={styles.overviewGrid}>
          <div className={styles.panel}>
            <div className={styles.panelHeader}><div><h3 className={styles.panelTitle}>设备健康度</h3><p className={styles.panelSub}>按当前状态分布</p></div><EyeOutlined style={{ color: '#8378c9' }} /></div>
            <div className={styles.healthBody}>
              <div className={styles.healthBar} aria-label="设备状态分布"><span style={{ width: barWidth(stats.in_use), '--bar-color': '#32c7b3' } as React.CSSProperties} /><span style={{ width: barWidth(stats.overdue), '--bar-color': '#ff927e' } as React.CSSProperties} /><span style={{ width: barWidth(stats.stopped), '--bar-color': '#f0bd4c' } as React.CSSProperties} /></div>
              <div className={styles.healthLegend}>
                <div><div className={styles.legendItem}><i className={styles.legendDot} style={{ '--dot': '#32c7b3' } as React.CSSProperties} />正常在用</div><strong className={styles.legendValue}>{stats.in_use}</strong></div>
                <div><div className={styles.legendItem}><i className={styles.legendDot} style={{ '--dot': '#ff927e' } as React.CSSProperties} />检定超期</div><strong className={styles.legendValue}>{stats.overdue}</strong></div>
                <div><div className={styles.legendItem}><i className={styles.legendDot} style={{ '--dot': '#f0bd4c' } as React.CSSProperties} />已停用</div><strong className={styles.legendValue}>{stats.stopped}</strong></div>
              </div>
            </div>
          </div>
          <div className={styles.panel}>
            <div className={styles.panelHeader}><div><h3 className={styles.panelTitle}>检定节奏</h3><p className={styles.panelSub}>需要关注的时间窗口</p></div><FieldTimeOutlined style={{ color: '#8378c9' }} /></div>
            <div className={styles.dueList}>
              <div className={styles.dueRow}><span className={styles.dueLabel}>今天到期</span><strong className={`${styles.dueValue} ${stats.due_today ? styles.warning : styles.good}`}>{stats.due_today}<small>台</small></strong></div>
              <div className={styles.dueRow}><span className={styles.dueLabel}>未来 7 天</span><strong className={`${styles.dueValue} ${stats.due_7d ? styles.warning : ''}`}>{stats.due_7d}<small>台</small></strong></div>
              <div className={styles.dueRow}><span className={styles.dueLabel}>未来 30 天</span><strong className={`${styles.dueValue} ${stats.due_30d ? styles.warning : ''}`}>{stats.due_30d}<small>台</small></strong></div>
              <div className={styles.dueRow}><span className={styles.dueLabel}>未来 90 天</span><strong className={styles.dueValue}>{stats.due_90d}<small>台</small></strong></div>
            </div>
          </div>
        </section>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}><Button type="link" href="/meter/departments" icon={<ClockCircleOutlined />}>管理部门提醒规则</Button></div>
      </div>
    </main>
  )
}
