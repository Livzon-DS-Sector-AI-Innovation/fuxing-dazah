'use client'

// 离职办理抽屉：阶段步骤条 + 「当前该动手的环节」操作面板。
// 已完成环节的时间收进步骤条，页面始终只有一处要操作；
// 飞书审批未配置的环节走「站内登记办结」，与接了飞书的环节在同一位置切换提示和按钮。

import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import {
  Alert, App as AntdApp, Button, Descriptions, Drawer, Input, Popconfirm, Space, Spin, Steps, Tag, Typography,
} from 'antd'
import type { OffboardingCase, OffboardingCaseDetail } from '@/types/hr'
import {
  cancelOffboardingCase,
  fetchOffboardingCase,
  manualOffboardingStageDone,
  saveClearanceItems,
  saveOffboardingHandover,
  submitOffboardingApproval,
  submitOffboardingClearance,
} from '@/actions/hr'
import { useHasPermission, useUnsavedConfirm } from '@/hooks/hr'
import {
  clearanceTimingText,
  OFFBOARDING_STATUS_TAG_COLORS,
  signWayLabel,
  STEPPER_STAGES,
  stepperIndex,
} from '@/lib/hr'
import CaseEditModal from './offboarding/CaseEditModal'
import CasePanel, { daysUntil, fmtTime } from './offboarding/CasePanel'
import CertIssuePanel from './offboarding/CertIssuePanel'
import ClearanceTable, { toPayload, toRows, type ClearanceRow } from './offboarding/ClearanceTable'
import ClosePanel from './offboarding/ClosePanel'
import DeliveryPanel from './offboarding/DeliveryPanel'
import HealthCheckPanel, { healthCheckText } from './offboarding/HealthCheckPanel'
import SignatureModal from './offboarding/SignatureModal'

const { Text } = Typography

/** 签收时间：纸质登记与当面手写签名取其一 */
function signedAt(d: OffboardingCaseDetail): string | null | undefined {
  return d.paper_signed_at || d.sign_state?.cert_signed_at
}

/** 步骤条下方的小字：已完成环节显示办结时间，「员工签收」显示签收人。
 *  七步并排每步很窄，时间只显示「月-日 时:分」，完整时间在鼠标悬停的 title 里。 */
function stepNote(d: OffboardingCaseDetail, key: OffboardingCaseDetail['status']): string | undefined {
  // 去掉年份：步骤条里放不下完整时间（按本地时区格式化，直接截 UTC 串会差 8 小时）
  const short = (value: string | null | undefined) => (value ? dayjs(value).format('MM-DD HH:mm') : undefined)
  switch (key) {
    case 'draft':
      // 与其余各步一致只放时间（「发起 11-27 13:33」比别的步骤长，会被截成「发起 11-27 …」）
      return short(d.created_at)
    case 'approving':
      return short(d.resignation_finished_at)
    case 'clearing':
      return short(d.clearance_finished_at)
    case 'cert_issuing':
      return short(d.cert_issued_at)
    case 'delivering':
      return short(d.mail_sent_at || d.sms_sent_at)
    case 'signed':
      return d.sign_state?.cert_sign_name || d.paper_signed_by || undefined
    case 'closed':
      return short(d.closed_at)
    default:
      return undefined
  }
}

