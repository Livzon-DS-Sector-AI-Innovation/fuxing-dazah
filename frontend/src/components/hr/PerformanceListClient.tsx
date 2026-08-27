'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Button, Card, DatePicker, Select, Space, Table, Tag, message, Modal } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchPerformanceEvaluations,
  fetchMyPerformanceEvaluations,
  autoCreatePerformanceEvaluations,
} from '@/actions/hr'

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  self_submitted: { color: 'blue', label: '待领导评分' },
  leader_scored: { color: 'green', label: '已完成' },
}

export default function PerformanceListClient() {
  const router = useRouter()
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
  }, [mode, month, status, page])

  useEffect(() => { loadData() }, [loadData])

  // 切换筛选条件时重置页码
  useEffect(() => { setPage(1) }, [mode, month, status])

  const handleAutoCreate = async () => {
    Modal.confirm({
      title: '批量生成当月考核',
      content: `将为所有部门生成 ${month} 的考核记录（已有则跳过），确认？`,
      onOk: async () => {
        try {
          const res = await autoCreatePerformanceEvaluations(month)
          message.success(res.message || `已为 ${res.data.created} 个部门生成考核`)
          loadData()
        } catch (err: any) {
          message.error(err.message || '生成失败')
        }
      },
    })
  }

  const columns = [
    { title: '部门', dataIndex: 'department', key: 'department', width: 150 },
    { title: '考核月份', dataIndex: 'evaluation_month', key: 'month', width: 100 },
    { title: '部门负责人', dataIndex: 'department_head', key: 'head', width: 100 },
    { title: '分管领导', dataIndex: 'evaluator_leader', key: 'leader', width: 100, render: (v: any) => v || '—' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 120,
      render: (s: string) => <Tag color={STATUS_MAP[s]?.color || 'default'}>{STATUS_MAP[s]?.label || s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: any, record: any) => <Button type="link" onClick={() => router.push(`/hr/performance/${record.id}`)}>查看</Button>,
    },
  ]

  return (
    <Card title="月度绩效考核" extra={
      <Space>
        <Button size="small" type={mode === 'my' ? 'primary' : 'default'} onClick={() => { setMode('my'); setPage(1) }}>我的考核</Button>
        <Button size="small" type={mode === 'all' ? 'primary' : 'default'} onClick={() => { setMode('all'); setPage(1) }}>全部考核</Button>
      </Space>
    }>
      <Space className="mb-4" wrap>
        <DatePicker picker="month" value={month ? dayjs(month) : null} onChange={(d) => setMonth(d ? d.format('YYYY-MM') : '')} allowClear placeholder="按月份筛选" />
        <Select value={status || undefined} onChange={(v) => setStatus(v || '')} allowClear placeholder="按状态筛选" style={{ width: 140 }}
          options={[{value:'draft',label:'草稿'},{value:'self_submitted',label:'待领导评分'},{value:'leader_scored',label:'已完成'}]} />
        <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
        {mode === 'all' && <Button icon={<PlusOutlined />} onClick={handleAutoCreate}>批量生成当月考核</Button>}
        <Button onClick={() => router.push('/hr/performance/score')}>批量项目评分</Button>
      </Space>
      {!loading && data.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          <p className="text-lg mb-2">暂无考核记录</p>
          <p className="mb-4">点击「批量生成当月考核」自动从部门管理和部门培训人员表拉取数据</p>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAutoCreate}>批量生成当月考核</Button>
        </div>
      )}
      {data.length > 0 && <Table rowKey="id" loading={loading} dataSource={data} columns={columns}
        pagination={{ current: page, total, pageSize: 20, onChange: (p) => setPage(p), showTotal: (t) => `共 ${t} 条` }}
        onRow={(r) => ({ style: { cursor: 'pointer' }, onClick: () => router.push(`/hr/performance/${r.id}`) })}
      />}
    </Card>
  )
}
