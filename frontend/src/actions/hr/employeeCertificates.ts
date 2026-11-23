'use server'

import { fetchHrApi, fetchHrDownload } from './_helpers'
import type {
  CertificateAccessLog,
  CertificateCategory,
  CertificateRequirement,
  CertificateUploadInput,
  EmployeeCertificate,
  EmployeeCertificatesView,
  MissingCertificateItem,
} from '@/types/hr'

/** 证件台账（当前版本；按部门/类别/姓名检索） */
export async function fetchCertificatesLedger(params: {
  department?: string
  category?: string
  keyword?: string
  current_only?: boolean
  page?: number
  page_size?: number
}): Promise<{ data: EmployeeCertificate[]; meta: { total: number; page: number; page_size: number } }> {
  const qs = new URLSearchParams()
  if (params.department) qs.set('department', params.department)
  if (params.category) qs.set('category', params.category)
  if (params.keyword) qs.set('keyword', params.keyword)
  if (params.current_only === false) qs.set('current_only', 'false')
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.page_size ?? 20))
  return fetchHrApi(`/hr/certificates?${qs.toString()}`, { errorMessage: '获取证件台账失败' })
}

/** 缺件清单（应交未交，HR 催收视图） */
export async function fetchMissingCertificates(department?: string): Promise<{ data: MissingCertificateItem[] }> {
  const qs = department ? `?department=${encodeURIComponent(department)}` : ''
  return fetchHrApi(`/hr/certificates/missing${qs}`, { errorMessage: '获取缺件清单失败' })
}

/** 员工证件视图（六类分组+待补交标注） */
export async function fetchEmployeeCertificates(employeeId: string): Promise<{ data: EmployeeCertificatesView }> {
  return fetchHrApi(`/hr/employees/${employeeId}/certificates`, { errorMessage: '获取员工证件失败' })
}

/** 上传/换证（同类别自动升版本，旧版保留可查） */
export async function uploadEmployeeCertificate(
  employeeId: string,
  input: CertificateUploadInput,
  file: File,
): Promise<{ code: number; message: string; data: EmployeeCertificate }> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('category', input.category)
  if (input.certificate_name) fd.append('certificate_name', input.certificate_name)
  if (input.certificate_no) fd.append('certificate_no', input.certificate_no)
  if (input.issue_date) fd.append('issue_date', input.issue_date)
  if (input.expiry_date) fd.append('expiry_date', input.expiry_date)
  fd.append('is_permanent', String(input.is_permanent ?? false))
  if (input.remark) fd.append('remark', input.remark)
  return fetchHrApi(`/hr/employees/${employeeId}/certificates`, {
    method: 'POST',
    body: fd,
    errorMessage: '上传证件失败',
  })
}

/** 证件原件下载（base64，调阅留审计） */
export async function downloadCertificateFile(certificateId: string): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload(`/hr/certificates/${certificateId}/file?download=true`, { errorMessage: '下载证件失败' })
}

/** 证件原件预览（base64，调阅留审计） */
export async function previewCertificateFile(certificateId: string): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload(`/hr/certificates/${certificateId}/file`, { errorMessage: '获取证件原件失败' })
}

/** 更正证件登记要素 */
export async function updateEmployeeCertificate(
  certificateId: string,
  changes: Partial<CertificateUploadInput>,
): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/certificates/${certificateId}`, {
    method: 'PUT',
    body: JSON.stringify(changes),
    errorMessage: '更正失败',
  })
}

/** 删除证件（软删；当前版本删除后最新历史版本自动顶替） */
export async function deleteEmployeeCertificate(certificateId: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/certificates/${certificateId}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

/** 应交证件清单配置 */
export async function fetchCertificateRequirements(): Promise<{ data: CertificateRequirement[] }> {
  return fetchHrApi('/hr/certificates/requirements', { errorMessage: '获取应交配置失败' })
}

export async function addCertificateRequirement(category: CertificateCategory, appliesTo: 'all' | 'key_position'): Promise<{ code: number; message: string }> {
  return fetchHrApi('/hr/certificates/requirements', {
    method: 'POST',
    body: JSON.stringify({ category, applies_to: appliesTo }),
    errorMessage: '新增应交配置失败',
  })
}

export async function deleteCertificateRequirement(requirementId: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/certificates/requirements/${requirementId}`, {
    method: 'DELETE',
    errorMessage: '删除应交配置失败',
  })
}

/** 证件调阅/操作记录（审计） */
export async function fetchCertificateAccessLogs(params: {
  employee_id?: string
  page?: number
  page_size?: number
}): Promise<{ data: CertificateAccessLog[]; meta: { total: number; page: number; page_size: number } }> {
  const qs = new URLSearchParams()
  if (params.employee_id) qs.set('employee_id', params.employee_id)
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.page_size ?? 20))
  return fetchHrApi(`/hr/certificates/access-logs?${qs.toString()}`, { errorMessage: '获取调阅记录失败' })
}
