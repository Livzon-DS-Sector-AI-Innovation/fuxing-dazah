'use client'

import { useEffect, useState } from 'react'
import { Button, Card, DatePicker, InputNumber, Space, Table, message } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { fetchPerformanceEvaluations, fetchPerformanceCategories, fetchCategoryScores, saveCategoryScores } from '@/actions/hr'

export default function PerformanceCategoryScoreClient({ initialMonth }: { initialMonth?: string }) {
  const [month, setMonth] = useState(initialMonth || dayjs().format('YYYY-MM'))
  const [evaluations, setEvaluations] = useState<any[]>([])
  const [categories, setCategories] = useState<any[]>([])
  const [scores, setScores] = useState<Record<string, Record<string, { score: number | null; weight: number }>>>({})
  const [catEditable, setCatEditable] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      const [catsRes, evalsRes] = await Promise.all([
        fetchPerformanceCategories(),
        fetchPerformanceEvaluations({ month, page_size: 100 }),
      ])
      const cats = (catsRes.data || []).filter((c: any) => c.is_active)
      setCategories(cats)
      const evals = (evalsRes.data?.items || [])
      setEvaluations(evals)
      // 加载所有考核的评分 + 各项目是否可编辑（负责人校验由后端返回）
      const scoreMap: Record<string, Record<string, { score: number | null; weight: number }>> = {}
      const editableMap: Record<string, boolean> = {}
      for (const ev of evals) {
        const sRes = await fetchCategoryScores(ev.id)
        const entry: Record<string, { score: number | null; weight: number }> = {}
        for (const s of sRes.data || []) {
          entry[s.category_id] = { score: s.score, weight: s.weight || (cats.find((c: any) => c.id === s.category_id)?.weight || 0) }
          editableMap[s.category_id] = s.can_edit !== false
        }
        scoreMap[ev.id] = entry
      }
      setScores(scoreMap)
      setCatEditable(editableMap)
    } catch (e: any) { message.error('加载失败: ' + (e?.message || String(e))) }
  }
  useEffect(() => { load() }, [month])

  const handleScore = (evalId: string, catId: string, val: number | null) => {
    setScores(prev => {
      const cur = prev[evalId]?.[catId] || { score: null, weight: 0 }
      return { ...prev, [evalId]: { ...(prev[evalId] || {}), [catId]: { ...cur, score: val } } }
    })
  }
  const handleWeight = (evalId: string, catId: string, val: number) => {
    setScores(prev => {
      const cur = prev[evalId]?.[catId] || { score: null, weight: 0 }
      return { ...prev, [evalId]: { ...(prev[evalId] || {}), [catId]: { ...cur, weight: val } } }
    })
  }

  const handleSave = async (evalId: string) => {
    setSaving(true)
    try {
      const batch = categories
        .filter(c => catEditable[c.id] !== false)
        .map(c => ({
          evaluation_id: evalId,
          category_id: c.id,
          score: scores[evalId]?.[c.id]?.score ?? null,
          weight: scores[evalId]?.[c.id]?.weight ?? c.weight,
        }))
      await saveCategoryScores(evalId, batch)
      message.success('已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  // 用于表格的列定义：部门 + 各考核项目列（非负责人项目禁用输入）
  const catCols = categories.map(c => {
    const editable = catEditable[c.id] !== false
    return {
      title: editable ? c.name : `${c.name}（${(c as any).evaluator || '非负责人'}）`,
      dataIndex: c.id, key: c.id, width: 170,
      render: (_: any, record: any) => {
        const v = scores[record.id]?.[c.id]
        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <InputNumber size="small" min={0} max={100} placeholder="分数"
              value={v?.score ?? null} disabled={!editable}
              onChange={(val) => handleScore(record.id, c.id, val)}
              style={{ width: '100%' }}
            />
            <InputNumber size="small" min={0} max={100} placeholder="权重%"
              value={v?.weight ?? c.weight} disabled
              style={{ width: '100%' }}
              addonAfter="%"
            />
          </Space>
        )
      },
    }
  })

  const columns = [
    { title: '部门', dataIndex: 'department', width: 150, fixed: 'left' as const },
    { title: '负责人', dataIndex: 'department_head', width: 100 },
    ...catCols,
    {
      title: '操作', width: 80, fixed: 'right' as const,
      render: (_: any, record: any) => <Button size="small" icon={<SaveOutlined />} loading={saving} onClick={() => handleSave(record.id)}>保存</Button>,
    },
  ]

  return (
    <Card title="考核项目评分" extra={
      <Space>
        <span>考核月份：</span>
        <DatePicker picker="month" value={dayjs(month)} onChange={(d) => d && setMonth(d.format('YYYY-MM'))} />
        <Button onClick={load}>刷新</Button>
      </Space>
    }>
      {categories.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <p>暂无考核项目配置，请先在「考核项目配置」中添加项目（环保/安全/质量/人才/生产/综合等）</p>
        </div>
      ) : (
        <Table rowKey="id" dataSource={evaluations} columns={columns} pagination={false} scroll={{ x: 200 + categories.length * 120 }} bordered size="small" />
      )}
    </Card>
  )
}
