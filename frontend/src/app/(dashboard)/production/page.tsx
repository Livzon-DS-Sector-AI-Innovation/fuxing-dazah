'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Row, Col, Spin } from 'antd'
import {
  AppstoreOutlined,
  FileTextOutlined,
  ArrowRightOutlined,
  ToolOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import type { Product } from '@/types/production'
import { fetchProductsClient } from '@/lib/api/production-client'
import { StepCyclePanel } from '@/components/production'
import { PageHeading } from '@/components/shared/PageHeading'
import styles from './ProductionDashboard.module.css'

const MENU_ITEMS = [
  {
    key: '/production/batches',
    title: '批次管理',
    description: '批次档案、状态流转与全链路溯源',
    icon: <AppstoreOutlined />,
    bg: '#e6e0f5',
    iconBg: '#5645d4',
  },
  {
    key: '/production/process',
    title: '产品工艺',
    description: '工艺规程主数据与版本管理',
    icon: <FileTextOutlined />,
    bg: '#ffe8d4',
    iconBg: '#dd5b00',
  },
  {
    key: '/production/workbench',
    title: '工作台',
    description: '批次执行与工序现场操作',
    icon: <ToolOutlined />,
    bg: '#dcecfa',
    iconBg: '#0075de',
  },
  {
    key: '/production/analytics',
    title: '数据汇总',
    description: '工段汇总矩阵与批次字段趋势分析',
    icon: <BarChartOutlined />,
    bg: '#d9f3e1',
    iconBg: '#1aae39',
  },
]

export default function ProductionDashboard() {
  const router = useRouter()
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)

  // 页面加载时获取产品数据，供工序周期分析使用
  useEffect(() => {
    fetchProductsClient()
      .then(setProducts)
      .catch(error => console.error('Failed to load dashboard products:', error))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className={styles.dashboard}>
      {/* ── Header ── */}
      <PageHeading title="生产管理概览" subtitle="实时监控生产运营状态，快速进入管理视图" />

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
          <Spin size="large" />
        </div>
      ) : (
        <>
          {/* ── Quick Access ── */}
          <Row gutter={24}>
            <Col span={24}>
              <Card
                className={styles.quickPanel}
                title={
                  <div className={styles.panelTitle}>
                    <span className={styles.panelTitleMark}><AppstoreOutlined /></span>
                    <span className={styles.panelTitleText}>快捷操作</span>
                    <span className={styles.panelTitleHint}>快速进入生产管理视图</span>
                  </div>
                }
                variant="borderless"
              >
                <Row gutter={[12, 12]}>
                  {MENU_ITEMS.map(item => (
                    <Col xs={24} sm={12} lg={6} key={item.key}>
                      <div
                        className={styles.quickAction}
                        onClick={() => router.push(item.key)}
                        style={{
                          background: item.bg,
                        }}
                      >
                        <div
                          className={styles.quickIcon}
                          style={{
                            background: `linear-gradient(145deg, ${item.iconBg}, ${item.iconBg}cc)`,
                          }}
                        >
                          {item.icon}
                        </div>
                        <div className={styles.quickCopy}>
                          <div className={styles.quickTitle}>
                            {item.title}
                          </div>
                          <div className={styles.quickDescription}>
                            {item.description}
                          </div>
                        </div>
                        <ArrowRightOutlined className={styles.quickArrow} />
                      </div>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>
          </Row>

          {/* ── 工序周期分析 ── */}
          <StepCyclePanel products={products} />
        </>
      )}
    </div>
  )
}
