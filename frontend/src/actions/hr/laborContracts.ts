'use server'

import { fetchHrApi } from './_helpers'
import type {
  ContractEntryPreview,
  ContractNoticeResult,
  ContractOffboardingHandoff,
  LaborContract,
  LaborContractCreateInput,
  LaborContractDetail,
  LaborContractListParams,
  LaborContractRenewInput,
  LaborContractStats,
  LaborContractUpdateInput,
} from '@/types/hr'

interface PagedEnvelope<T> {
  data: T[]
  meta: { total: number; page: number; page_size: number }
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** 劳动合同台账（分页；status 逗号分隔，expiring_days=公告期视图，todo=「待我处理」口径） */
export async function fetchLaborContracts(
  params: LaborContractListParams
): Promise<PagedEnvelope<LaborContract>> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.keyword) qs.set('keyword', params.keyword)
  if (params.expiring_days) qs.set('expiring_days', String(params.expiring_days))
  if (params.department) qs.set('department', params.department)
  if (params.todo) qs.set('todo', params.todo)
  if (params.include_history) qs.set('include_history', 'true')
  if (params.education) qs.set('education', params.education)
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.page_size ?? 20))
  return fetchHrApi(`/hr/labor-contracts?${qs.toString()}`, {
    errorMessage: '获取劳动合同台账失败',
  })
}

/** 「待我处理」统计（口径与列表 todo 筛选一致） */
export async function fetchLaborContractStats(
  department?: string
): Promise<{ data: LaborContractStats }> {
  const qs = department ? `?department=${encodeURIComponent(department)}` : ''
  return fetchHrApi(`/hr/labor-contracts/stats${qs}`, { errorMessage: '获取合同待办统计失败' })
}

/** 合同详情（含同一员工历次合同、七步进度、通知留痕） */
export async function fetchLaborContractDetail(id: string): Promise<{ data: LaborContractDetail }> {
  return fetchHrApi(`/hr/labor-contracts/${id}`, { errorMessage: '获取合同详情失败' })
}

/** 录入预推：签订次序与期限（缺省按入职日期+期限规则推算） */
export async function fetchContractEntryPreview(
  employeeNumber: string,
  startDate: string,
): Promise<{ data: ContractEntryPreview }> {
  const qs = new URLSearchParams({ employee_number: employeeNumber, start_date: startDate })
  return fetchHrApi(`/hr/labor-contracts/entry-preview?${qs.toString()}`, {
    errorMessage: '签订次序推算失败',
  })
}

/** 录入劳动合同（签订次序按入职日期推算，期限按签订次数自动计算） */
export async function createLaborContract(
  input: LaborContractCreateInput
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
    errorMessage: '录入合同失败',
  })
}

/** 编辑合同（限生效中/续签办理中） */
export async function updateLaborContract(
  id: string,
  input: LaborContractUpdateInput
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
    errorMessage: '保存合同失败',
  })
}

/** 办理续签（生成新合同行，旧行被取代；须先登记部门同意续签）。返回的是新合同 */
export async function renewLaborContract(
  id: string,
  input: LaborContractRenewInput
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/renew`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
    errorMessage: '续签办理失败',
  })
}

/** 登记部门续签意见（部门负责人凭 approve 权限登记；HR 的 manage 可代登记，记录登记人） */
export async function decideLaborContract(
  id: string,
  decision: 'agree' | 'disagree'
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/dept-decision`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ decision }),
    errorMessage: '登记部门意见失败',
  })
}

/** 转入离职办理（到期未续签 / 部门不同意续签）：为员工建离职办理单，返回精简视图供跳转 */
export async function transferLaborContractToOffboarding(
  id: string,
  payload: { offboarding_date?: string | null; reason?: string | null } = {}
): Promise<{ data: ContractOffboardingHandoff; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/transfer-offboarding`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '转入离职办理失败',
  })
}

/** 终止合同（人工终止；原因写台账） */
export async function terminateLaborContract(
  id: string,
  reason?: string
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/terminate`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ reason: reason ?? null }),
    errorMessage: '终止操作失败',
  })
}

/** 标记盖章完成（后端推送领取通知，notice 带送达结果） */
export async function stampLaborContract(
  id: string
): Promise<{ data: LaborContract & { notice?: ContractNoticeResult }; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/stamp`, {
    method: 'POST',
    errorMessage: '标记盖章失败',
  })
}

/** 登记已领取（员工到人事办公室领取合同原件即签收；系统仅内网可达，没有领取后的线上签字） */
export async function deliverLaborContract(
  id: string
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/deliver`, {
    method: 'POST',
    errorMessage: '登记领取失败',
  })
}

/** 重发员工通知（续签通知 / 领取通知） */
export async function resendLaborContractNotice(
  id: string,
  kind: 'renew' | 'collect'
): Promise<{ data: ContractNoticeResult; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/resend-notice`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ kind }),
    errorMessage: '重发通知失败',
  })
}

/** 重新发起飞书审批（撤销/降级后补救） */
export async function reAnnounceLaborContract(
  id: string
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/re-announce`, {
    method: 'POST',
    errorMessage: '重新发起审批失败',
  })
}
