'use client'

import { useCallback, useState } from 'react'
import Link from 'next/link'
import {
  Alert, App, Button, Card, Input, Space, Statistic, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  CloudSyncOutlined, ReloadOutlined, SettingOutlined,
  TeamOutlined, AimOutlined, MinusCircleOutlined, DashboardOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { fetchHeadcountPlans, triggerEmployeeSync } from '@/actions/hr'
import { usePermission } from '@/hooks/usePermission'
import type { HeadcountData, HeadcountPlanRow } from '@/types/hr'

const { Text } = Typography

/** 编制页顶部的同步状态精简形态（服务端注入，避免客户端重复拉取） */
export interface HeadcountSyncInfo {
  enabled: boolean
  headcount_table_id: string
  headcount_table_name: string
  last_sync_at: string | null
}

interface HeadcountClientProps {
  initialData: HeadcountData | null
  syncInfo: HeadcountSyncInfo | null
}

function formatSyncTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ') : '从未同步'
}

/** 缺编 badge：缺=红 / 满编=绿 / 超编=橙 */
function VacancyTag({ vacancy }: { vacancy: number }) {
  if (vacancy > 0) return <Tag color="red">缺编 {vacancy}</Tag>
  if (vacancy === 0) return <Tag color="green">满编</Tag>
  return <Tag color="orange">超编 {-vacancy}</Tag>
}

/**
 * 编制数（部门定编）页面。
 * 定编数据随员工档案同步拉取（同一 Base 一次同步两表）；
 * 在编/缺编按员工档案实时统计，飞书手填「现有人数」仅作对账参考列。
 */
