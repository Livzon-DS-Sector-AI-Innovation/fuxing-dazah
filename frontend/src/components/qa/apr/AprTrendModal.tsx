'use client'

import { Modal } from 'antd'
import { LineChartOutlined } from '@ant-design/icons'
import { AprChromeStyles, AprMeta, AprSegmented } from './AprChrome'
import { AprTrendChart } from './AprTrendChart'
import type { AprItem, AprTrend } from '@/types/qa'

/**
 * 单列趋势弹窗。
 *
 * 趋势是对着表里的某一列做的即时分析，放在页面底端会把用户带离表格；
 * 弹窗保留表格上下文，关掉即回到原来的滚动位置。
 */
export function AprTrendModal({
  item,
  year,
  scope,
  onScopeChange,
  onClose,
  trend,
  loading,
  error,
}: {
  item: AprItem | null
  year: number
  scope: 'year' | 'all'
  onScopeChange: (scope: 'year' | 'all') => void
  onClose: () => void
  trend: AprTrend | null
  loading: boolean
  error: string | null
}) {
  return (
    <Modal
      open={!!item}
      onCancel={onClose}
      footer={null}
      centered
      width="min(1180px, calc(100vw - 32px))"
      title={
        item ? (
          <span className={AprChromeStyles.trendTitle}>
            <LineChartOutlined aria-hidden="true" />
            趋势：{item.name_cn}
          </span>
        ) : null
      }
      styles={{ body: { maxHeight: 'calc(100vh - 180px)', overflowY: 'auto' } }}
    >
      {item ? (
        <>
          <div className={AprChromeStyles.trendToolbar}>
            <AprMeta
              items={[
                item.unit,
                item.spec_text ? `标准 ${item.spec_text}` : false,
                item.oot_min != null || item.oot_max != null ? '含 OOT 预警限' : false,
              ]}
            />
            <AprSegmented
              ariaLabel="趋势范围"
              value={scope}
              onChange={onScopeChange}
              options={[
                { value: 'year', label: `${year} 年` },
                { value: 'all', label: '跨年' },
              ]}
            />
          </div>
          <AprTrendChart trend={trend} loading={loading} error={error} height={440} />
          <p className={AprChromeStyles.trendHint}>
            {trend && trend.points.length > 15
              ? '横轴只标出部分批号；悬停任意点查看完整批号与数值，拖拽下方滑块可缩放区间。'
              : '横轴只标出部分批号；悬停任意点查看完整批号与数值。'}
          </p>
        </>
      ) : null}
    </Modal>
  )
}
