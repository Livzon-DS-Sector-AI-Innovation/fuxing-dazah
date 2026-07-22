'use client'

import { useEffect, useState, useCallback } from 'react'
import { Select, Button, Switch, App, Popconfirm } from 'antd'
import { ThunderboltOutlined, DeleteOutlined } from '@ant-design/icons'
import { useEnergyStore } from '@/stores/energy'
import { CollectLogTable, CollectLogDetailDrawer } from '@/components/energy'
import { getCollectLogs, triggerCollect, getCollectSettings, updateCollectSettings, clearCollectLogs } from '@/actions/energy'
import type { CollectLog, PaginatedResponse, CollectSettings } from '@/types/energy'

export default function CollectLogsPage() {
  const { message } = App.useApp()
  const {
    logFilters,
    setLogFilters,
    resetLogFilters,
    collectLogDrawerOpen,
    collectLogDrawerId,
    closeCollectLogDrawer,
  } = useEnergyStore()

  const [loading, setLoading] = useState(false)
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [data, setData] = useState<PaginatedResponse<CollectLog>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 10,
  })

  // 自动采集开关
  const [autoCollectEnabled, setAutoCollectEnabled] = useState(false)
  const [settingsLoading, setSettingsLoading] = useState(false)

  const fetchSettings = useCallback(async () => {
    try {
      const s = await getCollectSettings()
      setAutoCollectEnabled(s.auto_collect_enabled)
    } catch {
      // 忽略设置加载失败，使用默认值
    }
  }, [])

  useEffect(() => {
    fetchSettings()
  }, [fetchSettings])

  const handleToggleAutoCollect = async (enabled: boolean) => {
    setSettingsLoading(true)
    try {
      const result = await updateCollectSettings({ auto_collect_enabled: enabled })
      setAutoCollectEnabled(result.auto_collect_enabled)
      message.success(enabled ? '自动采集已开启' : '自动采集已关闭')
    } catch {
      message.error('设置更新失败')
    } finally {
      setSettingsLoading(false)
    }
  }

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const result = await getCollectLogs(logFilters)
      setData(result)
    } catch (error) {
      console.error('获取采集日志失败:', error)
    } finally {
      setLoading(false)
    }
  }, [logFilters])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleTriggerCollect = async () => {
    setTriggerLoading(true)
    try {
      await triggerCollect()
      fetchData()
    } catch (error) {
      console.error('触发采集失败:', error)
    } finally {
      setTriggerLoading(false)
    }
  }

  const handleRetry = async (platformCode: string) => {
    try {
      await triggerCollect(platformCode)
      fetchData()
    } catch (error) {
      console.error('触发重试失败:', error)
    }
  }

  const [clearLoading, setClearLoading] = useState(false)

  const handleClearLogs = async () => {
    setClearLoading(true)
    try {
      await clearCollectLogs()
      message.success('采集日志已清空')
      fetchData()
    } catch {
      message.error('清空日志失败')
    } finally {
      setClearLoading(false)
    }
  }

  const filledInputStyle = {
    background: '#f6f5f4',
    border: 'none',
    borderRadius: 8,
    height: 36,
  }

  return (
    <div
      style={{
        padding: '28px 32px',
        maxWidth: 1280,
        minHeight: '100%',
        background: '#fafaf9',
      }}
    >
      {/* ════ 标题区 ════ */}
      <h1
        style={{
          fontSize: 28,
          fontWeight: 500,
          color: '#1a1a1a',
          margin: 0,
          letterSpacing: '-0.3px',
          lineHeight: 1.3,
        }}
      >
        采集日志
      </h1>
      <p
        style={{
          fontSize: 13,
          color: '#a4a097',
          margin: '4px 0 0',
          lineHeight: 1.5,
        }}
      >
        查看数据采集任务的执行记录与结果详情
      </p>

      {/* 渐变分割线 */}
      <div
        style={{
          height: 1,
          marginTop: 18,
          marginBottom: 20,
          background:
            'linear-gradient(to right, #5645d4 0%, #e6e0f5 40%, transparent 100%)',
        }}
      />

      {/* ════ 筛选栏 ════ */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          flexWrap: 'wrap',
          background: '#ffffff',
          borderRadius: 12,
          padding: '12px 18px',
          boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
          border: '1px solid #ede9e4',
          marginBottom: 20,
        }}
      >
        <Select
          placeholder="采集状态"
          allowClear
          variant="filled"
          style={{ width: 120, ...filledInputStyle }}
          value={logFilters.status}
          onChange={(value) => setLogFilters({ status: value, page: 1 })}
          options={[
            { label: '成功', value: 'success' },
            { label: '失败', value: 'failed' },
            { label: '部分成功', value: 'partial' },
          ]}
        />

        <Button
          onClick={resetLogFilters}
          style={{
            color: '#787671',
            borderRadius: 8,
            height: 36,
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          重置
        </Button>

        {/* 右侧弹簧 */}
        <div style={{ flex: 1 }} />

        {/* ════ 自动采集开关 ════ */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '4px 12px',
            borderRadius: 8,
            background: autoCollectEnabled ? '#d9f3e1' : '#f0eeec',
          }}
        >
          <span
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: autoCollectEnabled ? '#18732e' : '#787671',
              whiteSpace: 'nowrap',
            }}
          >
            自动采集
          </span>
          <Switch
            size="small"
            checked={autoCollectEnabled}
            loading={settingsLoading}
            onChange={handleToggleAutoCollect}
          />
        </div>

        <div
          style={{
            width: 1,
            height: 20,
            background: '#ede9e4',
            margin: '0 4px',
          }}
        />

        <Button
          icon={<ThunderboltOutlined />}
          onClick={handleTriggerCollect}
          loading={triggerLoading}
          style={{
            color: '#5645d4',
            borderColor: '#5645d4',
            borderRadius: 8,
            fontWeight: 500,
            fontSize: 14,
            height: 36,
            padding: '0 16px',
          }}
        >
          手动采集
        </Button>

        <Popconfirm
          title="清空采集日志"
          description="确定要清空所有采集日志吗？此操作不可恢复。"
          onConfirm={handleClearLogs}
          okText="确定清空"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button
            icon={<DeleteOutlined />}
            loading={clearLoading}
            style={{
              color: '#d9413b',
              borderColor: '#f5d9d7',
              borderRadius: 8,
              fontWeight: 500,
              fontSize: 14,
              height: 36,
              padding: '0 16px',
            }}
          >
            清空日志
          </Button>
        </Popconfirm>
      </div>

      {/* ════ 数据表格 ════ */}
      <CollectLogTable
        data={data.items}
        loading={loading}
        total={data.total}
        onRefresh={fetchData}
        onRetry={handleRetry}
      />

      {/* ════ 详情抽屉 ════ */}
      {collectLogDrawerOpen && collectLogDrawerId && (
        <CollectLogDetailDrawer
          logId={collectLogDrawerId}
          open={collectLogDrawerOpen}
          onClose={closeCollectLogDrawer}
        />
      )}
    </div>
  )
}