export default function OffboardingCaseDrawer({
  open,
  caseId,
  onClose,
  onChanged,
}: {
  open: boolean
  caseId: string | null
  onClose: () => void
  /** 流程推进 / 编辑之后通知外层刷新列表 */
  onChanged: () => void
}) {
  const { message } = AntdApp.useApp()
  // 水合安全的权限判断（本页在 Suspense 边界内）
  const canManage = useHasPermission('hr:departure:manage')

  const [detail, setDetail] = useState<OffboardingCaseDetail | null>(null)
  const [acting, setActing] = useState(false)
  const [rows, setRows] = useState<ClearanceRow[]>([])
  const [rowsDirty, setRowsDirty] = useState(false)
  const [note, setNote] = useState('')
  const [handoverTo, setHandoverTo] = useState('')
  const [deptClerk, setDeptClerk] = useState('')
  const [editOpen, setEditOpen] = useState(false)
  // 员工到人事办公室时在这台电脑上手写签名（签收方式之一）
  const [signatureOpen, setSignatureOpen] = useState(false)
  // 交付阶段没办成的事（开证时邮件失败等）：留在交付面板顶部提醒
  const [deliveryNotes, setDeliveryNotes] = useState<string[]>([])

  // 清退明细改了没保存就关抽屉：先确认（仓库通用 hook，刷新 / 关标签页也会拦）
  const guardClose = useUnsavedConfirm(rowsDirty, onClose, {
    title: '清退明细还没保存',
    content: '关掉后这次修改会丢失。要先保存吗？',
  })

  /** 打开 / 切换单据时加载。setState 全部在 await 之后，不在 effect 里同步触发级联渲染。
   *  message 刻意不进依赖：App.useApp() 每次渲染返回新对象，进依赖会反复加载 */
  useEffect(() => {
    if (!open || !caseId) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchOffboardingCase(caseId)
        if (cancelled) return
        setDetail(r.data)
        setRows(toRows(r.data.clearance_items))
        setRowsDirty(false)
        setNote('')
        setHandoverTo(r.data.handover_to || '')
        setDeptClerk(r.data.dept_clerk || '')
      } catch (e) {
        if (!cancelled) {
          message.error(e instanceof Error ? e.message : '加载办理详情失败')
          onClose()
        }
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, caseId])

  // 只展示当前请求的那一单：抽屉关掉或切到另一单时，旧详情不顶替
  const d = detail && detail.id === caseId ? detail : null
  const status = d?.status
  const stepper = status ? stepperIndex(status) : { current: 0, status: 'process' as const }
  const active = !!d && status !== 'closed' && status !== 'canceled'
  const editable = canManage && !!d && (status === 'draft' || (status === 'approving' && !d.resignation_instance_code))

  /** 执行一个流转动作 → 刷详情 + 通知外层刷新；失败弹错不中断 */
  const act = async (fn: () => Promise<unknown>, successText: string) => {
    if (!d) return
    setActing(true)
    try {
      await fn()
      message.success(successText)
      await reload()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败')
    } finally {
      setActing(false)
    }
  }

  const reload = async () => {
    if (!d) return
    try {
      const r = await fetchOffboardingCase(d.id)
      setDetail(r.data)
      setRows(toRows(r.data.clearance_items))
      setRowsDirty(false)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '刷新办理详情失败')
    }
    onChanged()
  }

  /** 提交部门审批：后端 message 里带「走的是飞书还是站内」和提前天数提示，原样转达 */
  const submit = async () => {
    if (!d) return
    setActing(true)
    try {
      const res = await submitOffboardingApproval(d.id)
      const [head, ...rest] = (res.message || '').split('；')
      if (rest.length) message.warning(`${head}；${rest.join('；')}`, 8)
      else message.success(head || '已提交')
      await reload()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '提交部门审批失败')
    } finally {
      setActing(false)
    }
  }

  /** 保存清退明细（全量替换，保持表格顺序）；名称为空的行先就地拦下 */
  const saveRows = async () => {
    if (!d) return
    if (rows.some((row) => !row.item_name.trim())) throw new Error('有清退事项还没填名称')
    await saveClearanceItems(d.id, toPayload(rows))
    setRowsDirty(false)
  }

  const saveHandover = async () => {
    if (!d) return
    await saveOffboardingHandover(d.id, { handover_to: handoverTo.trim(), dept_clerk: deptClerk.trim() })
  }

  const leadNotice = (() => {
    if (!d || status !== 'draft') return null
    const probation = d.employee_category === '试用期'
    const leadDays = probation ? 3 : 30
    const until = daysUntil(d.offboarding_date)
    if (until.days >= leadDays) return null
    return (
      <Alert
        type="warning"
        showIcon
        title={`${probation ? '试用期员工' : '转正员工'}按制度应提前 ${leadDays} 天发起，当前距离职日${until.text}`}
        description="仍可继续提交，请确认已获批准（协商离职等情形）。"
      />
    )
  })()

  const renderStage = () => {
    if (!d) return null
    switch (status) {
      case 'draft':
        return (
          <CasePanel
            step={1}
            tone={d.health_check_required && !d.health_check_done ? 'warning' : 'default'}
            title="提交部门审批"
            hint={
              d.resignation_feishu
                ? '提交后自动创建飞书审批，由部门负责人在飞书审批；通过后系统自动进入清退会签。'
                : '未接飞书审批：请把离职申请交给部门负责人审批；负责人同意后，在这里登记办结即可进入清退会签。'
            }
            extra={<Tag>{d.approval_track === 'director' ? '总监级流程（M5 及以上）' : '一般员工流程'}</Tag>}
          >
            {d.health_check_required && !d.health_check_done && (
              <>
                <Alert type="warning" showIcon title="重点岗位：须先完成离岗体检登记，才能提交审批" />
                {canManage && <HealthCheckPanel detail={d} onChanged={reload} />}
              </>
            )}
            {leadNotice}
            {canManage && (
              <Button
                type="primary"
                loading={acting}
                disabled={d.health_check_required && !d.health_check_done}
                onClick={() => void submit()}
              >
                提交部门审批
              </Button>
            )}
          </CasePanel>
        )

      case 'approving':
        return (
          <CasePanel
            step={2}
            title="部门审批"
            hint={
              d.resignation_instance_code
                ? '部门负责人在飞书审批；通过后约 15 分钟内自动进入清退会签。'
                : '未接飞书审批：部门负责人同意后，在这里登记办结。'
            }
            extra={<Tag color="processing">审批中</Tag>}
          >
            {d.resignation_instance_code && (
              <Alert
                type="info"
                showIcon
                title="飞书审批进行中"
                description={
                  <span>
                    实例编号 <Text copyable>{d.resignation_instance_code}</Text>
                  </span>
                }
              />
            )}
            {canManage && (
              <>
                {!d.resignation_instance_code && (
                  <Input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="办理说明（可选，如：部门负责人已签字确认）"
                    maxLength={255}
                  />
                )}
                <Popconfirm
                  title="登记部门审批已通过？"
                  description={
                    d.resignation_instance_code
                      ? '登记后不再等待这条飞书审批，请自行在飞书里撤销它。'
                      : '进入清退会签，并带入四部门默认清退清单。'
                  }
                  okText="审批已通过"
                  cancelText="取消"
                  disabled={acting}
                  onConfirm={() =>
                    void act(
                      () => manualOffboardingStageDone(d.id, { stage: 'approving', note: note.trim() || undefined }),
                      '部门审批已办结，进入清退会签',
                    )
                  }
                >
                  <Button type="primary" loading={acting}>
                    {d.resignation_instance_code ? '审批已通过，站内登记办结' : '部门已同意，登记办结'}
                  </Button>
                </Popconfirm>
              </>
            )}
          </CasePanel>
        )

      case 'clearing': {
        const pending = rows.filter((row) => row.status === 'pending').length
        const timing = clearanceTimingText(d.clearance_due_date)
        const handoverDirty =
          handoverTo.trim() !== (d.handover_to || '') || deptClerk.trim() !== (d.dept_clerk || '')
        const clearanceActions = canManage ? (
          <Space wrap>
            <Button
              loading={acting}
              disabled={!rowsDirty}
              onClick={() => void act(saveRows, '清退明细已保存')}
            >
              保存明细
            </Button>
            <Popconfirm
              title="登记会签办结？"
              description={
                pending
                  ? `还有 ${pending} 项是「待确认」，确认各部门已清退完毕？`
                  : '进入证明开具。'
              }
              okText="会签已办结"
              cancelText="取消"
              disabled={acting}
              onConfirm={() =>
                void act(async () => {
                  if (rowsDirty) await saveRows()
                  await manualOffboardingStageDone(d.id, { stage: 'clearing' })
                }, '会签已办结，进入证明开具')
              }
            >
              <Button type="primary" loading={acting}>
                登记会签办结
              </Button>
            </Popconfirm>
            {pending > 0 && (
              <span className="text-[12px] text-[var(--color-steel)]">还有 {pending} 项待确认，可以都确认完再办结</span>
            )}
          </Space>
        ) : null
        return (
          <CasePanel
            step={3}
            title="清退交接会签"
            hint={
              d.clearance_instance_code
                ? '飞书清退会签进行中，办结后自动回读各部门填写的清退明细；也可以先在下面登记。'
                : '行政后勤 / 财务 / 人力资源 / 工作部门逐项确认清退情况，全部完成后登记会签办结。'
            }
            extra={<Tag color="processing">会签中</Tag>}
          >
            {d.clearance_pending && (
              <Alert
                type="info"
                showIcon
                title={`清退交接审批还没发起：${timing || '还没到建议发起日'}`}
                description="按公司规定在离职日前 2 天发起。到期后系统自动发起飞书审批；需要提前办就点下面的按钮。"
                action={canManage ? (
                  <Popconfirm
                    title="提前发起清退交接审批？"
                    description="还没到建议发起日，确定现在就在飞书发起吗？"
                    okText="现在发起"
                    cancelText="再等等"
                    disabled={acting}
                    onConfirm={() => void act(() => submitOffboardingClearance(d.id), '清退交接审批已发起')}
                  >
                    <Button size="small" loading={acting}>提前发起</Button>
                  </Popconfirm>
                ) : undefined}
              />
            )}
            {!d.clearance_instance_code && !d.clearance_pending && d.clearance_feishu && timing && (
              <Alert
                type="info"
                showIcon
                title={`${timing}。`}
                action={canManage ? (
                  <Button size="small" type="primary" loading={acting} onClick={() => void act(() => submitOffboardingClearance(d.id), '清退交接审批已发起')}>
                    发起清退交接审批
                  </Button>
                ) : undefined}
              />
            )}

            <div className="space-y-2">
              <div className="text-[13px] font-medium text-[var(--color-ink)]">交接转办</div>
              <Space wrap>
                <Input
                  value={handoverTo}
                  onChange={(e) => setHandoverTo(e.target.value)}
                  placeholder="交接人（工作交接承接人）"
                  maxLength={64}
                  style={{ width: 200 }}
                  disabled={!canManage}
                  aria-label="交接人"
                />
                <Input
                  value={deptClerk}
                  onChange={(e) => setDeptClerk(e.target.value)}
                  placeholder="部门办事员"
                  maxLength={64}
                  style={{ width: 180 }}
                  disabled={!canManage}
                  aria-label="部门办事员"
                />
                {canManage && (
                  <Button
                    disabled={!handoverDirty}
                    loading={acting}
                    onClick={() => void act(saveHandover, '交接信息已保存')}
                  >
                    保存
                  </Button>
                )}
              </Space>
            </div>

            {/* 默认清单有 20 项，表格很长：操作按钮在表格上下各放一份，不用滚到底才能办结 */}
            {clearanceActions}
            <ClearanceTable
              rows={rows}
              disabled={!canManage}
              onChange={(next) => {
                setRows(next)
                setRowsDirty(true)
              }}
            />
            {clearanceActions}
          </CasePanel>
        )
      }

      case 'cert_issuing':
        return (
          <CertIssuePanel
            detail={d}
            onChanged={reload}
            onIssued={(_data: OffboardingCase, notes: string[]) => {
              // 没办成的事（如邮件发送失败）带到下一步的交付面板里逐条提醒
              setDeliveryNotes(notes)
            }}
          />
        )

      case 'delivering':
        return (
          <DeliveryPanel
            detail={d}
            notes={deliveryNotes}
            onNotesChange={setDeliveryNotes}
            onOpenSignature={() => setSignatureOpen(true)}
            onChanged={reload}
          />
        )

      case 'signed':
        return canManage ? (
          <ClosePanel detail={d} onChanged={reload} />
        ) : (
          <CasePanel step={7} stepLabel="最后一步" title="办结收尾" hint="员工已签字确认，等待 HR 确认账号注销后办结。" />
        )

      case 'closed':
        return (
          <CasePanel step={7} stepLabel="回顾" tone="muted" title="已办结" hint="档案与各台账已同步，无需再操作。" extra={<Tag color="success">已办结</Tag>}>
            <Descriptions
              size="small"
              bordered
              column={2}
              items={[
                { key: 'closed', label: '办结时间', children: fmtTime(d.closed_at) },
                { key: 'account', label: '飞书账号', children: d.account_deactivated ? '已注销' : '未确认注销' },
                { key: 'sign', label: '签收方式', children: signWayLabel(d.delivery_channel) },
                { key: 'signer', label: '签收人 / 时间', children: `${d.sign_state?.cert_sign_name || d.paper_signed_by || '—'} · ${fmtTime(signedAt(d))}` },
                { key: 'cert', label: '证明开具', children: `${fmtTime(d.cert_issued_at)}${d.cert_issued_by ? ` · ${d.cert_issued_by}` : ''}` },
                { key: 'issuer', label: '发起', children: `${d.initiator_name || '—'} · ${fmtTime(d.created_at)}` },
                ...(d.handover_to || d.dept_clerk
                  ? [{ key: 'handover', label: '交接转办', children: [d.handover_to, d.dept_clerk].filter(Boolean).join(' / ') }]
                  : []),
              ]}
            />
          </CasePanel>
        )

      case 'canceled':
        return (
          <Alert
            type="info"
            showIcon
            title="该离职办理已取消"
            description={`${d.remark ? `备注：${d.remark}。` : ''}如仍需办理，请重新发起。`}
          />
        )

      default:
        return null
    }
  }

  return (
    <Drawer
      open={open}
      onClose={guardClose}
      size={960}
      title={d ? `离职办理 · ${d.name}` : '离职办理'}
      extra={
        d && (
          <Space>
            <Tag color={OFFBOARDING_STATUS_TAG_COLORS[status || ''] || 'default'}>{d.status_label}</Tag>
            {editable && <Button size="small" onClick={() => setEditOpen(true)}>编辑信息</Button>}
            {canManage && active && (
              <Popconfirm
                title="取消该离职办理？"
                description="取消后流程终止；如仍需办理要重新发起。"
                okText="取消办理"
                okButtonProps={{ danger: true }}
                cancelText="再想想"
                disabled={acting}
                onConfirm={() => void act(() => cancelOffboardingCase(d.id), '已取消')}
              >
                <Button danger size="small" loading={acting}>取消办理</Button>
              </Popconfirm>
            )}
          </Space>
        )
      }
    >
      <Spin spinning={!!caseId && !d}>
        {d && (
          <div className="space-y-5">
            <Steps
              size="small"
              current={stepper.current}
              status={stepper.status}
              items={STEPPER_STAGES.map((stage) => {
                // 说明文字超宽时省略，别把步骤标题挤得折行；完整内容放 title
                const note = stepNote(d, stage.key)
                return {
                  title: stage.title,
                  content: note ? (
                    <span className="block max-w-[88px] truncate" title={note}>
                      {note}
                    </span>
                  ) : undefined,
                }
              })}
            />

            <Descriptions
              size="small"
              bordered
              column={2}
              items={[
                { key: 'emp', label: '员工', children: `${d.name}（${d.employee_number}）` },
                { key: 'dept', label: '部门 / 岗位', children: `${d.department} / ${d.position || '-'}` },
                {
                  key: 'date',
                  label: '离职日期',
                  children: (
                    <Space size={4}>
                      <span>{d.offboarding_date}（{daysUntil(d.offboarding_date).text}）</span>
                      {d.ledger_synced && <Tag>飞书离职表</Tag>}
                    </Space>
                  ),
                },
                { key: 'type', label: '离职类型', children: d.offboarding_type },
                { key: 'reason', label: '离职原因', children: d.reason || '-' },
                { key: 'category', label: '用工类型', children: d.employee_category || '-' },
                { key: 'submitted', label: '离职申请', children: d.application_submitted ? '已递交' : '未递交' },
                { key: 'initiator', label: '发起', children: `${d.initiator_name || '—'} · ${fmtTime(d.created_at)}` },
                ...(d.health_check_required
                  ? [{ key: 'health', label: '离岗体检', children: healthCheckText(d) }]
                  : []),
                ...(d.remark ? [{ key: 'remark', label: '备注', children: d.remark }] : []),
              ]}
            />

            {renderStage()}
          </div>
        )}
      </Spin>

      {d && editable && (
        <CaseEditModal open={editOpen} detail={d} onClose={() => setEditOpen(false)} onSaved={reload} />
      )}
      {d && status === 'delivering' && canManage && (
        <SignatureModal
          open={signatureOpen}
          detail={d}
          onClose={() => setSignatureOpen(false)}
          onChanged={reload}
        />
      )}
    </Drawer>
  )
}
