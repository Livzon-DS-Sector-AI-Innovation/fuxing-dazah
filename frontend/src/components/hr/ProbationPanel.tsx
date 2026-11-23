'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Badge, Button, Card, Descriptions, Drawer, Empty, Form, Modal, Select, Spin, Tabs, Tag } from 'antd'
import { AuditOutlined, CheckOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import {
  cancelProbationReview, createProbationReview, fetchProbationReviews, finalizeProbationReview,
} from '@/actions/hr'
import { fetchEmployeesAction } from '@/actions/hr'
import { useDebouncedCallback } from '@/hooks/hr'
import type { ProbationReviewItem } from '@/types/hr'

const STATUS_META: Record<string, { label: string; color: string }> = {
  pending_step1: { label: '直属上级待评', color: 'processing' },
  pending_step2: { label: '部门经理待审', color: 'processing' },
  pending_step3: { label: '分管领导待审', color: 'processing' },
  effective: { label: '已生效', color: 'success' },
  rejected: { label: '未通过/退回', color: 'red' },
  cancelled: { label: '已取消', color: 'default' },
}

const ACTIVE_STATUSES = ['pending_step1', 'pending_step2', 'pending_step3']

const CONCLUSION_COLOR: Record<string, string> = { 通过: 'green', 延长: 'orange', 不通过: 'red' }
const DECISION_COLOR: Record<string, string> = { 同意: 'green', 退回: 'red' }

/** 转正管理面板：入口按钮 + Drawer（三级审批链发起 / 进行中 / 记录） */
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
  const [sendForm] = Form.useForm()
  const empSeq = useRef(0)

  // 详情
  const [detailTarget, setDetailTarget] = useState<ProbationReviewItem | null>(null)

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

  // 远程搜索防抖（300ms）；首拉全量（searchEmployees('')）不经防抖直接执行
  const { run: debouncedSearchEmployees } = useDebouncedCallback(searchEmployees, 300)

  const handleSend = async () => {
    const v = await sendForm.validateFields()
    setSending(true)
    try {
      const r = await createProbationReview(v.employee_id)
      msg.success(r.message || '评估卡片已发送给直属上级')
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

  const pending = items.filter(i => ACTIVE_STATUSES.includes(i.status))
  const done = items.filter(i => !ACTIVE_STATUSES.includes(i.status))

  const renderItem = (item: ProbationReviewItem) => {
    const meta = STATUS_META[item.status] || { label: item.status, color: 'default' }
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
            {item.days_left != null && ACTIVE_STATUSES.includes(item.status) && (
              <span className={`text-xs ${item.days_left < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                {item.days_left < 0 ? `已过期 ${Math.abs(item.days_left)} 天` : `${item.days_left} 天后到期`}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button size="small" onClick={() => setDetailTarget(item)}>详情</Button>
            {item.status === 'pending_step3' && canManage && (
              <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleFinalize(item)}>
                确认{item.conclusion === '通过' ? '转正' : item.conclusion === '延长' ? '延长' : '结果'}
              </Button>
            )}
            {ACTIVE_STATUSES.includes(item.status) && canManage && (
              <Button size="small" onClick={() => handleCancel(item)}>取消</Button>
            )}
          </div>
        </div>
        <div className="text-xs text-gray-500 mt-2 pl-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-gray-400">①{item.direct_manager_name}</span>
          <span className="text-gray-400">②{item.dept_manager_name || '未配置'}</span>
          <span className="text-gray-400">③{item.leader_name || '未配置'}</span>
          {item.comment && (
            <span className="min-w-0">
              <span className="text-gray-400">{item.direct_manager_name}评语：</span>{item.comment}
              {item.conclusion === '延长' && item.proposed_probation_end && (
                <Tag color="orange" style={{ fontSize: 10, margin: '0 0 0 8px' }}>建议新到期日 {item.proposed_probation_end}</Tag>
              )}
            </span>
          )}
        </div>
      </Card>
    )
  }

  const tabItems = [
    {
      key: 'pending',
      label: <Badge count={pending.filter(i => i.status === 'pending_step3').length} size="small" offset={[8, -2]}>
        <span className="px-1">进行中（{pending.length}）</span>
      </Badge>,
      children: loading ? <div className="text-center py-8"><Spin /></div> : pending.length === 0
        ? <Empty description="暂无进行中的转正评估" className="py-6" />
        : <div className="space-y-2">{pending.map(renderItem)}</div>,
    },
    {
      key: 'done',
      label: `已完结（${done.length}）`,
      children: loading ? <div className="text-center py-8"><Spin /></div> : done.length === 0
        ? <Empty description="暂无已完结记录" className="py-6" />
        : <div className="space-y-2">{done.slice(0, 30).map(renderItem)}</div>,
    },
  ]

  return (
    <>
      <Badge count={pending.filter(i => i.status === 'pending_step3').length} size="small" offset={[6, -2]}>
        <Button icon={<AuditOutlined />} onClick={() => setPanelOpen(true)}>转正管理</Button>
      </Badge>

      <Drawer title="试用期转正管理" size={720} open={panelOpen} onClose={() => setPanelOpen(false)}
        extra={canManage && (
          <Button type="primary" size="small" icon={<AuditOutlined />}
            onClick={() => { searchEmployees(''); setSendOpen(true) }}>
            发起评估
          </Button>
        )}
      >
        <div className="text-xs text-gray-400 mb-3">
          三级审批链：直属上级评估 → 部门经理审批 → 分管领导审批，全部同意后自动转正生效（写源表「员工性质=正式」）。
          审批人自动解析：直属上级取员工档案，部门经理/分管领导取部门管理配置；转正前 30 天会提醒部门负责人，
          重点岗位须先有安全考试合格记录。试用期时长：一般岗位 3 个月 / 重点岗位 6 个月（系统设置可调）。
        </div>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Drawer>

      <Modal title="发起转正评估" open={sendOpen} onCancel={() => { setSendOpen(false); sendForm.resetFields() }}
        onOk={handleSend} okText="发送评估卡片" confirmLoading={sending}>
        <div className="text-xs text-gray-400 mt-1 mb-2">
          发起后评估卡依次私发直属上级 → 部门经理 → 分管领导；无需再手动选择评估人。
        </div>
        <Form form={sendForm} layout="vertical" className="mt-2">
          <Form.Item name="employee_id" label="试用期员工" rules={[{ required: true, message: '请选择员工' }]}>
            <Select showSearch placeholder="搜索试用期员工（姓名/工号）" filterOption={false}
              onSearch={debouncedSearchEmployees} notFoundContent={empSearching ? <Spin size="small" /> : null}
              options={empOptions} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title={`评估详情 — ${detailTarget?.employee_name || ''}`} size={560} open={!!detailTarget}
        onClose={() => setDetailTarget(null)}>
        {detailTarget && (
          <Descriptions size="small" column={1} bordered items={[
            { key: 'e', label: '员工', children: `${detailTarget.employee_name}（${detailTarget.employee_number || '-'}）` },
            { key: 's', label: '状态', children: `${detailTarget.status_label}（当前第 ${detailTarget.current_step} 级）` },
            { key: 's1', label: `① 直属上级 ${detailTarget.direct_manager_name}`,
              children: detailTarget.conclusion ? `${detailTarget.conclusion}：${detailTarget.comment || '—'}` : '待评估' },
            { key: 's2', label: `② 部门经理 ${detailTarget.dept_manager_name || '-'}`,
              children: detailTarget.dept_manager_decision
                ? <span>{detailTarget.dept_manager_decision}{detailTarget.dept_manager_comment ? `：${detailTarget.dept_manager_comment}` : ''}</span>
                : '待审批' },
            { key: 's3', label: `③ 分管领导 ${detailTarget.leader_name || '-'}`,
              children: detailTarget.leader_decision
                ? <span>{detailTarget.leader_decision}{detailTarget.leader_comment ? `：${detailTarget.leader_comment}` : ''}</span>
                : '待审批' },
            ...(detailTarget.proposed_probation_end && detailTarget.conclusion === '延长'
              ? [{ key: 'p', label: '建议新到期日', children: detailTarget.proposed_probation_end }] : []),
            { key: 'n', label: 'HR 附注', children: detailTarget.hr_note || '无' },
          ]} />
        )}
      </Drawer>
    </>
  )
}
