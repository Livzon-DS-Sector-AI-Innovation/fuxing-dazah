'use client'

import Link from 'next/link'
import { ArrowRightOutlined, BarChartOutlined, BellOutlined, CloudServerOutlined, DatabaseOutlined, HistoryOutlined, SettingOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { PageHeading } from '@/components/shared/PageHeading'
import { EnergyPageFrame } from '@/components/energy'
import styles from '@/components/energy/EnergyAnalytics.module.css'

const entries = [
  { href: '/energy/visualization', title: '能源总览', description: '查看能耗趋势、部门排名和峰谷分布。', icon: <BarChartOutlined />, tone: 'lavender' },
  { href: '/energy/collect-history', title: '采集历史', description: '按能源类型回溯历史采集数据，定位异常波动。', icon: <HistoryOutlined />, tone: 'sky' },
  { href: '/energy/collect-logs', title: '采集日志', description: '跟踪数据源采集状态、失败原因和重试进度。', icon: <DatabaseOutlined />, tone: 'mint' },
  { href: '/energy/devices', title: '数据源配置', description: '维护平台连接、设备映射和采集归属。', icon: <CloudServerOutlined />, tone: 'peach' },
  { href: '/energy/type-config', title: '能源配置', description: '统一维护能源类型、单位和展示颜色。', icon: <SettingOutlined />, tone: 'yellow' },
  { href: '/energy/alerts', title: '预警管理', description: '配置预警规则、车间阈值与报告推送。', icon: <BellOutlined />, tone: 'rose' },
  { href: '/energy/alert-process', title: '预警处理', description: '集中处理待确认的能源异常记录。', icon: <ThunderboltOutlined />, tone: 'rose' },
]

export default function EnergyPage() {
  return (
    <EnergyPageFrame>
      <PageHeading title="能源管理" subtitle="把采集、分析、配置和异常处理集中在一个工作台。" />
      <div className={styles.stack}>
        <section className={styles.intro}>
          <div>
            <h2>能源运营工作台</h2>
            <p>从总览开始了解今天的能耗，再进入采集、配置或预警处理流程。每个入口都会保留当前页面的筛选与操作上下文。</p>
          </div>
          <Link className={styles.quickLink} href="/energy/visualization" style={{ minWidth: 170, padding: '14px 16px', alignItems: 'center' }}>
            <span>打开能源总览</span><ArrowRightOutlined />
          </Link>
        </section>
        <section>
          <div className={styles.panelHeader}>
            <div><h2>常用工作流</h2><p>按任务进入对应页面，减少在菜单中来回查找。</p></div>
          </div>
          <div className={styles.quickGrid}>
            {entries.map((entry) => (
              <Link className={styles.quickLink} href={entry.href} key={entry.href}>
                <span className={styles.quickIcon}>{entry.icon}</span>
                <span><h3>{entry.title}</h3><p>{entry.description}</p></span>
                <ArrowRightOutlined style={{ marginLeft: 'auto', color: '#a4a097' }} />
              </Link>
            ))}
          </div>
        </section>
      </div>
    </EnergyPageFrame>
  )
}