export default function HeadcountClient({ initialData, syncInfo }: HeadcountClientProps) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [data, setData] = useState<HeadcountData | null>(initialData)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [keyword, setKeyword] = useState('')

  const canManage = hasPermission('hr:settings:manage')

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      setData((await fetchHeadcountPlans()).data)
    } catch (err) {
      message.error(err instanceof Error && err.message ? err.message : '加载编制数据失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await triggerEmployeeSync()
      const hc = res.data?.headcount
      if (hc?.error) {
        message.warning(`员工档案已同步，但定编表拉取失败：${hc.error}`, 10)
      } else if (hc) {
        message.success(`同步完成：员工档案 ${res.data?.updated ?? 0} 条更新，定编 ${hc.total ?? 0} 行`)
      } else {
        message.success(`同步完成：员工档案 ${res.data?.updated ?? 0} 条更新`)
      }
      await loadData()
    } catch (err) {
      message.error(err instanceof Error && err.message ? err.message : '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const plans = data?.plans ?? []
  const summary = data?.summary
  const filtered = keyword
    ? plans.filter((p) => p.department.includes(keyword))
    : plans

  const columns: ColumnsType<HeadcountPlanRow> = [
    {
      title: '部门',
      dataIndex: 'department',
      width: 200,
      render: (v: string, row) => (
        row.matched
          ? <Link href={`/staffing/profile?department=${encodeURIComponent(v)}`} className="font-medium">{v}</Link>
          : (
            <Tooltip title="员工档案中未找到同名部门，在编按 0 统计；请核对定编表与档案的部门写法">
              <span className="font-medium">{v}</span>
              <Tag color="warning" className="ml-1">未匹配</Tag>
            </Tooltip>
          )
      ),
    },
    {
      title: '定编',
      dataIndex: 'department_quota',
      width: 90,
      align: 'right',
      render: (v: number) => <span className="font-medium">{v}</span>,
    },
    {
      title: '在编',
      dataIndex: 'actual_count',
      width: 110,
      align: 'right',
      render: (v: number, row) => (
        <Space size={4}>
          <span className="font-medium">{v}</span>
          {row.department_quota > 0 && (
            <Text type="secondary" className="text-xs">
              {Math.round((v / row.department_quota) * 100)}%
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '飞书参考',
      dataIndex: 'source_current_count',
      width: 100,
      align: 'right',
      render: (v: number | null, row) => {
        if (v === null || v === undefined) return <Text type="secondary">-</Text>
        // 手填值与本地统计不一致时标灰提醒（便于发现飞书表未及时更新）
        return v === row.actual_count
          ? <Text type="secondary">{v}</Text>
          : (
            <Tooltip title={`飞书手填 ${v} 与本地统计 ${row.actual_count} 不一致（以本地统计为准）`}>
              <Text type="warning">{v}*</Text>
            </Tooltip>
          )
      },
    },
    {
      title: '缺编',
      dataIndex: 'vacancy',
      width: 110,
      render: (v: number) => <VacancyTag vacancy={v} />,
    },
    {
      title: '岗位明细',
      dataIndex: 'position_detail',
      ellipsis: true,
      render: (v: string) => (v ? <Text type="secondary">{v}</Text> : '-'),
    },
  ]

  return (
    <div className="space-y-4">
      {/* 同步状态条 */}
      <Card size="small">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <Space size="middle" wrap>
            <CloudSyncOutlined />
            <Text type="secondary" className="text-sm">上次同步：{formatSyncTime(syncInfo?.last_sync_at ?? null)}</Text>
            <Text type="secondary" className="text-sm">
              定编表：{syncInfo?.headcount_table_id ? (syncInfo.headcount_table_name || syncInfo.headcount_table_id) : '未绑定'}
            </Text>
          </Space>
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => { void loadData() }} loading={loading}>
              刷新
            </Button>
            {canManage && (
              <Button size="small" type="primary" icon={<CloudSyncOutlined />} onClick={handleSync} loading={syncing}>
                立即同步（档案+定编）
              </Button>
            )}
          </Space>
        </div>
      </Card>

      {!syncInfo?.headcount_table_id && (
        <Alert
          type="info"
          showIcon
          title="尚未绑定定编数表"
          description={(
            <>
              在 员工档案 页顶部的「多维表格同步」面板中填写「定编数数据表 table_id」，
              绑定后每次同步将顺带拉取编制数据。
              <Link href="/staffing/profile" className="ml-1">
                去设置 <SettingOutlined />
              </Link>
            </>
          )}
        />
      )}

      {summary && summary.unmatched_departments.length > 0 && (
        <Alert
          type="warning"
          showIcon
          title={`${summary.unmatched_departments.length} 个部门未匹配到员工档案`}
          description={`定编表部门：${summary.unmatched_departments.join('、')}；其缺编按在编 0 计算，请核对两边部门名称写法。`}
        />
      )}

      {/* 汇总指标 */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Card size="small"><Statistic title="总定编" value={summary.total_quota} suffix="人" prefix={<AimOutlined className="mr-1 text-[var(--color-primary)]" />} /></Card>
          <Card size="small"><Statistic title="在编（实时）" value={summary.total_actual} suffix="人" prefix={<TeamOutlined className="mr-1 text-[var(--color-primary)]" />} /></Card>
          <Card size="small">
            <Statistic
              title="缺编合计" value={summary.total_vacancy} suffix="人"
              prefix={<MinusCircleOutlined className={summary.total_vacancy > 0 ? 'mr-1 text-red-500' : summary.total_vacancy < 0 ? 'mr-1 text-orange-500' : 'mr-1 text-green-500'} />}
              valueStyle={summary.total_vacancy > 0 ? { color: '#cf1322' } : summary.total_vacancy < 0 ? { color: '#d46b08' } : { color: '#389e0d' }}
            />
          </Card>
          <Card size="small"><Statistic title="编制达成率" value={summary.achievement_rate} suffix="%" precision={1} prefix={<DashboardOutlined className="mr-1 text-[var(--color-primary)]" />} /></Card>
        </div>
      )}

      {/* 定编表 */}
      <Card size="small">
        <div className="flex items-center justify-between mb-3">
          <Input.Search
            placeholder="搜索部门"
            allowClear
            style={{ width: 220 }}
            onSearch={setKeyword}
            onChange={(e) => { if (!e.target.value) setKeyword('') }}
          />
          <Text type="secondary" className="text-sm">
            共 {summary?.department_count ?? 0} 个部门；点击部门名查看该部门员工
          </Text>
        </div>
        <Table<HeadcountPlanRow>
          rowKey="department"
          size="small"
          loading={loading}
          dataSource={filtered}
          pagination={false}
          columns={columns}
          expandable={{
            rowExpandable: (r) => (r.positions?.length ?? 0) > 0,
            expandedRowRender: (r) => (
              <div className="flex flex-wrap gap-2 py-1">
                {r.positions.map((p) => (
                  <Tag key={p.name} color={p.count != null && p.count > 0 ? 'blue' : 'default'}>
                    {p.name}
                    {p.count !== null ? ` ×${p.count}` : ''}
                  </Tag>
                ))}
              </div>
            ),
          }}
        />
      </Card>
    </div>
  )
}
