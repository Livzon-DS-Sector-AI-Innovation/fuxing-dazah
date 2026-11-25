'use client'

// 合同详情抽屉：六节点进度（对应需求「待补四：状态分散缺完整进度」）+
// 历次合同履历 + 全部流转动作（站内审批 / 重新发起飞书审批 / 续签 / 盖章 / 领取 / 终止）。

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Input,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
} from 'antd'
import {
  decideLaborContract,
  deliverLaborContract,
  fetchLaborContractDetail,
  reAnnounceLaborContract,
  stampLaborContract,
  terminateLaborContract,
} from '@/actions/hr'
import type { LaborContract, LaborContractDetail } from '@/types/hr'
import ContractFormModal from '@/components/hr/ContractFormModal'

interface Props {
  contractId: string | null
  canManage: boolean
  onClose: () => void
  onChanged: () => void
}

/** 六节点进度：由字段推导当前步骤（对应 公告期预警→部门审批→通知续签→签订盖章→领取→签字） */
function progressCurrent(c: LaborContract): { current: number; labels: string[] } {
  const labels = ['到期预警', '部门审批', '通知续签', '签订盖章', '领取合同', '线上签字']
  if (c.sign_confirmed_at) return { current: 6, labels }
  if (c.delivered_at) return { current: 5, labels }
  if (c.stamped_at) return { current: 4, labels }
  if (c.seq_no > 1 || c.sign_date) return { current: 3, labels }
  if (c.dept_decision === 'disagree') return { current: 2, labels }
  if (c.status === 'pending_renewal') return { current: 1, labels }
  return { current: 0, labels }
}

