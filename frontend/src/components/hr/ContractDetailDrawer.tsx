'use client'

// 合同详情抽屉：顶部「下一步」面板（当前环节的动作都在这里）+ 六步进度（后端按状态推导）+
// 通知留痕 + 历次合同履历 + 电子档案（扫描件版本 / 调阅留痕）。
// 办理续签后直接切到新合同，把「盖章 → 领取 → 归档」串下去（员工领取合同即签收，
// 系统只在公司内网可达，没有领取后的线上签字）；
// 部门不同意续签 / 到期未续签的，在这里直接为员工发起离职办理。

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Dropdown,
  Input,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import { DownOutlined } from '@ant-design/icons'
import {
  decideLaborContract,
  deliverLaborContract,
  fetchLaborContractDetail,
  reAnnounceLaborContract,
  resendLaborContractNotice,
  stampLaborContract,
  terminateLaborContract,
  transferLaborContractToOffboarding,
} from '@/actions/hr'
import type { ContractNotice, LaborContract, LaborContractDetail } from '@/types/hr'
import { noticeKindLabel, noticeStatusMeta, rowNextAction, toStepItems } from '@/lib/hr/contractFlow'
import { formatDateTime } from '@/lib/hr/format'
import ContractFormModal from '@/components/hr/ContractFormModal'
import ContractArchivePanel from '@/components/hr/labor-contract/ContractArchivePanel'

interface Props {
  contractId: string | null
  canManage: boolean
  /** 有「部门续签审批」权限：部门负责人只凭它就能登记同意 / 不同意 */
  canApprove?: boolean
  onClose: () => void
  onChanged: () => void
}

/** 后端返回的是带 +00:00 的 UTC 时间串：按本地时区格式化（此前直接截取显示的是 UTC，差 8 小时） */
function fmtTime(iso?: string | null): string {
  return iso ? formatDateTime(iso) : '-'
}

const STATUS_TAG: Record<string, string> = {
  active: 'green',
  renewing: 'blue',
  pending_renewal: 'orange',
  expired_unrenewed: 'volcano',
  terminated: 'red',
  superseded: 'default',
}

const DECIDABLE_STATUSES = ['active', 'pending_renewal', 'renewing', 'expired_unrenewed']
const DONE_STATUSES = ['superseded', 'terminated']

