'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { App, Button, Card, DatePicker, Segmented, Select, Space, Table, Tag } from 'antd'
import { DownloadOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchPerformanceEvaluations,
  fetchMyPerformanceEvaluations,
  autoCreatePerformanceEvaluations,
  fetchPerformanceReport,
} from '@/actions/hr'
import { PERFORMANCE_STATUS_META, downloadBase64File } from '@/lib/hr'

export default function PerformanceListClient() {
  const router = useRouter()
  const { message, modal } = App.useApp()
  const [mode, setMode] = useState<'all' | 'my'>('all')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [month, setMonth] = useState<string>('')
  const [status, setStatus] = useState<string>('')

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      if (mode === 'my') {
        // 我的考核：先全量拉取再前端过滤状态
        const res = await fetchMyPerformanceEvaluations(month || undefined)
        let items = res.data.items || []
        if (status) items = items.filter((it: any) => it.status === status)
        setData(items)
        setTotal(items.length)
      } else {
        const params: any = { page, page_size: 20 }
        if (month) params.month = month
        if (status) params.status = status
        const res = await fetchPerformanceEvaluations(params)
        setData(res.data.items || [])
        setTotal(res.data.total || 0)
      }
    } catch (err: any) {
      message.error(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
    // message 不进依赖数组（App.useApp 的 message 进 deps 会反复触发加载）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, month, status, page])

  // 筛选变化先重置页码再加载（单次请求，避免旧页请求与新页请求竞态覆盖）
  useEffect(() => {
    if (page !== 1) {
      setPage(1)
      return
    }
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, month, status, page, loadData])

  const handleAutoCreate = async () => {
    // 未选月份时按「当月」生成（按钮文案即「当月」）：空月份会为全部部门建出月份为空的脏记录
    const targetMonth = month || dayjs().format('YYYY-MM')
    modal.confirm({
      title: '批量生成当月考核',
      content: `将为所有部门生成 ${targetMonth} 的考核记录（已有则跳过），确认？`,
      onOk: async () => {
        try {
          const res = await autoCreatePerformanceEvaluations(targetMonth)
          message.success(res.message || `已为 ${res.data.created} 个部门生成考核`)
          loadData()
        } catch (err: any) {
          message.error(err.message || '生成失败')
        }
      },
    })
  }

  const handleDownloadReport = async () => {
    try {
      const { base64, filename } = await fetchPerformanceReport(month)
      downloadBase64File(base64, filename || `绩效汇总_${month}.xlsx`)
    } catch (err: any) {
      message.error(err.message || '导出失败')
    }
  }

  const columns = [
    { title: '部门', dataIndex: 'department', key: 'department', width: 150, ellipsis: true },
    { title: '考核月份', dataIndex: 'evaluation_month', key: 'month', width: 100 },
    { title: '部门负责人', dataIndex: 'department_head', key: 'head', width: 100, ellipsis: true },
    { title: '分管领导', dataIndex: 'evaluator_leader', key: 'leader', width: 100, render: (v: any) => v || '—' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 120,
      render: (s: string) => <Tag color={PERFORMANCE_STATUS_META[s]?.color || 'default'}>{PERFORMANCE_STATUS_META[s]?.label || s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: any, record: any) => <Button type="link" onClick={() => router.push(`/hr/performance/${record.id}`)}>查看</Button>,
    },
  ]

  // 仅「全部考核 + 无任何筛选 + 没有数据」才认为是真没生成过考核，展示批量生成引导；
  // 带筛选无结果只提示没有符合条件的记录
  const showCreateGuide = mode === 'all' && !month && !status

  return (
    <Card extra={
      <Segmented<'all' | 'my'> value={mode} onChange={(v) => { setMode(v); setPage(1) }}
        options={[{ value: 'my', label: '我的考核' }, { value: 'all', label: '全部考核' }]} />
    }>
      <Space className="mb-4" wrap>
        <DatePicker picker="month" value={month ? dayjs(month) : null} onChange={(d) => setMonth(d ? d.format('YYYY-MM') : '')} allowClear placeholder="按月份筛选" />
        <Select value={status || undefined} onChange={(v) => setStatus(v || '')} allowClear placeholder="按状态筛选" style={{ width: 140 }}
          options={Object.entries(PERFORMANCE_STATUS_META).map(([value, meta]) => ({ value, label: meta.label }))} />
        <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
        {mode === 'all' && <Button icon={<PlusOutlined />} onClick={handleAutoCreate}>批量生成当月考核</Button>}
        <Button onClick={() => router.push('/hr/performance/score')}>批量项目评分</Button>
        <Button icon={<DownloadOutlined />} onClick={handleDownloadReport}>汇总报表</Button>
      </Space>
      {!loading && data.length === 0 && (
        showCreateGuide ? (
          <div className="text-center py-12 text-gray-400">
            <p className="text-lg mb-2">暂无考核记录</p>
            <p className="mb-4">点击「批量生成当月考核」自动从部门管理和部门培训人员表拉取数据</p>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAutoCreate}>批量生成当月考核</Button>
          </div>
        ) : (
          <div className="text-center py-12 text-gray-400">没有符合条件的考核记录</div>
        )
      )}
      {data.length > 0 && <Table rowKey="id" loading={loading} dataSource={data} columns={columns}
        pagination={{ current: page, total, pageSize: 20, onChange: (p) => setPage(p), showTotal: (t) => `共 ${t} 条` }}
        onRow={(r) => ({ style: { cursor: 'pointer' }, onClick: () => router.push(`/hr/performance/${r.id}`) })}
      />}
    </Card>
  )
}
