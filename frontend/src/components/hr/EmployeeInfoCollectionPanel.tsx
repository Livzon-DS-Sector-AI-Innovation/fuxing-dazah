'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Badge, Button, Card, Descriptions, Drawer, Empty, Form, Input, Modal, Select, Spin, Tabs, Tag, Tooltip } from 'antd'
import { SendOutlined, FileSearchOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import {
  approveInfoCollection, createInfoCollections, fetchInfoCollections, rejectInfoCollection,
} from '@/actions/hr'
import { fetchEmployeesAction } from '@/actions/hr'
import type { EmployeeInfoCollectionItem } from '@/types/hr'

const STATUS_META: Record<string, { label: string; color: string }> = {
  sent: { label: '待填写', color: 'default' },
  submitted: { label: '待审核', color: 'orange' },
  approved: { label: '已采纳', color: 'green' },
  rejected: { label: '已驳回', color: 'red' },
}

/** 员工信息收集面板：发起收集 / 待审核对比采纳 / 进度一览 */
export default function EmployeeInfoCollectionPanel() {
  const { message: msg, modal } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:profile:update')

  const [items, setItems] = useState<EmployeeInfoCollectionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('submitted')
  const [panelOpen, setPanelOpen] = useState(false)

  // 发起收集
  const [sendOpen, setSendOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [empOptions, setEmpOptions] = useState<{ value: string; label: string }[]>([])
  const [empSearching, setEmpSearching] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const searchSeq = useRef(0)

  // 对比 Drawer
  const [diffItem, setDiffItem] = useState<EmployeeInfoCollectionItem | null>(null)

  // 驳回
  const [rejectForm] = Form.useForm()
  const [rejectTarget, setRejectTarget] = useState<EmployeeInfoCollectionItem | null>(null)
  const [rejecting, setRejecting] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await fetchInfoCollections()
      setItems(r.data || [])
    } catch { setItems([]) }
    finally { setLoading(false) }
  }, [])

  // 初次加载：effect 内自含异步（避免同步 setState 级联渲染告警）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchInfoCollections()
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
    const seq = ++searchSeq.current
    setEmpSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== searchSeq.current) return
      const raw = (d as { data?: { items?: unknown[] } | unknown[] })?.data
      const list = (Array.isArray(raw) ? raw : (raw as { items?: unknown[] })?.items || []) as Array<{
        id: string; name: string; employee_number?: string; department?: string
      }>
      setEmpOptions(list.map(e => ({
        value: e.id,
        label: `${e.name}（${e.employee_number || ''} · ${e.department || '-'}）`,
      })))
    } catch { /* 静默 */ }
    finally { if (seq === searchSeq.current) setEmpSearching(false) }
  }

  const handleSend = async () => {
    if (selectedIds.length === 0) { msg.warning('请选择员工'); return }
    setSending(true)
    try {
      const r = await createInfoCollections(selectedIds)
      if (r.data?.created > 0) msg.success(r.message || `已发送 ${r.data.created} 份`)
      r.data?.skipped?.forEach(s => msg.warning(`${s.name || '员工'}：${s.reason}`))
      setSendOpen(false); setSelectedIds([]); load()
    } catch (e) { msg.error(e instanceof Error ? e.message : '发起失败') }
    finally { setSending(false) }
  }

  const handleApprove = (item: EmployeeInfoCollectionItem) => {
    modal.confirm({
      title: `采纳 ${item.employee_name} 的信息？`,
      content: '将写入飞书源表并更新本地档案（下轮同步结果一致）。',
      okText: '采纳',
      onOk: async () => {
        try {
          const r = await approveInfoCollection(item.id)
          msg.success(r.message || '已采纳')
          load()
        } catch (e) { msg.error(e instanceof Error ? e.message : '采纳失败') }
      },
    })
  }

  const handleReject = async () => {
    if (!rejectTarget) return
    const v = await rejectForm.validateFields()
    setRejecting(true)
    try {
      const r = await rejectInfoCollection(rejectTarget.id, v.reason)
      msg.success(r.message || '已驳回')
      setRejectTarget(null); rejectForm.resetFields(); load()
    } catch (e) { msg.error(e instanceof Error ? e.message : '驳回失败') }
    finally { setRejecting(false) }
  }

  const pending = items.filter(i => i.status === 'submitted')
  const sentItems = items.filter(i => i.status === 'sent')
  const doneItems = items.filter(i => i.status === 'approved' || i.status === 'rejected')

  const renderItem = (item: EmployeeInfoCollectionItem) => {
    const meta = STATUS_META[item.status]
    const changed = item.diff.filter(d => d.submitted && d.submitted !== d.current).length
    return (
      <Card key={item.id} size="small">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <b className="text-sm">{item.employee_name}</b>
            <span className="text-xs text-gray-400">{item.employee_number}</span>
            <span className="text-xs text-gray-500">{item.department} · {item.position}</span>
            <Tag color={meta.color} style={{ fontSize: 10, margin: 0 }}>{meta.label}</Tag>
            {item.status === 'submitted' && changed > 0 && (
              <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>{changed} 项更新</Tag>
            )}
            {item.status === 'submitted' && changed === 0 && (
              <Tooltip title="员工填写内容与档案现值一致（补空/确认）"><Tag style={{ fontSize: 10, margin: 0 }}>无差异</Tag></Tooltip>
            )}
            {item.reject_reason && (
              <span className="text-xs text-red-400">驳回原因：{item.reject_reason}</span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-400 flex-shrink-0">
            {item.submitted_at && <span>提交于 {item.submitted_at.slice(0, 16).replace('T', ' ')}</span>}
            {item.status === 'submitted' && canManage && <>
              <Button size="small" icon={<FileSearchOutlined />} onClick={() => setDiffItem(item)}>对比</Button>
              <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleApprove(item)}>采纳</Button>
              <Button size="small" danger icon={<CloseOutlined />} onClick={() => { setRejectTarget(item); rejectForm.resetFields() }}>驳回</Button>
            </>}
          </div>
        </div>
      </Card>
    )
  }

  const tabItems = [
    {
      key: 'submitted',
      label: <Badge count={pending.length} size="small" offset={[8, -2]}><span className="px-1">待审核</span></Badge>,
      children: loading ? <div className="text-center py-8"><Spin /></div> : pending.length === 0
        ? <Empty description="暂无待审核的员工信息" className="py-6" />
        : <div className="space-y-2">{pending.map(i => renderItem(i))}</div>,
    },
    {
      key: 'sent',
      label: `待填写（${sentItems.length}）`,
      children: loading ? <div className="text-center py-8"><Spin /></div> : sentItems.length === 0
        ? <Empty description="暂无进行中的收集任务" className="py-6" />
        : <div className="space-y-2">{sentItems.map(i => renderItem(i))}</div>,
    },
    {
      key: 'done',
      label: `已结束（${doneItems.length}）`,
      children: loading ? <div className="text-center py-8"><Spin /></div> : doneItems.length === 0
        ? <Empty description="暂无已结束的任务" className="py-6" />
        : <div className="space-y-2">{doneItems.slice(0, 30).map(i => renderItem(i))}</div>,
    },
  ]

  return (
    <>
      {/* 入口按钮：不占页面版面，点击开 Drawer */}
      <Badge count={pending.length} size="small" offset={[6, -2]}>
        <Button icon={<SendOutlined />} onClick={() => setPanelOpen(true)}>
          新员工信息收集
        </Button>
      </Badge>

      <Drawer title="新员工信息收集" width={720} open={panelOpen} onClose={() => setPanelOpen(false)}
        extra={canManage && (
          <Button type="primary" size="small" icon={<SendOutlined />} onClick={() => { searchEmployees(''); setSendOpen(true) }}>
            发起收集
          </Button>
        )}
      >
        <div className="text-xs text-gray-400 mb-3">
          向新员工飞书私发信息登记表单卡片，员工在飞书里填写提交；HR 审核采纳后自动写入员工档案源表。
        </div>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Drawer>

      <Modal title="发起信息收集" open={sendOpen} onCancel={() => setSendOpen(false)}
        onOk={handleSend} okText="发送" confirmLoading={sending} okButtonProps={{ disabled: selectedIds.length === 0 }}>
        <div className="space-y-3">
          <Select mode="multiple" style={{ width: '100%' }} placeholder="搜索并选择员工（姓名/工号）"
            showSearch filterOption={false} onSearch={searchEmployees} notFoundContent={empSearching ? <Spin size="small" /> : null}
            value={selectedIds} onChange={setSelectedIds} options={empOptions}
          />
          <div className="text-xs text-gray-400">
            将向所选员工飞书私发「新员工信息登记」表单卡片（身份证、联系方式、学历、紧急联系人等 15 项）；
            未绑定飞书账号的员工会被跳过并提示。
          </div>
        </div>
      </Modal>

      <Drawer title={`信息对比 — ${diffItem?.employee_name || ''}`} width={640} open={!!diffItem}
        onClose={() => setDiffItem(null)}
        extra={diffItem?.status === 'submitted' && canManage && (
          <div className="flex gap-2">
            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => { handleApprove(diffItem); setDiffItem(null) }}>采纳</Button>
            <Button size="small" danger icon={<CloseOutlined />} onClick={() => { setRejectTarget(diffItem); setDiffItem(null); rejectForm.resetFields() }}>驳回</Button>
          </div>
        )}
      >
        {diffItem && (
          <>
            <Descriptions size="small" column={2} className="mb-3" items={[
              { key: 'n', label: '员工', children: `${diffItem.employee_name}（${diffItem.employee_number || '-'}）` },
              { key: 'd', label: '部门岗位', children: `${diffItem.department || '-'} · ${diffItem.position || '-'}` },
              { key: 't', label: '提交时间', children: diffItem.submitted_at?.slice(0, 16).replace('T', ' ') || '-' },
              { key: 'r', label: '此前驳回', children: diffItem.reject_reason || '无' },
            ]} />
            <table className="w-full text-[13px] border-collapse">
              <thead><tr className="bg-gray-50">
                <th className="p-2 text-left border w-28">字段</th>
                <th className="p-2 text-left border">档案现值</th>
                <th className="p-2 text-left border">员工填写</th>
              </tr></thead>
              <tbody>
                {diffItem.diff.map(d => {
                  const changed = !!d.submitted && d.submitted !== d.current
                  return (
                    <tr key={d.field} className={changed ? 'bg-blue-50' : ''}>
                      <td className="p-2 border">{d.label}</td>
                      <td className="p-2 border text-gray-500">{d.current || <span className="text-gray-300">（空）</span>}</td>
                      <td className="p-2 border font-medium">
                        {d.submitted || <span className="text-gray-300">（未填）</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <div className="text-xs text-gray-400 mt-2">蓝色行为与档案不一致的字段；采纳后全部覆盖写入。</div>
          </>
        )}
      </Drawer>

      <Modal title={`驳回 — ${rejectTarget?.employee_name || ''}`} open={!!rejectTarget}
        onCancel={() => setRejectTarget(null)} onOk={handleReject} okText="驳回并通知重填" okButtonProps={{ danger: true }} confirmLoading={rejecting}>
        <Form form={rejectForm} layout="vertical" className="mt-2">
          <Form.Item name="reason" label="驳回原因（将随新表单卡片发送给员工）"
            rules={[{ required: true, message: '请填写原因' }, { max: 200, message: '最多 200 字' }]}>
            <Input.TextArea rows={3} placeholder="如：身份证号位数不对，请核对后重新填写" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
