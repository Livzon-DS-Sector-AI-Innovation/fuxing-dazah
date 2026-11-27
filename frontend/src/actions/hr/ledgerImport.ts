'use server'

// 台账 Excel 导入（两步预检式）：模板下载 / 预检 / 落库。
// 注意：本文件只 export 函数，类型一律放 types/hr（turbopack 'use server'
// 文件导出类型会被登记进 ACTIONS_MANIFEST，client 引用即整链静默崩溃）。

import type { LedgerImportLedger, LedgerImportPrecheck, LedgerImportResult } from '@/types/hr'
import { fetchHrApi, fetchHrDownload } from './_helpers'

const LEDGER_LABELS: Record<LedgerImportLedger, string> = {
  onboarding: '入职台账',
  contract: '劳动合同',
  departure: '离职台账',
  training: '培训台账',
  incident: '工伤纠纷台账',
}

/** 下载固定列头的导入模板（含一行灰色示例） */
export async function downloadLedgerTemplate(ledger: LedgerImportLedger): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/ledger-import/${ledger}/template`, {
    errorMessage: '下载模板失败',
  })
  return { base64, filename: filename || `${LEDGER_LABELS[ledger]}导入模板.xlsx` }
}

/** 上传文件预检：解析 + 查重，返回统计与明细（不写库） */
export async function precheckLedgerImport(
  ledger: LedgerImportLedger,
  file: File
): Promise<{ data: LedgerImportPrecheck }> {
  const form = new FormData()
  form.append('file', file)
  return fetchHrApi(`/hr/ledger-import/${ledger}/precheck`, {
    method: 'POST',
    body: form,
    errorMessage: '文件解析失败',
  })
}

/** 确认后落库：duplicateMode=overwrite 覆盖重复 / skip 跳过重复 */
export async function commitLedgerImport(
  ledger: LedgerImportLedger,
  file: File,
  duplicateMode: 'overwrite' | 'skip'
): Promise<{ data: LedgerImportResult; message: string }> {
  const form = new FormData()
  form.append('file', file)
  form.append('duplicate_mode', duplicateMode)
  return fetchHrApi(`/hr/ledger-import/${ledger}/commit`, {
    method: 'POST',
    body: form,
    errorMessage: '导入失败',
  })
}
