'use server'

import { fetchHrApi } from './_helpers'
import type {
  ContractEntryPreview,
  LaborContract,
  LaborContractCreateInput,
  LaborContractDetail,
  LaborContractListParams,
  LaborContractRenewInput,
  LaborContractUpdateInput,
} from '@/types/hr'

interface PagedEnvelope<T> {
  data: T[]
  meta: { total: number; page: number; page_size: number }
}

/** 劳动合同台账（分页；status 逗号分隔，expiring_days=公告期视图） */
export async function fetchLaborContracts(
  params: LaborContractListParams
): Promise<PagedEnvelope<LaborContract>> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.keyword) qs.set('keyword', params.keyword)
  if (params.expiring_days) qs.set('expiring_days', String(params.expiring_days))
  if (params.department) qs.set('department', params.department)
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.page_size ?? 20))
  return fetchHrApi(`/hr/labor-contracts?${qs.toString()}`, {
    errorMessage: '获取劳动合同台账失败',
  })
}

/** 合同详情（含同一员工历次合同） */
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
    headers: { 'Content-Type': 'application/json' },
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    errorMessage: '保存合同失败',
  })
}

/** 办理续签（生成新合同行，旧行被取代） */
export async function renewLaborContract(
  id: string,
  input: LaborContractRenewInput
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/renew`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    errorMessage: '续签办理失败',
  })
}

/** 部门审批（站内勾选；飞书审批由后端轮询回写） */
export async function decideLaborContract(
  id: string,
  decision: 'agree' | 'disagree'
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/dept-decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
    errorMessage: '审批操作失败',
  })
}

/** 终止合同（不同意续签/到期未续签等） */
export async function terminateLaborContract(
  id: string,
  reason?: string
): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/terminate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason: reason ?? null }),
    errorMessage: '终止操作失败',
  })
}

/** 标记盖章完成（后端推送领取通知） */
export async function stampLaborContract(id: string): Promise<{ data: LaborContract; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/stamp`, {
    method: 'POST',
    errorMessage: '标记盖章失败',
  })
}

/** 标记已领取（后端签发签字链接并推送提醒） */
export async function deliverLaborContract(
  id: string
): Promise<{ data: LaborContract & { sign_url?: string }; message: string }> {
  return fetchHrApi(`/hr/labor-contracts/${id}/deliver`, {
    method: 'POST',
    errorMessage: '标记领取失败',
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
