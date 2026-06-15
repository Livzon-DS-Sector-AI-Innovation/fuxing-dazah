'use client'

import { useState, useEffect } from 'react'
import { App, Card, Button, Statistic, Row, Col, Tag, Spin } from 'antd'
import { SyncOutlined, CloudSyncOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { fetchSyncStatus, syncFromFeishu } from '@/lib/api/hr'

interface SyncStatus {
  local_total: number
  feishu_total: number
  synced_count: number
  unsynced_count: number
  conflict_count: number
  last_sync_at: string | null
}

export default function FeishuSyncPanel({ onSynced }: { onSynced?: () => void }) {
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const loadStatus = async () => {
    setLoading(true)
    try {
      const res = await fetchSyncStatus()
      setStatus(res.data)
    } catch (err: any) {
      message.error(err.message || '获取同步状态失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStatus()
  }, [])

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncFromFeishu()
      message.success(res.message)
      await loadStatus()
      onSynced?.()
    } catch (err: any) {
      message.error(err.message || '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const syncRate = status && status.local_total > 0
    ? Math.round((status.synced_count / status.local_total) * 100)
    : 0

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <CloudSyncOutlined />
          飞书多维表格同步状态
        </span>
      }
      extra={
        <Button
          type="primary"
          icon={<SyncOutlined spin={syncing} />}
          onClick={handleSync}
          loading={syncing}
        >
          从飞书同步
        </Button>
      }
    >
      <Spin spinning={loading}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="本地记录数" value={status?.local_total || 0} />
          </Col>
          <Col span={6}>
            <Statistic title="飞书记录数" value={status?.feishu_total || 0} />
          </Col>
          <Col span={6}>
            <Statistic
              title="已同步"
              value={status?.synced_count || 0}
              suffix={`/ ${status?.local_total || 0}`}
            />
          </Col>
          <Col span={6}>
            <div className="text-sm text-gray-500 mb-1">同步率</div>
            <Tag color={syncRate >= 90 ? 'success' : syncRate >= 50 ? 'warning' : 'error'}>
              {syncRate}%
            </Tag>
            {status && status.unsynced_count > 0 && (
              <Tag color="warning" icon={<ExclamationCircleOutlined />}>
                未同步 {status.unsynced_count}
              </Tag>
            )}
            {status && status.conflict_count > 0 && (
              <Tag color="error">冲突 {status.conflict_count}</Tag>
            )}
          </Col>
        </Row>
        {status?.last_sync_at && (
          <div className="mt-3 text-xs text-gray-400">
            上次同步: {status.last_sync_at}
          </div>
        )}
      </Spin>
    </Card>
  )
}