export default function ContractDetailDrawer({ contractId, canManage, canApprove = false, onClose, onChanged }: Props) {
  const { message } = App.useApp()
  const router = useRouter()
  const [detail, setDetail] = useState<LaborContractDetail | null>(null)
  const [acting, setActing] = useState(false)
  const [renewOpen, setRenewOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [terminateOpen, setTerminateOpen] = useState(false)
  const [terminateReason, setTerminateReason] = useState('')
  // 不同意续签 / 到期未续签之后：提醒 HR 给员工办离职，发起成功后给直达入口
  const [handoff, setHandoff] = useState<{ contractId: string; caseId?: string; caseNo?: string } | null>(null)
  // 续签后在抽屉内切到新合同：记下「从哪张切到了哪张」，外层关掉或换成别的合同时自然失效
  const [switched, setSwitched] = useState<{ from: string; to: string } | null>(null)
  const archiveRef = useRef<HTMLDivElement>(null)

  const currentId = contractId && switched?.from === contractId ? switched.to : contractId

  // 打开 / 切换合同时加载：setState 全部在 await 之后，不在 effect 里同步触发级联渲染
  useEffect(() => {
    if (!currentId) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchLaborContractDetail(currentId)
        if (!cancelled) setDetail(r.data)
      } catch (e) {
        if (cancelled) return
        message.error(e instanceof Error ? e.message : '加载合同详情失败')
        onClose()
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId])

  // 事件驱动的刷新（流转动作 / 续签 / 编辑 / 归档之后）
  const load = useCallback(async (id: string) => {
    try {
      const r = await fetchLaborContractDetail(id)
      setDetail(r.data)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '加载合同详情失败')
    }
  }, [message])

  /** 执行一个流转动作 → 刷详情 + 通知台账刷新；失败弹错不中断 */
  const act = async (fn: () => Promise<unknown>, successText: string, after?: () => void) => {
    if (!currentId) return
    setActing(true)
    try {
      await fn()
      message.success(successText)
      after?.()
      await load(currentId)
      onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败')
    } finally {
      setActing(false)
    }
  }

  // 只展示当前请求的那份合同：抽屉关掉或切到另一份时，旧详情不顶替（不必在 effect 里清状态）
  const c = detail && detail.id === currentId ? detail : null
  const canDecide = !!c && (canManage || canApprove) && DECIDABLE_STATUSES.includes(c.status) && !c.stamped_at
  const feishuApproving = !!c && c.approval_mode === 'feishu' && c.status === 'pending_renewal'
  const canRenew = !!c && canManage && DECIDABLE_STATUSES.includes(c.status) && c.term_type !== 'open' && !c.stamped_at
  const deptAgreed = c?.dept_decision === 'agree'
  const canStamp = !!c && canManage && ['active', 'renewing'].includes(c.status) && !c.stamped_at
  const canDeliver = !!c && canManage && !!c.stamped_at && !c.delivered_at
  const canTerminate = !!c && canManage && !DONE_STATUSES.includes(c.status)
  const canTransfer = !!c && canManage && (
    c.status === 'expired_unrenewed' || (c.status === 'terminated' && c.dept_decision === 'disagree')
  )
  const action = c ? rowNextAction(c) : null
  const live = !!c && !DONE_STATUSES.includes(c.status)
  const waitingHr = <span className="text-[13px] text-[var(--color-slate)]">等 HR 办理（需要「管理劳动合同」权限）。</span>

  /** 重发员工通知（续签通知 / 领取通知） */
  const resend = (kind: 'renew' | 'collect') => {
    if (!c) return Promise.resolve()
    return act(async () => {
      const r = await resendLaborContractNotice(c.id, kind)
      if (r.data.status !== 'sent') {
        message.warning(`通知没有送达：${r.data.error || '原因未知'}`, 8)
      }
    }, '已重发')
  }

  /** 转入离职办理：成功后把办理单编号亮出来，并给「去离职管理继续办理」的入口 */
  const doTransfer = async () => {
    if (!c) return
    setActing(true)
    try {
      const r = await transferLaborContractToOffboarding(c.id)
      setHandoff({ contractId: c.id, caseId: r.data.id, caseNo: r.data.case_no })
      message.success(`已转入离职办理（${r.data.case_no}）`)
      await load(c.id)
      onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '转入离职办理失败')
    } finally {
      setActing(false)
    }
  }

  /** 部门意见：同意 / 不同意（飞书审批进行中时不提供站内登记） */
  const decideButtons = (primary: boolean) => {
    if (!c) return null
    if (feishuApproving) {
      return (
        <Tooltip title="部门负责人在飞书审批，结果自动回写；不需要在这里操作">
          <Button disabled>飞书审批中</Button>
        </Tooltip>
      )
    }
    return (
      <Space wrap>
        <Popconfirm
          title="部门同意续签？"
          description="登记后进入续签办理，并给员工发续签通知。代部门负责人登记的，系统会记录登记人。"
          okText="同意续签"
          onConfirm={() => void act(() => decideLaborContract(c.id, 'agree'), '已登记：部门同意续签')}
          disabled={acting}
        >
          <Button type={primary ? 'primary' : 'default'} loading={acting}>同意续签</Button>
        </Popconfirm>
        <Popconfirm
          title="部门不同意续签？"
          description="合同将标记终止。登记后可以在这里直接为员工发起离职办理。"
          okText="不同意续签"
          okButtonProps={{ danger: true }}
          cancelText="取消"
          onConfirm={() =>
            void act(
              () => decideLaborContract(c.id, 'disagree'),
              '已登记：部门不同意续签，合同已终止',
              () => setHandoff({ contractId: c.id }),
            )
          }
          disabled={acting}
        >
          <Button danger loading={acting}>不同意续签</Button>
        </Popconfirm>
        {c.renewal_approval_configured && c.status === 'pending_renewal' && (
          <Button disabled={acting} onClick={() => void act(() => reAnnounceLaborContract(c.id), '已重新发起审批')}>
            转飞书审批
          </Button>
        )}
      </Space>
    )
  }

  /** 「下一步」面板：当前环节的主按钮 + 说明 */
  const renderNext = () => {
    if (!c || !action) return null
    let body: React.ReactNode = null
    switch (action.kind) {
      case 'decide':
        body = canDecide ? decideButtons(true) : (
          <span className="text-[13px] text-[var(--color-slate)]">
            等部门负责人给出意见；有「部门续签审批」权限的人才能登记。
          </span>
        )
        break
      case 'renew':
        body = canRenew ? (
          <Button type="primary" disabled={acting || !deptAgreed} onClick={() => setRenewOpen(true)}>
            办理续签
          </Button>
        ) : waitingHr
        break
      case 'stamp':
        body = canStamp ? (
          <Popconfirm
            title="员工已签字、公司已盖章？"
            description="登记后给员工发领取通知。"
            okText="已盖章"
            onConfirm={() =>
              void act(async () => {
                const r = await stampLaborContract(c.id)
                if (r.data.notice && r.data.notice.status !== 'sent') {
                  message.warning(`已登记盖章，但领取通知没有送达：${r.data.notice.error || '员工可能没有飞书账号'}`)
                }
              }, '已登记盖章')
            }
            disabled={acting}
          >
            <Button type="primary" loading={acting}>登记已盖章</Button>
          </Popconfirm>
        ) : waitingHr
        break
      case 'deliver':
        body = canDeliver ? (
          <Popconfirm
            title="员工已领取合同原件？"
            description="员工到人事办公室领取合同即完成签收，登记后可以上传扫描件归档。"
            okText="已领取"
            onConfirm={() => void act(() => deliverLaborContract(c.id), '已登记领取')}
            disabled={acting}
          >
            <Button type="primary" loading={acting}>登记已领取</Button>
          </Popconfirm>
        ) : waitingHr
        break
      case 'archive':
        body = (
          <Space wrap>
            <Button type="primary" onClick={() => archiveRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
              去上传扫描件
            </Button>
            <span className="text-[13px] text-[var(--color-slate)]">逐页扫描合并成一份文件，在下方「电子档案」上传。</span>
          </Space>
        )
        break
      case 'transfer':
        body = canTransfer ? (
          <Space wrap>
            {c.status === 'expired_unrenewed' && canDecide && (
              <Popconfirm
                title="部门同意续签？"
                description="员工留下、补办续签时登记；登记后可以办理续签。"
                okText="同意续签"
                onConfirm={() => void act(() => decideLaborContract(c.id, 'agree'), '已登记：部门同意续签')}
                disabled={acting}
              >
                <Button loading={acting}>部门同意续签</Button>
              </Popconfirm>
            )}
            <Popconfirm
              title="为这位员工发起离职办理？"
              description="合同置为已终止，并在「离职管理」里新建一张办理单，离职日期默认取合同到期日。"
              okText="发起离职办理"
              onConfirm={() => void doTransfer()}
              disabled={acting}
            >
              <Button type="primary" danger loading={acting}>转入离职办理</Button>
            </Popconfirm>
          </Space>
        ) : (
          <span className="text-[13px] text-[var(--color-slate)]">等 HR 处理（转入离职办理需要「管理劳动合同」权限）。</span>
        )
        break
    }
    return (
      <Alert
        type={action.kind === 'transfer' ? 'warning' : 'info'}
        showIcon
        title={`下一步：${action.label}`}
        description={
          <div className="space-y-2">
            <div>{action.hint}</div>
            {body}
          </div>
        }
      />
    )
  }

  return (
    <Drawer
      open={!!contractId}
      onClose={onClose}
      size="large"
      title={c ? `${c.name} · 第 ${c.seq_no} 份合同` : '合同详情'}
      extra={
        c && (
          <Space>
            <Tag color={STATUS_TAG[c.status] ?? 'default'}>{c.status_label}</Tag>
            {c.origin_label && <Tag>{c.origin_label}</Tag>}
          </Space>
        )
      }
    >
      <Spin spinning={!!currentId && !c}>
        {c && (
          <div className="space-y-5">
            {handoff && handoff.contractId === c.id && (
              <Alert
                type={handoff.caseId ? 'success' : 'warning'}
                showIcon
                closable
                onClose={() => setHandoff(null)}
                title={
                  handoff.caseId
                    ? `已转入离职办理：${handoff.caseNo}`
                    : c.status === 'terminated'
                      ? '部门不同意续签，合同已终止。这位员工的离职手续还没发起。'
                      : '合同到期未续签。这位员工的离职手续还没发起。'
                }
                action={
                  handoff.caseId ? (
                    <Button size="small" type="primary" onClick={() => router.push(`/hr/departure?case=${handoff.caseId}`)}>
                      去离职管理继续办理
                    </Button>
                  ) : canTransfer ? (
                    <Popconfirm
                      title="现在为这位员工发起离职办理？"
                      description="在「离职管理」里新建一张办理单，离职日期默认取合同到期日。"
                      okText="发起"
                      onConfirm={() => void doTransfer()}
                    >
                      <Button size="small" type="primary" danger>发起离职办理</Button>
                    </Popconfirm>
                  ) : undefined
                }
              />
            )}

            {live && renderNext()}

            {/* 六个节点在抽屉宽度下并排，标题放图标下方才不会被折成两行 */}
            <Steps size="small" titlePlacement="vertical" items={toStepItems(c.progress)} />

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
                    ? `${c.dept_decision_label}（${c.dept_decision_by || '-'} · ${fmtTime(c.dept_decision_at)}）`
                    : c.status === 'pending_renewal'
                      ? `待审批（${c.approval_mode_label || '未发起'}）`
                      : '-',
                },
                { key: 'stamp', label: '盖章完成', children: fmtTime(c.stamped_at) },
                { key: 'deliver', label: '领取时间', children: fmtTime(c.delivered_at) },
                {
                  key: 'term_info',
                  label: '终止信息',
                  children: c.terminated_at ? `${c.terminated_reason || '-'}（${fmtTime(c.terminated_at)}）` : '-',
                },
                ...(c.approval_instance_code
                  ? [{ key: 'instance', label: '飞书审批实例', children: c.approval_instance_code }]
                  : []),
                ...(c.remark ? [{ key: 'remark', label: '备注', children: c.remark }] : []),
              ]}
            />

            {live && (
              <Space wrap>
                {/* 还没进公告期的在履约合同：要提前续签，先在这里登记部门意见 */}
                {canDecide && action?.kind !== 'decide' && c.status === 'active' && (
                  <>
                    <span className="text-[13px] text-[var(--color-slate)]">提前续签先登记部门意见：</span>
                    {decideButtons(false)}
                  </>
                )}
                {canRenew && action?.kind !== 'renew' && c.status !== 'active' && (
                  <Tooltip title={deptAgreed ? undefined : '先登记部门「同意续签」，才能办理续签'}>
                    <Button disabled={acting || !deptAgreed} onClick={() => setRenewOpen(true)}>办理续签</Button>
                  </Tooltip>
                )}
                {['active', 'renewing'].includes(c.status) && (
                  <Button disabled={acting} onClick={() => setEditOpen(true)}>编辑</Button>
                )}
                {canTerminate && (
                  <Dropdown
                    menu={{
                      items: [
                        {
                          key: 'terminate',
                          label: <span className="text-[var(--color-error)]">终止合同</span>,
                          onClick: () => { setTerminateReason(''); setTerminateOpen(true) },
                        },
                      ],
                    }}
                  >
                    <Button disabled={acting}>
                      更多 <DownOutlined />
                    </Button>
                  </Dropdown>
                )}
              </Space>
            )}

            {live && (
              <div>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-medium text-gray-600">通知记录</span>
                  {canManage && c.status !== 'active' && (
                    <Space size={4}>
                      {deptAgreed && !c.stamped_at && <Button size="small" onClick={() => void resend('renew')}>重发续签通知</Button>}
                      {!!c.stamped_at && !c.delivered_at && <Button size="small" onClick={() => void resend('collect')}>重发领取通知</Button>}
                    </Space>
                  )}
                </div>
                <NoticeList notices={c.notices || []} />
              </div>
            )}

            {c.history.length > 1 && (
              <div>
                <div className="mb-2 text-[13px] font-medium text-gray-600">历次合同（{c.name}）· 点一行切换</div>
                <Table<LaborContract>
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={[...c.history].reverse()}
                  onRow={(r) => ({
                    onClick: () => { if (r.id !== c.id) switchTo(r.id) },
                    style: { cursor: r.id === c.id ? 'default' : 'pointer' },
                  })}
                  columns={[
                    { title: '次序', dataIndex: 'seq_label', width: 130 },
                    { title: '期限', dataIndex: 'term_label', width: 90 },
                    { title: '起止', width: 210, render: (_, r) => `${r.start_date || '-'} ~ ${r.end_date || '无固定'}` },
                    { title: '状态', dataIndex: 'status_label', width: 100 },
                    { title: '领取', width: 84, render: (_, r) => (r.delivered_at ? '已领取' : '-') },
                    {
                      title: '归档', width: 84,
                      render: (_, r) => (
                        <Tag color={r.archive_status === 'archived' ? 'green' : 'orange'}>
                          {r.archive_status === 'archived' ? '已归档' : '未归档'}
                        </Tag>
                      ),
                    },
                  ]}
                />
              </div>
            )}

            {/* 电子档案：扫描件版本 / 上传换版 / 原件调阅留痕（能力由后端按数据范围下发） */}
            <div ref={archiveRef}>
              <ContractArchivePanel
                contractId={c.id}
                archiveStatus={c.archive_status}
                canManage={!!c.can_archive}
                canAccessFile={!!c.can_access_file}
                onChanged={() => {
                  if (currentId) void load(currentId)
                  onChanged()
                }}
              />
            </div>
          </div>
        )}
      </Spin>

      {/* 续签办理 / 编辑：期限按签订次数自动带出，仅确认日期；续签成功后切到新合同 */}
      {c && (
        <ContractFormModal
          open={renewOpen}
          mode="renew"
          contract={c}
          onClose={() => setRenewOpen(false)}
          onSaved={(saved) => {
            setRenewOpen(false)
            onChanged()
            if (saved?.id && saved.id !== c.id) {
              message.success(`续签已办理，已切换到新合同（第 ${saved.seq_no} 份）：接着登记盖章、领取`)
              switchTo(saved.id)
            } else {
              void load(c.id)
            }
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
            void load(c.id)
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

  /** 抽屉内切到另一份合同（续签后的新合同 / 历次合同） */
  function switchTo(id: string) {
    if (!contractId) return
    setSwitched({ from: contractId, to: id })
    setHandoff(null)
  }
}

/** 通知留痕：每条通知发给谁、是否送达；没送达的说明原因 */
function NoticeList({ notices }: { notices: ContractNotice[] }) {
  if (!notices.length) {
    return <div className="text-[13px] text-gray-500">还没有发过通知。</div>
  }
  return (
    <div className="divide-y divide-[var(--color-hairline)] rounded-[var(--rounded-md)] border border-[var(--color-hairline)]">
      {notices.slice(0, 8).map((n, idx) => {
        const meta = noticeStatusMeta(n.status)
        return (
          <div key={`${n.kind}-${n.created_at}-${idx}`} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[13px]">
            <span className="w-[88px] shrink-0 text-gray-500">{fmtTime(n.created_at).slice(0, 16)}</span>
            <span className="w-[92px] shrink-0">{noticeKindLabel(n.kind)}</span>
            <span className="min-w-0 flex-1 truncate text-gray-600">{n.recipient_name || '—'}</span>
            <Tag color={meta.color}>{meta.label}</Tag>
            {n.status !== 'sent' && n.error_message && (
              <Tooltip title={n.error_message}>
                <span className="max-w-[220px] truncate text-[12px] text-[var(--color-steel)]">{n.error_message}</span>
              </Tooltip>
            )}
          </div>
        )
      })}
      {notices.length > 8 && (
        <div className="px-3 py-1.5 text-[12px] text-gray-500">仅显示最近 8 条</div>
      )}
    </div>
  )
}
