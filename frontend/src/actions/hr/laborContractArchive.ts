'use server'

import { fetchHrApi, fetchHrDownload } from './_helpers'
import type {
  ContractAccessLog,
  ContractArchiveDepartment,
  ContractArchiveListParams,
  ContractArchiveRow,
  ContractArchiveStats,
  ContractArchiveVersion,
  ContractImportCommitResult,
  ContractImportCommitRow,
  ContractImportOption,
  ContractImportPrecheck,
  DepartureContractFilterOptions,
  DepartureContractListParams,
  DepartureContractProcedureInput,
  DepartureContractView,
  EmployeeContractsView,
  LaborContract,
} from '@/types/hr'

interface PagedEnvelope<T> {
  data: T[]
  meta: { total: number; page: number; page_size: number }
}

interface ArchiveMutation {
  data: { contract: LaborContract; versions: ContractArchiveVersion[] }
  message: string
}

// ─── 电子档案库 ───

/** 档案库台账（归档状态 / 在职离职 / 部门筛选；按部门-工号-签订次数排序） */
export async function fetchContractArchive(
  params: ContractArchiveListParams
): Promise<PagedEnvelope<ContractArchiveRow>> {
  const qs = new URLSearchParams()
  if (params.archive_status) qs.set('archive_status', params.archive_status)
  if (params.population) qs.set('population', params.population)
  if (params.keyword) qs.set('keyword', params.keyword)
  if (params.department) qs.set('department', params.department)
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.page_size ?? 20))
  return fetchHrApi(`/hr/labor-contracts-archive?${qs.toString()}`, { errorMessage: '获取电子档案库失败' })
}

/** 档案库概览（在职/离职 × 未归档/已归档；含是否可归档） */
export async function fetchContractArchiveStats(): Promise<{ data: ContractArchiveStats }> {
  return fetchHrApi('/hr/labor-contracts-archive/stats', { errorMessage: '获取档案库概览失败' })
}

/** 未归档份数按部门（档案库部门下拉） */
export async function fetchContractArchiveDepartments(): Promise<{ data: ContractArchiveDepartment[] }> {
  return fetchHrApi('/hr/labor-contracts-archive/departments', { errorMessage: '获取部门列表失败' })
}

/** 导出补扫清单（未归档合同，按部门分组） */
export async function exportUnarchivedContracts(
  department?: string
): Promise<{ base64: string; filename: string | null }> {
  const qs = department ? `?department=${encodeURIComponent(department)}` : ''
  return fetchHrDownload(`/hr/labor-contracts-archive/export-unarchived${qs}`, {
    errorMessage: '导出补扫清单失败',
  })
}

/** 员工历次合同（员工档案「合同」页签） */
export async function fetchEmployeeContracts(employeeNumber: string): Promise<{ data: EmployeeContractsView }> {
  return fetchHrApi(`/hr/labor-contracts/by-employee/${encodeURIComponent(employeeNumber)}`, {
    errorMessage: '获取员工合同失败',
  })
}

// ─── 扫描件版本 / 上传 / 原件调阅 ───

export async function fetchContractArchiveVersions(contractId: string): Promise<{ data: ContractArchiveVersion[] }> {
  return fetchHrApi(`/hr/labor-contracts/${contractId}/archive/versions`, {
    errorMessage: '获取扫描件版本失败',
  })
}

/** 上传合同扫描件（已有扫描件则升为新版本，旧版保留） */
export async function uploadContractArchive(
  contractId: string,
  file: File,
  remark?: string
): Promise<ArchiveMutation> {
  const fd = new FormData()
  fd.append('file', file)
  if (remark?.trim()) fd.append('remark', remark.trim())
  return fetchHrApi(`/hr/labor-contracts/${contractId}/archive`, {
    method: 'POST',
    body: fd,
    errorMessage: '上传扫描件失败',
  })
}

/** 删除扫描件版本（软删；删当前版时最新历史版本顶替） */
export async function deleteContractArchiveVersion(
  contractId: string,
  versionId: string
): Promise<ArchiveMutation> {
  return fetchHrApi(`/hr/labor-contracts/${contractId}/archive/${versionId}`, {
    method: 'DELETE',
    errorMessage: '删除扫描件版本失败',
  })
}

/** 合同扫描件原件下载（base64，调阅留痕） */
export async function downloadContractArchiveFile(
  contractId: string,
  versionId: string
): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload(
    `/hr/labor-contracts/${contractId}/archive/${versionId}/file?download=true`,
    { errorMessage: '下载扫描件失败' }
  )
}

/** 合同扫描件原件预览（base64，调阅留痕） */
export async function previewContractArchiveFile(
  contractId: string,
  versionId: string
): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload(`/hr/labor-contracts/${contractId}/archive/${versionId}/file`, {
    errorMessage: '获取扫描件原件失败',
  })
}

