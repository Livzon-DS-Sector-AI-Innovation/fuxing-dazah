'use client'

import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  Input,
  InputNumber,
  DatePicker,
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
} from '@ant-design/icons'
import dayjs from 'dayjs'
import Link from 'next/link'
import { AnnualTrainingPlan, AnnualTrainingPlanItem } from '@/types/hr'
import { fetchPlanItems } from '@/lib/api/hr'
import { batchUpdatePlanItems } from '@/actions/hr'

interface AnnualPlanDetailClientProps {
  planId: string
  plan: AnnualTrainingPlan | null
}

const QUARTER_OPTIONS = [
  '第一季度', '第二季度', '第三季度', '第四季度',
]

export default function AnnualPlanDetailClient({
  planId,
  plan,
}: AnnualPlanDetailClientProps) {
  const [items, setItems] = useState<AnnualTrainingPlanItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<AnnualTrainingPlanItem>>({})

  const loadItems = async () => {
    setLoading(true)
    try {
      const res = await fetchPlanItems(planId)
      setItems(res.data || [])
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
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000'}/api/v1/hr/annual-training-plans/${planId}/export`)
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

  const handleDelete = (item: AnnualTrainingPlanItem) => {
    if (item.id.startsWith('new-')) {
      setItems((prev) => prev.filter((i) => i.id !== item.id))
      setEditingId(null)
      return
    }
    setItems((prev) => prev.filter((i) => i.id !== item.id))
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
        <Spin size="large" tip="加载中..." />
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
          <table className="w-full border-collapse text-sm" style={{ tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '5%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '24%' }} />
              <col style={{ width: '12%' }} />
              <col style={{ width: '12%' }} />
              <col style={{ width: '8%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '9%' }} />
              <col style={{ width: '4%' }} />
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
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  序号
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  培训季度及课时
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  培训内容及使用教材
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  培训对象
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  授课单位及授课人
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  考核方式
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  培训跟踪
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  确认人/日期
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center">
                  备注
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-1 py-2 text-center no-print">
                  操作
                </td>
              </tr>
              {/* 数据行 */}
              {displayRows.map((item, idx) => {
                const editing = isEditing(item)
                const isBlank = item.id.startsWith('blank-')
                return (
                  <tr key={item.id}>
                    <td className="border border-gray-300 px-1 py-1 text-center align-top">
                      <span className="px-1">{idx + 1}</span>
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <div className="space-y-1">
                          <select
                            className="w-full text-xs border rounded px-1 py-0.5"
                            value={editForm.month || ''}
                            onChange={(e) => updateField('month', e.target.value)}
                          >
                            <option value="">请选择</option>
                            {['第一季度','第二季度','第三季度','第四季度'].map((m) => (
                              <option key={m} value={m}>{m}</option>
                            ))}
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
                        <span className="px-1">
                          {item.month || ''}
                          {item.month && item.duration_hours ? ' ' : ''}
                          {item.duration_hours ? `${item.duration_hours}课时` : ''}
                        </span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.content_and_textbook || ''}
                          onChange={(e) => updateField('content_and_textbook', e.target.value)}
                        />
                      ) : (
                        <span className="px-1">{item.content_and_textbook || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.target_audience || ''}
                          onChange={(e) => updateField('target_audience', e.target.value)}
                        />
                      ) : (
                        <span className="px-1">{item.target_audience || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.position_and_count || ''}
                          onChange={(e) => updateField('position_and_count', e.target.value)}
                        />
                      ) : (
                        <span className="px-1">{item.position_and_count || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.training_method || ''}
                          onChange={(e) => updateField('training_method', e.target.value)}
                        />
                      ) : (
                        <span className="px-1">{item.training_method || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <select
                          className="w-full text-xs border rounded px-1 py-0.5"
                          value={editForm.tracking_status || ''}
                          onChange={(e) => updateField('tracking_status', e.target.value)}
                        >
                          <option value="">请选择</option>
                          <option value="完成">完成</option>
                          <option value="未完成">未完成</option>
                        </select>
                      ) : (
                        <span className="px-1">{item.tracking_status ? `□${item.tracking_status}` : ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <div className="space-y-1">
                          <Input
                            size="small"
                            placeholder="确认人"
                            value={editForm.confirmer || ''}
                            onChange={(e) => updateField('confirmer', e.target.value)}
                          />
                          <DatePicker
                            size="small"
                            className="w-full"
                            placeholder="日期"
                            value={editForm.confirm_date ? dayjs(editForm.confirm_date) : null}
                            onChange={(d) => updateField('confirm_date', d ? d.format('YYYY-MM-DD') : '')}
                          />
                        </div>
                      ) : (
                        <span className="px-1">
                          {item.confirmer || ''}
                          {item.confirmer && item.confirm_date ? ' / ' : ''}
                          {item.confirm_date || ''}
                        </span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 align-top">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.remarks || ''}
                          onChange={(e) => updateField('remarks', e.target.value)}
                        />
                      ) : (
                        <span className="px-1">{item.remarks || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 text-center align-top no-print">
                      {isBlank ? null : editing ? (
                        <Space size="small" direction="vertical" className="w-full">
                          <Button
                            size="small"
                            onClick={handleCancel}
                          >
                            取消
                          </Button>
                        </Space>
                      ) : (
                        <Space size="small" direction="vertical" className="w-full">
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
