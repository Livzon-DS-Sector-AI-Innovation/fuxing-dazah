'use client'

import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  Input,
  Tag,
  InputNumber,
  DatePicker,
  Select,
  Spin,
  message,
  Space,
  Popconfirm,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  SaveOutlined,
  EditOutlined,
  ArrowLeftOutlined,
  DownloadOutlined,
  SendOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import Link from 'next/link'
import { AnnualTrainingPlan, AnnualTrainingPlanItem } from '@/types/hr'
import { fetchPlanItems, API_BASE } from '@/lib/api/hr'
import { batchUpdatePlanItems } from '@/actions/hr'

interface AnnualPlanDetailClientProps {
  planId: string
  plan: AnnualTrainingPlan | null
}

const MONTH_OPTIONS = Array.from({length:12}, (_,i) => `${i+1}月`)

export default function AnnualPlanDetailClient({
  planId,
  plan,
}: AnnualPlanDetailClientProps) {
  const [items, setItems] = useState<AnnualTrainingPlanItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<AnnualTrainingPlanItem>>({})
  const [deptList, setDeptList] = useState<string[]>([])
  const [trainerList, setTrainerList] = useState<string[]>([])

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/departments?page_size=100`).then(r => r.json())
      .then(d => setDeptList((d.data||[]).map((x:any) => x.name)))
    fetch(`${API_BASE}/api/v1/hr/trainers?page_size=200`).then(r => r.json())
      .then(d => setTrainerList((d.data||[]).map((x:any) => x.name)))
  }, [])

  const loadItems = async () => {
    setLoading(true)
    try {
      const res = await fetchPlanItems(planId)
      const sorted = (res.data || []).sort((a: any, b: any) => {
        // 已完成的排最底下
        if (a.tracking_status === '完成' && b.tracking_status !== '完成') return 1
        if (a.tracking_status !== '完成' && b.tracking_status === '完成') return -1
        // 未完成的按月份排序
        const ma = parseInt((a.month || '0').replace(/[^0-9]/g, '')) || 13
        const mb = parseInt((b.month || '0').replace(/[^0-9]/g, '')) || 13
        return ma - mb
      })
      setItems(sorted)
    } catch (err: any) {
      message.error('加载明细失败: ' + (err.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadItems()
  }, [planId])

  const handleExport = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${planId}/export`)
      if (!res.ok) throw new Error('导出失败')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const contentDisposition = res.headers.get('content-disposition')
      const filename = contentDisposition?.match(/filename\*?=utf-8''(.+)/)?.[1] || contentDisposition?.match(/filename="(.+)"/)?.[1] || '年度培训计划.xlsx'
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    }
  }

  const handleAdd = () => {
    const newItem: AnnualTrainingPlanItem = {
      id: `new-${Date.now()}`,
      plan_id: planId,
      month: '',
      trainee_count: undefined,
      duration_hours: undefined,
      content_and_textbook: '',
      target_audience: '',
      position_and_count: '',
      training_method: '',
      training_hours: undefined,
      confirmer: '',
      confirm_date: '',
      remarks: '',
      tracking_status: '',
      sort_order: items.length,
    }
    setItems([...items, newItem])
    setEditingId(newItem.id)
    setEditForm(newItem)
  }

  const handleEdit = (item: AnnualTrainingPlanItem) => {
    setEditingId(item.id)
    setEditForm({ ...item })
  }

  const handleCancel = () => {
    setEditingId(null)
    setEditForm({})
    setItems((prev) => prev.filter((i) => !i.id.startsWith('new-')))
  }

  const handleSaveAll = async () => {
    if (items.length === 0) {
      message.warning('请先添加明细')
      return
    }

    const payloadItems = items.map((item) => ({
      month: item.month || undefined,
      trainee_count: item.trainee_count || undefined,
      duration_hours: item.duration_hours || undefined,
      content_and_textbook: item.content_and_textbook || undefined,
      target_audience: item.target_audience || undefined,
      position_and_count: item.position_and_count || undefined,
      training_method: item.training_method || undefined,
      training_hours: item.training_hours || undefined,
      confirmer: item.confirmer || undefined,
      confirm_date: item.confirm_date || undefined,
      remarks: item.remarks || undefined,
      tracking_status: item.tracking_status || undefined,
      sort_order: item.sort_order,
    }))

    setSaving(true)
    try {
      await batchUpdatePlanItems(planId, { items: payloadItems as any })
      message.success('保存成功')
      setEditingId(null)
      setEditForm({})
      await loadItems()
    } catch (err: any) {
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (item: AnnualTrainingPlanItem) => {
    if (item.id.startsWith('new-')) {
      setItems((prev) => prev.filter((i) => i.id !== item.id))
      setEditingId(null)
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${planId}/items/${item.id}`, { method: 'DELETE', credentials: 'include' })
      if (!res.ok) throw new Error('删除失败')
      setItems((prev) => prev.filter((i) => i.id !== item.id))
      message.success('已删除')
    } catch { message.error('删除失败') }
  }

  const updateField = (field: keyof AnnualTrainingPlanItem, value: any) => {
    setEditForm((prev) => ({ ...prev, [field]: value }))
    if (editingId) {
      setItems((prev) =>
        prev.map((i) => (i.id === editingId ? { ...i, [field]: value } : i))
      )
    }
  }

  const isEditing = (item: AnnualTrainingPlanItem) => editingId === item.id

  // Pad to at least 12 visible rows
  const displayRows = [...items]
  while (displayRows.length < 12) {
    displayRows.push({
      id: `blank-${displayRows.length}`,
      plan_id: planId,
      sort_order: displayRows.length,
    } as AnnualTrainingPlanItem)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin size="large" description="加载中..." />
      </div>
    )
  }

  if (!plan) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <p>未找到该年度计划</p>
        <Link href="/hr/training/annual-plan">
          <Button type="link">返回列表</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 控制栏 */}
      <div className="flex flex-wrap items-center gap-4 no-print">
        <Link href="/hr/training/annual-plan">
          <Button icon={<ArrowLeftOutlined />}>返回</Button>
        </Link>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleAdd}
          disabled={!!editingId}
        >
          添加行
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={handleSaveAll}
        >
          保存全部
        </Button>
        <Button
          icon={<DownloadOutlined />}
          onClick={handleExport}
        >
          导出年度培训计划
        </Button>
        {editingId && (
          <Button onClick={handleCancel}>取消编辑</Button>
        )}
      </div>

      <div id="print-area" className="print-area">
        <Card bordered={false} className="annual-plan-preview">
          <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm" style={{ tableLayout: 'fixed', minWidth: '1800px' }}>
            <colgroup>
              <col style={{ width: '50px' }} />
              <col style={{ width: '150px' }} />
              <col style={{ width: '400px' }} />
              <col style={{ width: '220px' }} />
              <col style={{ width: '200px' }} />
              <col style={{ width: '100px' }} />
              <col style={{ width: '100px' }} />
              <col style={{ width: '150px' }} />
              <col style={{ width: '80px' }} />
              <col style={{ width: '180px' }} />
              <col style={{ width: '100px' }} />
            </colgroup>
            <tbody>
              {/* 第1行: 标题 */}
              <tr>
                <td
                  colSpan={10}
                  className="text-center text-lg font-bold border border-gray-300 py-2"
                >
                  {plan.year} 年培训计划
                </td>
              </tr>
              {/* 第2行: 部门 */}
              <tr>
                <td
                  colSpan={10}
                  className="text-left text-sm font-semibold border border-gray-300 px-3 py-1"
                >
                  部门：{plan.department}
                </td>
              </tr>
              {/* 表头 */}
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  序号
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训季度及课时
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训内容及使用教材
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训对象
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  授课单位及授课人
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  考核方式
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训跟踪
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  确认人/日期
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  状态
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  备注
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center no-print">
                  操作
                </td>
              </tr>
              {/* 数据行 */}
              {displayRows.map((item, idx) => {
                const editing = isEditing(item)
                const isBlank = item.id.startsWith('blank-')
                return (
                  <tr key={item.id} style={{ background: item.tracking_status === '完成' ? '#f6ffed' : 'transparent' }}>
                    <td className="border border-gray-300 px-2 py-2 text-center align-top" style={{ lineHeight: '1.6' }}>
                      <span>{idx + 1}</span>
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <div className="space-y-1">
                          <select
                            className="w-full text-sm border rounded px-2 py-1"
                            value={editForm.month || ''}
                            onChange={(e) => updateField('month', e.target.value)}
                          >
                            <option value="">请选择</option>
                            {MONTH_OPTIONS.map((m) => ( <option key={m} value={m}>{m}</option> ))}
                          </select>
                          <InputNumber
                            size="small"
                            className="w-full"
                            min={0}
                            step={0.5}
                            placeholder="课时"
                            value={editForm.duration_hours ?? undefined}
                            onChange={(val) => updateField('duration_hours', val)}
                          />
                        </div>
                      ) : (
                        <span>
                          {item.month || ''}
                          {item.month && item.duration_hours ? ' ' : ''}
                          {item.duration_hours ? `${item.duration_hours}课时` : ''}
                        </span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.content_and_textbook || ''}
                          onChange={(e) => updateField('content_and_textbook', e.target.value)}
                        />
                      ) : (
                        <span>{item.content_and_textbook || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <Select mode="tags" size="small" style={{ width: '100%' }} placeholder="选部门或输入"
                          value={editForm.target_audience ? editForm.target_audience.split(/[,，、\s]+/).filter(Boolean) : []}
                          onChange={(vals) => updateField('target_audience', vals.join('、'))}
                          options={deptList.map(d => ({value:d,label:d}))} />
                      ) : (
                        <span>{item.target_audience || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <Select mode="tags" size="small" style={{ width: '100%' }} placeholder="选培训师或输入"
                          value={editForm.position_and_count ? editForm.position_and_count.split(/[,，、\s]+/).filter(Boolean) : []}
                          onChange={(vals) => updateField('position_and_count', vals.join('、'))}
                          options={trainerList.map(t => ({value:t,label:t}))} />
                      ) : (
                        <span className="whitespace-pre-wrap">{item.position_and_count || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <Select size="small" style={{ width: '100%' }} placeholder="选择"
                          value={editForm.training_method || undefined}
                          onChange={(v) => updateField('training_method', v)}
                          options={[{value:'面授',label:'面授'},{value:'自学',label:'自学'},{value:'自学+面授',label:'自学+面授'}]} />
                      ) : (
                        <span>{item.training_method || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top text-center" style={{ lineHeight: '1.6' }}>
                      {editing ? (
                        <select
                          className="w-full text-sm border rounded px-2 py-1"
                          value={editForm.tracking_status || ''}
                          onChange={(e) => updateField('tracking_status', e.target.value)}
                        >
                          <option value="">请选择</option>
                          <option value="完成">完成</option>
                          <option value="未完成">未完成</option>
                        </select>
                      ) : (
                        <span>{item.tracking_status === '完成'
                          ? <Tag color="green">✓ 完成</Tag>
                          : item.tracking_status === '未完成'
                          ? <Tag color="red">✗ 未完成</Tag>
                          : <Tag color="default">—</Tag>}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <div className="space-y-1">
                          <Select size="small" style={{ width: '100%' }} placeholder="选确认人" allowClear showSearch
                            value={editForm.confirmer || undefined}
                            onChange={(v) => updateField('confirmer', v)}
                            options={trainerList.map(t => ({value:t,label:t}))}
                            filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                          <DatePicker
                            size="small"
                            className="w-full"
                            placeholder="日期"
                            value={editForm.confirm_date ? dayjs(editForm.confirm_date) : null}
                            onChange={(d) => updateField('confirm_date', d ? d.format('YYYY-MM-DD') : '')}
                          />
                        </div>
                      ) : (
                        <span>
                          {item.confirmer || ''}
                          {item.confirmer && item.confirm_date ? ' / ' : ''}
                          {item.confirm_date || ''}
                        </span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top text-center" style={{ lineHeight: '1.6' }}>
                      {(() => {
                        const s = (item as any).training_status || '—'
                        const colors: Record<string, string> = {'已评估': '#52c41a', '已通知': '#1677ff', '未开始': '#999'}
                        return <span style={{ color: colors[s] || '#999', fontWeight: 500, fontSize: 12 }}>{s}</span>
                      })()}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 align-top" style={{ wordBreak: 'break-word', lineHeight: '1.6' }}>
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.remarks || ''}
                          onChange={(e) => updateField('remarks', e.target.value)}
                        />
                      ) : (
                        <span>{item.remarks || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-2 py-2 text-center align-top no-print">
                      {isBlank ? null : editing ? (
                        <Space size="small" orientation="vertical" className="w-full">
                          <Button
                            size="small"
                            onClick={handleCancel}
                          >
                            取消
                          </Button>
                        </Space>
                      ) : (
                        <Space size="small" orientation="vertical" className="w-full">
                          <Button
                            size="small"
                            type="primary"
                            icon={<SendOutlined />}
                            onClick={() => {
                              const params = new URLSearchParams()
                              params.set('subject', item.content_and_textbook || '')
                              params.set('method', item.training_method || '')
                              params.set('dept', plan?.department || '')
                              params.set('assessment', item.training_method || '')
                              window.open(`/hr/training/notification?${params.toString()}`, '_blank')
                            }}
                          />
                          <Button
                            size="small"
                            icon={<EditOutlined />}
                            onClick={() => handleEdit(item)}
                          />
                          <Popconfirm
                            title="确认删除？"
                            onConfirm={() => handleDelete(item)}
                          >
                            <Button
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                            />
                          </Popconfirm>
                        </Space>
                      )}
                    </td>
                  </tr>
                )
              })}
              {/* 底部签名行 */}
              <tr>
                <td colSpan={5} className="border border-gray-300 px-3 py-3 text-sm">
                  制表人/日期：
                </td>
                <td colSpan={5} className="border border-gray-300 px-3 py-3 text-sm">
                  部门负责人/日期：
                </td>
              </tr>
            </tbody>
          </table>
          </div>
        </Card>
      </div>

      <style jsx global>{`
        @media print {
          body * {
            visibility: hidden;
          }
          #print-area,
          #print-area * {
            visibility: visible;
          }
          #print-area {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
          }
          .no-print {
            display: none !important;
          }
          .ant-card {
            border: none !important;
            box-shadow: none !important;
          }
          .ant-card-body {
            padding: 0 !important;
          }
        }
      `}</style>
    </div>
  )
}
