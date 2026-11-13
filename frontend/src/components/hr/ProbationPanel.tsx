'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Badge, Button, Card, Descriptions, Drawer, Empty, Form, Modal, Select, Spin, Tabs, Tag } from 'antd'
import { AuditOutlined, CheckOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import {
  cancelProbationReview, createProbationReview, fetchProbationReviews, finalizeProbationReview,
} from '@/actions/hr'
import { fetchEmployeesAction } from '@/actions/hr'
import type { ProbationReviewItem } from '@/types/hr'

const STATUS_META: Record<string, { label: string; color: string }> = {
  pending_reviewer: { label: '待负责人评估', color: 'processing' },
  pending_hr: { label: '待HR确认', color: 'orange' },
  effective: { label: '已生效', color: 'success' },
  cancelled: { label: '已取消', color: 'default' },
}

const CONCLUSION_COLOR: Record<string, string> = { 通过: 'green', 延长: 'orange', 不通过: 'red' }

/** 转正管理面板：入口按钮 + Drawer（发起评估 / 待确认 / 记录） */
export default function ProbationPanel() {
  const { message: msg, modal } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:profile:update')

  const [items, setItems] = useState<ProbationReviewItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('pending')
  const [panelOpen, setPanelOpen] = useState(false)

  // 发起
  const [sendOpen, setSendOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [empOptions, setEmpOptions] = useState<{ value: string; label: string }[]>([])
  const [empSearching, setEmpSearching] = useState(false)
  const [reviewerOptions, setReviewerOptions] = useState<{ value: string; label: string }[]>([])
  const [reviewerSearching, setReviewerSearching] = useState(false)
  const [sendForm] = Form.useForm()
  const empSeq = useRef(0)
  const revSeq = useRef(0)

  // 确认
  const [finalizeTarget, setFinalizeTarget] = useState<ProbationReviewItem | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetchProbationReviews()
      setItems(r.data || [])
    } catch { setItems([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchProbationReviews()
        if (!cancelled) setItems(r.data || [])
      } catch {
        if (!cancelled) setItems([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const searchEmployees = async (keyword: string) => {
    const seq = ++empSeq.current
    setEmpSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '试用期', keyword, page: 1, page_size: 20 })
      if (seq !== empSeq.current) return
      const raw = (d as { data?: { items?: unknown[] } | unknown[] })?.data
      const list = (Array.isArray(raw) ? raw : (raw as { items?: unknown[] })?.items || []) as Array<{
        id: string; name: string; employee_number?: string; department?: string
      }>
      setEmpOptions(list.map(e => ({
        value: e.id,
        label: `${e.name}（${e.employee_number || ''} · ${e.department || '-'}）`,
      })))
    } catch { /* 静默 */ }
    finally { if (seq === empSeq.current) setEmpSearching(false) }
  }

  const searchReviewers = async (keyword: string) => {
    const seq = ++revSeq.current
    setReviewerSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== revSeq.current) return
      const raw = (d as { data?: { items?: unknown[] } | unknown[] })?.data
      const list = (Array.isArray(raw) ? raw : (raw as { items?: unknown[] })?.items || []) as Array<{
        name: string; employee_number?: string; department?: string
      }>
      setReviewerOptions(list.map(e => ({
        value: e.name,
        label: `${e.name}（${e.employee_number || ''} · ${e.department || '-'}）`,
      })))
    } catch { /* 静默 */ }
    finally { if (seq === revSeq.current) setReviewerSearching(false) }
  }

  const handleSend = async () => {
    const v = await sendForm.validateFields()
    setSending(true)
    try {
      const r = await createProbationReview(v.employee_id, v.reviewer_name)
      msg.success(r.message || '评估卡片已发送')
      setSendOpen(false); sendForm.resetFields(); load()
    } catch (e) { msg.error(e instanceof Error ? e.message : '发起失败') }
    finally { setSending(false) }
  }

  const handleFinalize = (item: ProbationReviewItem) => {
    modal.confirm({
      title: `确认${item.conclusion === '通过' ? '转正生效' : item.conclusion === '延长' ? '延长试用期' : '不通过'} — ${item.employee_name}？`,
      content: item.conclusion === '通过'
        ? '将写入源表「员工性质=正式」，员工状态转为在职（下轮同步口径一致）。'
        : item.conclusion === '延长'
          ? `试用期将延长至 ${item.proposed_probation_end}，到期后需重新发起评估。`
          : '不改动员工状态，请按需走离职流程。',
      okText: '确认',
      onOk: async () => {
        try {
          const r = await finalizeProbationReview(item.id, item.hr_note || undefined)
          msg.success(r.message || '已确认')
          load()
        } catch (e) { msg.error(e instanceof Error ? e.message : '确认失败') }
      },
    })
  }

  const handleCancel = async (item: ProbationReviewItem) => {
    try {
      const r = await cancelProbationReview(item.id)
      msg.success(r.message || '已取消')
      load()
    } catch (e) { msg.error(e instanceof Error ? e.message : '取消失败') }
  }

  const pending = items.filter(i => i.status === 'pending_reviewer' || i.status === 'pending_hr')
  const effective = items.filter(i => i.status === 'effective' || i.status === 'cancelled')

  const renderItem = (item: ProbationReviewItem) => {
    const meta = STATUS_META[item.status]
    return (
      <Card key={item.id} size="small">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap min-w-0">
            <b className="text-sm">{item.employee_name}</b>
            <span className="text-xs text-gray-400">{item.employee_number}</span>
            <span className="text-xs text-gray-500 truncate">{item.department} · {item.position}</span>
            <Tag color={meta.color} style={{ fontSize: 10, margin: 0 }}>{meta.label}</Tag>
            {item.conclusion && (
              <Tag color={CONCLUSION_COLOR[item.conclusion]} style={{ fontSize: 10, margin: 0 }}>{item.conclusion}</Tag>
            )}
            <span className="text-xs text-gray-400">评估人：{item.reviewer_name}</span>
            {item.days_left != null && item.status !== 'effective' && (
              <span className={`text-xs ${item.days_left < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                {item.days_left < 0 ? `已过期 ${Math.abs(item.days_left)} 天` : `${item.days_left} 天后到期`}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {item.status === 'pending_hr' && canManage && (
              <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleFinalize(item)}>
                确认{item.conclusion === '通过' ? '转正' : item.conclusion === '延长' ? '延长' : '结果'}
              </Button>
            )}
            {(item.status === 'pending_reviewer' || item.status === 'pending_hr') && canManage && (
              <Button size="small" onClick={() => handleCancel(item)}>取消</Button>
            )}
            {(item.status === 'effective' || item.status === 'cancelled') && (
              <Button size="small" onClick={() => setFinalizeTarget(item)}>详情</Button>
            )}
          </div>
        </div>
        {item.comment && (
          <div className="text-xs text-gray-500 mt-2 pl-0.5">
            <span className="text-gray-400">{item.reviewer_name}评语：</span>{item.comment}
            {item.conclusion === '延长' && item.proposed_probation_end && (
              <Tag color="orange" style={{ fontSize: 10, margin: '0 0 0 8px' }}>建议新到期日 {item.proposed_probation_end}</Tag>
            )}
          </div>
        )}
      </Card>
    )
  }

  const tabItems = [
    {
      key: 'pending',
      label: <Badge count={pending.filter(i => i.status === 'pending_hr').length} size="small" offset={[8, -2]}>
        <span className="px-1">进行中（{pending.length}）</span>
      </Badge>,
      children: loading ? <div className="text-center py-8"><Spin /></div> : pending.length === 0
        ? <Empty description="暂无进行中的转正评估" className="py-6" />
        : <div className="space-y-2">{pending.map(renderItem)}</div>,
    },
    {
      key: 'done',
      label: `已完结（${effective.length}）`,
      children: loading ? <div className="text-center py-8"><Spin /></div> : effective.length === 0
        ? <Empty description="暂无已完结记录" className="py-6" />
        : <div className="space-y-2">{effective.slice(0, 30).map(renderItem)}</div>,
    },
  ]

  return (
    <>
      <Badge count={pending.filter(i => i.status === 'pending_hr').length} size="small" offset={[6, -2]}>
        <Button icon={<AuditOutlined />} onClick={() => setPanelOpen(true)}>转正管理</Button>
      </Badge>

      <Drawer title="试用期转正管理" width={720} open={panelOpen} onClose={() => setPanelOpen(false)}
        extra={canManage && (
          <Button type="primary" size="small" icon={<AuditOutlined />}
            onClick={() => { searchEmployees(''); setSendOpen(true) }}>
            发起评估
          </Button>
        )}
      >
        <div className="text-xs text-gray-400 mb-3">
          试用期统一 3 个月（到期=入职+3月-1天）。发起后评估卡片私发部门负责人，结论经 HR 确认生效：
          通过则写源表「员工性质=正式」并转在职；延长则改期后重走一轮。
        </div>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Drawer>

      <Modal title="发起转正评估" open={sendOpen} onCancel={() => { setSendOpen(false); sendForm.resetFields() }}
        onOk={handleSend} okText="发送评估卡片" confirmLoading={sending}>
        <Form form={sendForm} layout="vertical" className="mt-2">
          <Form.Item name="employee_id" label="试用期员工" rules={[{ required: true, message: '请选择员工' }]}>
            <Select showSearch placeholder="搜索试用期员工（姓名/工号）" filterOption={false}
              onSearch={searchEmployees} notFoundContent={empSearching ? <Spin size="small" /> : null}
              options={empOptions} />
          </Form.Item>
          <Form.Item name="reviewer_name" label="评估人（部门负责人）"
            tooltip="需评估人登录过系统或在源表有员工账号，否则卡片发送失败"
            rules={[{ required: true, message: '请选择或输入评估人姓名' }]}>
            <Select showSearch mode="tags" maxCount={1} placeholder="搜索在职员工（按姓名发卡）"
              filterOption={false} onSearch={searchReviewers}
              notFoundContent={reviewerSearching ? <Spin size="small" /> : null}
              options={reviewerOptions} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title={`评估详情 — ${finalizeTarget?.employee_name || ''}`} width={560} open={!!finalizeTarget}
        onClose={() => setFinalizeTarget(null)}>
        {finalizeTarget && (
          <Descriptions size="small" column={1} bordered items={[
            { key: 'e', label: '员工', children: `${finalizeTarget.employee_name}（${finalizeTarget.employee_number || '-'}）` },
            { key: 'r', label: '评估人', children: finalizeTarget.reviewer_name },
            { key: 'c', label: '结论', children: finalizeTarget.conclusion || '-' },
            { key: 'm', label: '评语', children: finalizeTarget.comment || '-' },
            { key: 'n', label: 'HR 附注', children: finalizeTarget.hr_note || '无' },
          ]} />
        )}
      </Drawer>
    </>
  )
}
