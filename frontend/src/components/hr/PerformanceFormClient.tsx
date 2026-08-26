'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Button, Card, Input, InputNumber, Select, Space, Table, Tag, message, Descriptions, Divider, Popconfirm } from 'antd'
import { SaveOutlined, SendOutlined, ArrowLeftOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { fetchPerformanceEvaluation, updatePerformanceEvaluation, submitSelfEvaluation, submitLeaderEvaluation, fetchCategoryScores, saveCategoryScores } from '@/actions/hr'

const CATEGORY_OPTIONS = [
  { value: 'key_work', label: '月度重点工作' },
  { value: 'routine_work', label: '月度常规工作' },
  { value: 'reward_penalty', label: '奖惩项目' },
]

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  self_submitted: { color: 'blue', label: '待领导评分' },
  leader_scored: { color: 'green', label: '已完成' },
  confirmed: { color: 'purple', label: '已确认' },
}

export default function PerformanceFormClient() {
  const params = useParams()
  const router = useRouter()
  const evalId = params.id as string
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [evaluation, setEvaluation] = useState<any>(null)
  const [items, setItems] = useState<any[]>([])
  const [editable, setEditable] = useState(true)
  const [categoryScores, setCategoryScores] = useState<any[]>([])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [ev, cs] = await Promise.all([
        fetchPerformanceEvaluation(evalId),
        fetchCategoryScores(evalId),
      ])
      setEvaluation(ev.data)
      setItems(ev.data.items || [])
      setCategoryScores(cs.data || [])
      setEditable(ev.data.status === 'draft')
    } catch (err: any) { message.error(err.message || '加载失败') }
    finally { setLoading(false) }
  }, [evalId])

  useEffect(() => { loadData() }, [loadData])

  const updateItem = (i: number, f: string, v: any) => setItems((p: any[]) => { const n = [...p]; n[i] = { ...n[i], [f]: v }; return n })

  const addItem = () => setItems((p: any[]) => [...p, { category: 'key_work', indicator: '', standard: '', weight: 0, self_score: null, leader_score: null, final_score: null, completion: '', sort_order: p.length }])

  const handleSave = async () => {
    setSaving(true)
    try {
      await updatePerformanceEvaluation(evalId, { items })
      message.success('已保存')
      loadData()
    } catch (err: any) { message.error(err.message || '保存失败') }
    finally { setSaving(false) }
  }

  const handleSubmitSelf = async () => {
    setSubmitting(true)
    try {
      await updatePerformanceEvaluation(evalId, { items })
      await submitSelfEvaluation(evalId)
      message.success('自评已提交，已通知分管领导')
      loadData()
    } catch (err: any) { message.error(err.message || '提交失败') }
    finally { setSubmitting(false) }
  }

  const handleSubmitLeader = async () => {
    setSubmitting(true)
    try {
      await updatePerformanceEvaluation(evalId, { items })
      await submitLeaderEvaluation(evalId)
      message.success('领导评分已提交')
      loadData()
    } catch (err: any) { message.error(err.message || '提交失败') }
    finally { setSubmitting(false) }
  }

  const updateCatScore = (categoryId: string, val: any) => {
    setCategoryScores((prev: any[]) => prev.map((s: any) =>
      s.category_id === categoryId ? { ...s, score: val } : s
    ))
  }

  const handleSaveCatScores = async () => {
    setSaving(true)
    try {
      const batch = categoryScores.map((s: any) => ({
        evaluation_id: evalId,
        category_id: s.category_id,
        score: s.score,
        weight: s.weight,
      }))
      await saveCategoryScores(evalId, batch)
      message.success('项目评分已保存')
    } catch (err: any) { message.error(err.message || '保存失败') }
    finally { setSaving(false) }
  }

  const totalWeight = items.reduce((s: number, it: any) => s + (it.weight || 0), 0)
  const totalSelf = items.reduce((s: number, it: any) => s + ((it.self_score || 0) * (it.weight || 0) / 100), 0)
  const totalLeader = items.reduce((s: number, it: any) => s + ((it.leader_score || 0) * (it.weight || 0) / 100), 0)

  if (loading) return <Card loading style={{ minHeight: 400 }} />
  const si = STATUS_MAP[evaluation?.status] || { color: 'default', label: evaluation?.status }

  return (
    <div className="space-y-4">
      <Button icon={<ArrowLeftOutlined />} onClick={() => router.back()} type="text">返回</Button>
      <Card>
        <Descriptions title="考核信息" column={4} size="small" bordered>
          <Descriptions.Item label="部门">{evaluation?.department}</Descriptions.Item>
          <Descriptions.Item label="月份">{evaluation?.evaluation_month}</Descriptions.Item>
          <Descriptions.Item label="负责人">{evaluation?.department_head}</Descriptions.Item>
          <Descriptions.Item label="分管领导">{evaluation?.evaluator_leader || '—'}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={si.color}>{si.label}</Tag></Descriptions.Item>
          <Descriptions.Item label="定编">{evaluation?.headcount || '—'}</Descriptions.Item>
          <Descriptions.Item label="自评时间">{evaluation?.self_submitted_at ? new Date(evaluation.self_submitted_at).toLocaleString() : '—'}</Descriptions.Item>
          <Descriptions.Item label="领导评分时间">{evaluation?.leader_submitted_at ? new Date(evaluation.leader_submitted_at).toLocaleString() : '—'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="考核项目评分" size="small" extra={
        <Space>
          {categoryScores.some((s: any) => s.scored_by) && <span className="text-xs text-gray-400">已评分项: {categoryScores.filter((s: any) => s.score != null).length}/{categoryScores.length}</span>}
          <Button icon={<SaveOutlined />} loading={saving} onClick={handleSaveCatScores} size="small">保存项目评分</Button>
        </Space>
      }>
        {categoryScores.length === 0 ? (
          <div className="text-center py-6 text-gray-400 text-sm">暂未配置考核项目，请先在「项目配置」中添加</div>
        ) : (
          <Table rowKey="category_id" dataSource={categoryScores} pagination={false} size="small" bordered
            columns={[
              { title: '考核项目', dataIndex: 'category_name', width: 140 },
              { title: '权重(%)', dataIndex: 'weight', width: 80, render: (v: number) => `${v}%` },
              { title: '得分', dataIndex: 'score', width: 90,
                render: (v: any, r: any) => <InputNumber size="small" value={v} min={0} max={100} placeholder="打分" onChange={(val) => updateCatScore(r.category_id, val)} style={{ width: '100%' }} />,
              },
              { title: '加权', width: 70, render: (_: any, r: any) => r.score != null ? <strong style={{ color: '#1677ff' }}>{(r.score * r.weight / 100).toFixed(1)}</strong> : '—' },
              { title: '评分人', dataIndex: 'scored_by', width: 80, render: (v: any) => v || '—' },
              { title: '评分时间', dataIndex: 'scored_at', width: 140, render: (v: any) => v ? new Date(v).toLocaleString() : '—' },
            ]}
            summary={() => {
              const total = categoryScores.reduce((s: number, r: any) => s + (r.score != null ? r.score * r.weight / 100 : 0), 0)
              return <Table.Summary.Row><Table.Summary.Cell index={0} colSpan={4}><strong>项目评分加权总分</strong></Table.Summary.Cell><Table.Summary.Cell index={1}><strong style={{ color: '#1677ff', fontSize: 16 }}>{total.toFixed(1)}</strong></Table.Summary.Cell></Table.Summary.Row>
            }}
          />
        )}
      </Card>

      <Card title="考核指标" extra={editable && <Space><Button icon={<PlusOutlined />} onClick={addItem}>添加</Button><Button icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button></Space>}>
        <Table rowKey="sort_order" dataSource={items.map((it: any, i: number) => ({ ...it, _i: i }))} pagination={false} size="small" bordered scroll={{ x: 1100 }}
          columns={[
            { title: '#', width: 40, render: (_: any, __: any, i: number) => i + 1 },
            { title: '类别', dataIndex: 'category', width: 110, render: (v: string, _: any, i: number) => editable ? <Select size="small" value={v} onChange={(val) => updateItem(i, 'category', val)} options={CATEGORY_OPTIONS} style={{ width: '100%' }} /> : CATEGORY_OPTIONS.find(o => o.value === v)?.label || v },
            { title: '考核指标', dataIndex: 'indicator', width: 180, render: (v: string, _: any, i: number) => editable ? <Input size="small" value={v} onChange={(e) => updateItem(i, 'indicator', e.target.value)} /> : <span>{v}</span> },
            { title: '标准/目标', dataIndex: 'standard', width: 160, render: (v: string, _: any, i: number) => editable ? <Input size="small" value={v || ''} onChange={(e) => updateItem(i, 'standard', e.target.value)} /> : <span>{v || '—'}</span> },
            { title: '权重%', dataIndex: 'weight', width: 70, render: (v: number, _: any, i: number) => editable ? <InputNumber size="small" value={v} min={0} max={100} onChange={(val) => updateItem(i, 'weight', val || 0)} style={{ width: '100%' }} /> : <span>{v}%</span> },
            { title: '自评分', dataIndex: 'self_score', width: 70, render: (v: number, _: any, i: number) => editable ? <InputNumber size="small" value={v} min={0} max={100} onChange={(val) => updateItem(i, 'self_score', val)} style={{ width: '100%' }} /> : <span>{v != null ? v : '—'}</span> },
            { title: '领导评分', dataIndex: 'leader_score', width: 80, render: (v: number, _: any, i: number) => <InputNumber size="small" value={v} min={0} max={100} onChange={(val) => updateItem(i, 'leader_score', val)} disabled={evaluation?.status === 'leader_scored'} style={{ width: '100%' }} /> },
            { title: '核定分', dataIndex: 'final_score', width: 70, render: (v: number) => <span style={{ fontWeight: 'bold', color: '#1677ff' }}>{v != null ? v : '—'}</span> },
            { title: '完成情况', dataIndex: 'completion', width: 160, render: (v: string, _: any, i: number) => editable ? <Input size="small" value={v || ''} onChange={(e) => updateItem(i, 'completion', e.target.value)} /> : <span>{v || '—'}</span> },
            ...(editable ? [{ title: '', width: 40, render: (_: any, r: any) => <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={() => setItems((p: any[]) => p.filter((_, j) => j !== r._i))} /> }] : []),
          ]}
          summary={() => (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0} colSpan={4}><strong>合计</strong></Table.Summary.Cell>
              <Table.Summary.Cell index={1}><strong>{totalWeight}%</strong></Table.Summary.Cell>
              <Table.Summary.Cell index={2}><strong>{totalSelf.toFixed(1)}</strong></Table.Summary.Cell>
              <Table.Summary.Cell index={3}><strong>{totalLeader.toFixed(1)}</strong></Table.Summary.Cell>
              <Table.Summary.Cell index={4}><strong>{totalLeader.toFixed(1)}</strong></Table.Summary.Cell>
              <Table.Summary.Cell index={5} />
              {editable && <Table.Summary.Cell index={6} />}
            </Table.Summary.Row>
          )}
        />
        <Divider />
        <div className="flex justify-between items-center">
          <div>
            <p>权重合计：<span style={{ color: totalWeight === 100 ? 'green' : 'red' }}>{totalWeight}%{totalWeight === 100 ? ' ✓' : ' ⚠'}</span></p>
            <p>自评加权：{totalSelf.toFixed(1)} 分　领导加权：{totalLeader.toFixed(1)} 分</p>
          </div>
          <Space>
            {editable && <Popconfirm title="提交后不可修改自评，确认？" onConfirm={handleSubmitSelf}><Button type="primary" icon={<SendOutlined />} loading={submitting}>提交自评</Button></Popconfirm>}
            {(evaluation?.status === 'draft' || evaluation?.status === 'self_submitted') && (
              <Popconfirm title="确认提交领导评分？" onConfirm={handleSubmitLeader}><Button type="primary" icon={<SendOutlined />} loading={submitting} style={{ background: '#52c41a' }}>提交领导评分</Button></Popconfirm>
            )}
            {!editable && evaluation?.status !== 'leader_scored' && <Button icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>}
          </Space>
        </div>
      </Card>
    </div>
  )
}
