'use client'

import { useState, useEffect } from 'react'
import { Card, Form, Input, InputNumber, Select, Button, message, Alert } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import EvaluationPreview from '@/components/hr/EvaluationPreview'

const METHODS = [{v:'面授',l:'面授'},{v:'自学',l:'自学'},{v:'自学+面授',l:'自学+面授'}]
const ASSESSMENT = [{v:'笔试',l:'笔试'},{v:'问答',l:'问答'}]

export default function EvaluationFormPage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [pendingList, setPendingList] = useState<any[]>([])
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/training-evaluations/pending`).then(r => r.json())
      .then(res => setPendingList(res.data || []))
  }, [])

  const handleSelect = (id: string) => {
    const item = pendingList.find(p => p.id === id)
    if (!item) return
    form.setFieldsValue({
      subject: item.content || '',
      training_method: item.method || undefined,
      trainee_names: item.audience || '',
      assessment_method: item.remarks?.match(/考核方式:(\S+)/)?.[1] || undefined,
      expected_count: item.expected_count || 0,
      actual_count: item.expected_count || 0,
      exam_count: item.expected_count || 0,
    })
    message.success(`已加载：${item.content?.substring(0,40)}（应到${item.expected_count}人）`)
  }

  const handleGenerate = async () => {
    const vals = await form.validateFields()
    setLoading(true)
    try {
      const payload = {
        subject: vals.subject,
        training_date: vals.training_date?.format('YYYY-MM-DD'),
        training_method: vals.training_method,
        trainer: vals.trainer,
        trainee_names: (vals.trainee_names || '').split(/[,，、\s]+/).filter(Boolean),
        assessment_method: vals.assessment_method,
        expected_count: vals.expected_count, actual_count: vals.actual_count,
        sick_leave: vals.sick_leave||0, personal_leave: vals.personal_leave||0,
        maternity_leave: vals.maternity_leave||0,
        absent_count: (vals.sick_leave||0)+(vals.personal_leave||0)+(vals.maternity_leave||0),
        exam_count: vals.exam_count||vals.actual_count,
        excellent_count: vals.excellent_count, qualified_count: vals.qualified_count,
        unqualified_count: vals.unqualified_count,
      }
      const res = await fetch(`${API_BASE}/api/v1/hr/training-evaluation`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error('生成失败')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url
      a.download = `培训效果评估表_${payload.training_date||'nodate'}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
      message.success('评估表已生成，台账已更新')
      // 刷新待评估列表
      fetch(`${API_BASE}/api/v1/hr/training-evaluations/pending`).then(r => r.json())
        .then(res => setPendingList(res.data || []))
    } catch (err: any) { message.error(err.message || '生成失败') }
    finally { setLoading(false) }
  }

  const C = { border:'1px solid #ccc', padding:'6px 10px', fontSize:13 } as const
  const H = { ...C, background:'#f5f5f5', fontWeight:600, textAlign:'center' as const }

  return (
    <div className="space-y-4 max-w-5xl">
      <h1 className="text-[22px] font-semibold">培训效果评估表</h1>

      {pendingList.length > 0 && (
        <Alert type="info" showIcon message={`${pendingList.length} 条培训待评估，选择后自动填表`} />
      )}

      <Card size="small" title="从年度计划选择（自动填表）">
        <Select showSearch placeholder="搜索培训内容..." allowClear
          filterOption={(input, option) => (option?.label as string||'').toLowerCase().includes(input.toLowerCase())}
          options={pendingList.map(p => ({value:p.id, label:`[${p.department}] ${p.content?.substring(0,60)}`}))}
          onChange={handleSelect} style={{ width:'100%' }} />
      </Card>

      <Form form={form} layout="vertical">
        {/* 基本信息行：匹配模板 Row 0-3 */}
        <Card size="small" title="培训基本信息">
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'0 24px' }}>
            <Form.Item name="subject" label="培训内容" rules={[{required:true}]}><Input /></Form.Item>
            <Form.Item name="training_date" label="培训日期" rules={[{required:true}]}><Input placeholder="如 2026-06-25" /></Form.Item>
            <Form.Item name="training_method" label="培训方式"><Select options={METHODS.map(m=>({value:m.v,label:m.l}))} /></Form.Item>
            <Form.Item name="trainer" label="培训师"><Input /></Form.Item>
            <Form.Item name="trainee_names" label="培训对象"><Input.TextArea rows={2} placeholder="部门/班组/人员，逗号分隔" /></Form.Item>
            <Form.Item name="assessment_method" label="考核方式"><Select options={ASSESSMENT.map(a=>({value:a.v,label:a.l}))} /></Form.Item>
          </div>
        </Card>

        {/* 人数统计行：匹配模板 Row 5-8 */}
        <Card size="small" title="培训人数统计">
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'0 16px' }}>
            <Form.Item name="expected_count" label="应到人数"><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="actual_count" label="实到人数"><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="exam_count" label="参加考核人数"><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="sick_leave" label="病假" initialValue={0}><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="personal_leave" label="事假" initialValue={0}><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="maternity_leave" label="产假" initialValue={0}><InputNumber min={0} className="w-full" /></Form.Item>
          </div>
        </Card>

        {/* 考核结果：匹配模板 Row 11 */}
        <Card size="small" title="考核结果">
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'0 16px' }}>
            <Form.Item name="excellent_count" label="优秀（≥90）"><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="qualified_count" label="合格（≥80且＜90）"><InputNumber min={0} className="w-full" /></Form.Item>
            <Form.Item name="unqualified_count" label="不合格（＜80）"><InputNumber min={0} className="w-full" /></Form.Item>
          </div>
        </Card>

        <Button type="primary" size="large" icon={<DownloadOutlined />} onClick={handleGenerate} loading={loading}>
          生成培训效果评估表
        </Button>
      </Form>

      {/* 实时预览 */}
      <Card title="📋 培训效果评估表预览" className="mt-4 print:break-before-page">
        <EvaluationPreview
          topicStr={form.getFieldValue('subject') || ''}
          dateStr={form.getFieldValue('training_date') || ''}
          trainingMethodValue={form.getFieldValue('training_method') || ''}
          trainerValue={form.getFieldValue('trainer') || ''}
          assessmentMethodValue={form.getFieldValue('assessment_method') || ''}
          deptValue=""
          traineeDepts={[]}
          previewNames={Array(form.getFieldValue('expected_count') || 0).fill({})}
          evalDurationHours=""
        />
      </Card>
    </div>
  )
}