/** 合同扫描件调阅/下载记录 */
export async function fetchContractAccessLogs(
  contractId: string,
  params?: { page?: number; page_size?: number }
): Promise<PagedEnvelope<ContractAccessLog>> {
  const qs = new URLSearchParams()
  qs.set('page', String(params?.page ?? 1))
  qs.set('page_size', String(params?.page_size ?? 20))
  return fetchHrApi(`/hr/labor-contracts/${contractId}/access-logs?${qs.toString()}`, {
    errorMessage: '获取调阅记录失败',
  })
}

// ─── 批量挂接（存量电子档）───

export async function downloadContractImportTemplate(): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload('/hr/labor-contracts-archive/batch-import/template', {
    errorMessage: '下载导入模板失败',
  })
}

/** 批量挂接补选（姓名/工号搜员工与离职人员，返回其合同清单） */
export async function fetchContractImportOptions(keyword: string): Promise<{ data: ContractImportOption[] }> {
  return fetchHrApi(
    `/hr/labor-contracts-archive/batch-import/options?keyword=${encodeURIComponent(keyword)}`,
    { errorMessage: '搜索员工失败' }
  )
}

/** 批量挂接预检（ZIP：扫描件 + 可选 Excel 清单；附件入服务端暂存） */
export async function precheckContractImport(file: File): Promise<{ data: ContractImportPrecheck }> {
  const fd = new FormData()
  fd.append('file', file)
  return fetchHrApi('/hr/labor-contracts-archive/batch-import/precheck', {
    method: 'POST',
    body: fd,
    errorMessage: '批量挂接预检失败',
  })
}

/** 批量挂接提交（按确认行归档，版本化同单个上传） */
export async function commitContractImport(
  rows: ContractImportCommitRow[]
): Promise<{ data: ContractImportCommitResult }> {
  return fetchHrApi('/hr/labor-contracts-archive/batch-import/commit', {
    method: 'POST',
    body: JSON.stringify({ rows }),
    errorMessage: '批量挂接失败',
  })
}

// ─── 离职合同台账 ───

export async function fetchDepartureContracts(
  params: DepartureContractListParams
): Promise<PagedEnvelope<DepartureContractView>> {
  const qs = new URLSearchParams()
  if (params.department) qs.set('department', params.department)
  if (params.date_from) qs.set('date_from', params.date_from)
  if (params.date_to) qs.set('date_to', params.date_to)
  if (params.termination_type) qs.set('termination_type', params.termination_type)
  if (params.keyword) qs.set('keyword', params.keyword)
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.page_size ?? 20))
  return fetchHrApi(`/hr/departure-contracts?${qs.toString()}`, { errorMessage: '获取离职合同台账失败' })
}

export async function fetchDepartureContractFilterOptions(): Promise<{ data: DepartureContractFilterOptions }> {
  return fetchHrApi('/hr/departure-contracts/filter-options', { errorMessage: '获取筛选项失败' })
}

/** 导出离职人员合同情况说明（与列表同筛选口径） */
export async function exportDepartureContracts(
  params: DepartureContractListParams
): Promise<{ base64: string; filename: string | null }> {
  const qs = new URLSearchParams()
  if (params.department) qs.set('department', params.department)
  if (params.date_from) qs.set('date_from', params.date_from)
  if (params.date_to) qs.set('date_to', params.date_to)
  if (params.termination_type) qs.set('termination_type', params.termination_type)
  if (params.keyword) qs.set('keyword', params.keyword)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return fetchHrDownload(`/hr/departure-contracts/export${suffix}`, { errorMessage: '导出情况说明失败' })
}

/** 维护离职合同台账人工项（终止方式更正 / 审批依据 / 流程单号 / 原件回收状态） */
export async function updateDepartureContractProcedure(
  recordId: string,
  input: DepartureContractProcedureInput
): Promise<{ message: string }> {
  return fetchHrApi(`/hr/departure-records/${recordId}/contract-procedure`, {
    method: 'PUT',
    body: JSON.stringify(input),
    errorMessage: '保存失败',
  })
}

/** 离职人员合同扫描件归档（无合同行时按离职记录合同信息建档） */
export async function archiveDepartureContract(
  recordId: string,
  file: File,
  remark?: string
): Promise<ArchiveMutation> {
  const fd = new FormData()
  fd.append('file', file)
  if (remark?.trim()) fd.append('remark', remark.trim())
  return fetchHrApi(`/hr/departure-records/${recordId}/contract-archive`, {
    method: 'POST',
    body: fd,
    errorMessage: '归档失败',
  })
}