export default function ContractDetailDrawer({ contractId, canManage, onClose, onChanged }: Props) {
  const { message } = App.useApp()
  const [detail, setDetail] = useState<LaborContractDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [acting, setActing] = useState(false)
  const [renewOpen, setRenewOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [terminateOpen, setTerminateOpen] = useState(false)
  const [terminateReason, setTerminateReason] = useState('')

  const load = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const r = await fetchLaborContractDetail(id)
      setDetail(r.data)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '加载合同详情失败')
      onClose()
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (contractId) void load(contractId)
    else setDetail(null)
  }, [contractId, load])

  /** 执行一个流转动作 → 刷详情 + 通知台账刷新；失败弹错不中断 */
  const act = async (fn: () => Promise<unknown>, successText: string) => {
    if (!contractId) return
    setActing(true)
    try {
      await fn()
      message.success(successText)
      await load(contractId)
      onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败')
    } finally {
      setActing(false)
    }
  }

  const c = detail
  const progress = c ? progressCurrent(c) : null
  const canDecide = canManage && c?.status === 'pending_renewal'
  const canRenew =
    canManage && !!c &&
    ['active', 'pending_renewal', 'renewing', 'expired_unrenewed'].includes(c.status) &&
    c.term_type !== 'open'
  const canStamp = canManage && !!c && ['active', 'renewing'].includes(c.status) && !c.stamped_at
  const canDeliver = canManage && !!c?.stamped_at && !c?.delivered_at
  const canTerminate = canManage && !!c && !['superseded', 'terminated'].includes(c.status)

  return (
    <Drawer
      open={!!contractId}
      onClose={onClose}
      size="large"
      title={c ? `${c.name} · 第 ${c.seq_no} 份合同` : '合同详情'}
      extra={
        c && (
          <Tag color={c.status === 'active' ? 'green' : c.status === 'terminated' ? 'red' : 'orange'}>
            {c.status_label}
          </Tag>
        )
      }
    >
      <Spin spinning={loading}>
        {c && progress && (
          <div className="space-y-5">
            <Steps
              size="small"
              current={progress.current}
              items={progress.labels.map((t) => ({ title: t }))}
            />

            <Descriptions
              size="small"
              column={2}
              bordered
              items={[
                { key: 'emp', label: '工号', children: c.employee_number },
                { key: 'dept', label: '部门 / 岗位', children: `${c.department}${c.position ? ' / ' + c.position : ''}` },
                { key: 'seq', label: '签订次序', children: c.seq_label },
                { key: 'term', label: '合同期限', children: c.term_label },
                { key: 'start', label: '起始日', children: c.start_date || '-' },
                { key: 'end', label: '到期日', children: c.end_date || '无固定期限' },
                { key: 'sign', label: '签订日', children: c.sign_date || '-' },
                {
                  key: 'decision',
                  label: '部门审批',
                  children: c.dept_decision
                    ? `${c.dept_decision_label}（${c.dept_decision_by || '-'} · ${c.dept_decision_at?.slice(0, 16) || '-'}）`
                    : c.status === 'pending_renewal'
                      ? `待审批（${c.approval_mode_label || '未发起'}）`
                      : '-',
                },
                { key: 'stamp', label: '盖章完成', children: c.stamped_at?.slice(0, 16) || '-' },
                { key: 'deliver', label: '领取时间', children: c.delivered_at?.slice(0, 16) || '-' },
                { key: 'signok', label: '线上签字', children: c.sign_confirmed_at?.slice(0, 16) || '-' },
                {
                  key: 'term_info',
                  label: '终止信息',
                  children: c.terminated_at ? `${c.terminated_reason || '-'}（${c.terminated_at.slice(0, 16)}）` : '-',
                },
                ...(c.approval_instance_code
                  ? [{ key: 'instance', label: '飞书审批实例', children: c.approval_instance_code }]
                  : []),
                ...(c.remark ? [{ key: 'remark', label: '备注', children: c.remark }] : []),
              ]}
            />

            {canManage && (
              <Space wrap>
                {canDecide && c.approval_mode === 'feishu' && (
                  <Button disabled title="飞书审批由部门负责人在飞书完成，结果自动回写">
                    飞书审批中
                  </Button>
                )}
                {canDecide && c.approval_mode !== 'feishu' && (
                  <>
                    <Popconfirm
                      title="确认同意续签？"
                      description="同意后进入续签办理，并推送续签通知给员工。"
                      onConfirm={() => void act(() => decideLaborContract(c.id, 'agree'), '已记录：同意续签')}
                      disabled={acting}
                    >
                      <Button type="primary" disabled={acting}>同意续签</Button>
                    </Popconfirm>
                    <Popconfirm
                      title="确认不同意续签？"
                      description="合同将标记终止并转入离职流程办理，此后不再参与到期预警。"
                      onConfirm={() =>
                        void act(
                          () => decideLaborContract(c.id, 'disagree'),
                          '已记录：不同意续签，合同转终止流程',
                        )
                      }
                      disabled={acting}
                    >
                      <Button danger disabled={acting}>不同意续签</Button>
                    </Popconfirm>
                    <Button
                      disabled={acting}
                      onClick={() => void act(() => reAnnounceLaborContract(c.id), '已重新发起审批')}
                    >
                      重新发起飞书审批
                    </Button>
                  </>
                )}
                {canRenew && (
                  <Button
                    type={c.status === 'renewing' ? 'primary' : 'default'}
                    disabled={acting}
                    onClick={() => setRenewOpen(true)}
                  >
                    办理续签
                  </Button>
                )}
                {canStamp && (
                  <Popconfirm
                    title="确认已签订并盖章完成？"
                    description="确认后推送领取通知给员工。"
                    onConfirm={() => void act(() => stampLaborContract(c.id), '已标记盖章完成')}
                    disabled={acting}
                  >
                    <Button disabled={acting}>标记盖章完成</Button>
                  </Popconfirm>
                )}
                {canDeliver && (
                  <Popconfirm
                    title="员工已领取合同原件？"
                    description="确认后推送线上签字提醒（一次性签字链接）。"
                    onConfirm={() => void act(() => deliverLaborContract(c.id), '已标记领取')}
                    disabled={acting}
                  >
                    <Button type="primary" disabled={acting}>标记已领取</Button>
                  </Popconfirm>
                )}
                {canManage && ['active', 'renewing'].includes(c.status) && (
                  <Button disabled={acting} onClick={() => setEditOpen(true)}>编辑</Button>
                )}
                {canTerminate && (
                  <Button danger disabled={acting} onClick={() => { setTerminateReason(''); setTerminateOpen(true) }}>
                    终止合同
                  </Button>
                )}
              </Space>
            )}

            {c.history.length > 1 && (
              <div>
                <div className="mb-2 text-[13px] font-medium text-gray-600">历次合同（{c.name}）</div>
                <Table<LaborContract>
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={[...c.history].reverse()}
                  columns={[
                    { title: '次序', dataIndex: 'seq_label', width: 130 },
                    { title: '期限', dataIndex: 'term_label', width: 90 },
                    { title: '起止', width: 210, render: (_, r) => `${r.start_date || '-'} ~ ${r.end_date || '无固定'}` },
                    { title: '状态', dataIndex: 'status_label', width: 100 },
                    { title: '签字', width: 90, render: (_, r) => (r.sign_confirmed_at ? '已确认' : '-') },
                  ]}
                />
              </div>
            )}
          </div>
        )}
      </Spin>

      {/* 续签办理 / 编辑：期限按签订次数自动带出，仅确认日期 */}
      {c && (
        <ContractFormModal
          open={renewOpen}
          mode="renew"
          contract={c}
          onClose={() => setRenewOpen(false)}
          onSaved={() => {
            setRenewOpen(false)
            if (contractId) void load(contractId)
            onChanged()
          }}
        />
      )}
      {c && (
        <ContractFormModal
          open={editOpen}
          mode="edit"
          contract={c}
          onClose={() => setEditOpen(false)}
          onSaved={() => {
            setEditOpen(false)
            if (contractId) void load(contractId)
            onChanged()
          }}
        />
      )}

      {/* 终止：原因写台账 */}
      <Modal
        open={terminateOpen}
        title="终止合同"
        okText="确认终止"
        okButtonProps={{ danger: true }}
        confirmLoading={acting}
        onCancel={() => setTerminateOpen(false)}
        onOk={() => {
          if (!c) return
          void act(
            () => terminateLaborContract(c.id, terminateReason.trim() || undefined),
            '合同已终止',
          ).then(() => setTerminateOpen(false))
        }}
      >
        <div className="space-y-2">
          <div className="text-[13px] text-gray-500">
            终止原因将写入台账（如：到期未续签、协商解除等）；已离职员工的合同在离职台账单独保管。
          </div>
          <Input
            placeholder="终止原因（选填）"
            value={terminateReason}
            maxLength={100}
            onChange={(e) => setTerminateReason(e.target.value)}
          />
        </div>
      </Modal>
    </Drawer>
  )
}
