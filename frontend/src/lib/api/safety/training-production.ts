/**
 * S6 培训生产链（T1-T5）API client —— 七端点薄封装（#7 纯前端接入）。
 *
 * 端点契约以 backend/app/modules/safety/api/training_behavior.py 为准
 * （全部已测、零后端改动）：
 * - POST /training-behavior/demand/generate {year}（重跑替换同年未处理草案）
 * - GET  /training-behavior/demand/drafts?year&status
 * - POST /training-behavior/demand/drafts/{id}/adopt（写 Bitable 计划行）
 * - POST /training-behavior/demand/drafts/{id}/reject
 * - POST /training-behavior/material/generate {record_id, material_type, config?}
 * - GET  /training-behavior/material/{record_id}（产物清单：附件+标记）
 * - POST /training-behavior/record/parse {record_id}（取该行签到表附件首图）
 */
import { apiGet, apiPost, API_BASE_URL } from '@/lib/http-client'

const BASE = API_BASE_URL + '/api/v1/safety/training-behavior'

// ── 链1 年度培训需求草案 ────────────────────────────────────────────

export interface DemandGenerateResult {
  year: number
  summary: string
  count: number
  replaced: number
  statutory_notes: string[]
  sources: Record<string, unknown> & { disconnected?: number }
}

export interface TrainingDemandDraft {
  id: string
  year: number
  position: string
  topic: string
  suggested_hours: number | null
  form: string | null
  audience: string
  basis: string
  is_statutory_gap: boolean
  status: 'draft' | 'adopted' | 'rejected'
  status_label: string
  adopted_record_id: string | null
  created_at: string | null
}

export function generateTrainingDemand(year: number): Promise<DemandGenerateResult> {
  return apiPost(`${BASE}/demand/generate`, { year })
}

export async function fetchTrainingDemandDrafts(
  params?: { year?: number; status?: string },
): Promise<TrainingDemandDraft[]> {
  const sp = new URLSearchParams()
  if (params?.year) sp.set('year', String(params.year))
  if (params?.status) sp.set('status', params.status)
  const qs = sp.toString()
  const data = await apiGet<{ items: TrainingDemandDraft[]; total: number }>(
    `${BASE}/demand/drafts${qs ? '?' + qs : ''}`,
  )
  return data.items
}

export interface AdoptDraftResult {
  draft_id: string
  adopted_record_id: string
  fields: Record<string, unknown>
}

export function adoptTrainingDemandDraft(id: string): Promise<AdoptDraftResult> {
  return apiPost(`${BASE}/demand/drafts/${id}/adopt`)
}

export function rejectTrainingDemandDraft(
  id: string,
): Promise<{ draft_id: string; status: string; status_label: string }> {
  return apiPost(`${BASE}/demand/drafts/${id}/reject`)
}

// ── 链2 课件与试卷生成 ──────────────────────────────────────────────

export type MaterialType = 'lecture' | 'exam' | 'both'

export interface ExamConfig {
  choice_count?: number
  true_false_count?: number
  multi_choice_count?: number
  fill_blank_count?: number
}

export interface GeneratedMaterial {
  material_type: 'lecture' | 'exam'
  file_name: string
  file_token: string
  generated_at: string
  title?: string
  references?: string[]
  knowledge_chars?: number
  total_count?: number
  counts?: Record<string, number>
}

export function generateTrainingMaterial(
  recordId: string,
  materialType: MaterialType,
  config?: ExamConfig,
): Promise<{ record_id: string; material_type: MaterialType; materials: GeneratedMaterial[] }> {
  return apiPost(`${BASE}/material/generate`, {
    record_id: recordId,
    material_type: materialType,
    config,
  })
}

export interface TrainingMaterialList {
  record_id: string
  topic: string
  attachments: { name: string; file_token: string; material_type: 'lecture' | 'exam' | null }[]
  generations: { material_type: 'lecture' | 'exam'; generated_at: string }[]
}

export function fetchTrainingMaterials(recordId: string): Promise<TrainingMaterialList> {
  return apiGet(`${BASE}/material/${recordId}`)
}

// ── 链3 签到/成绩解析（vision 分级回填） ────────────────────────────

export interface TrainingRecordParse {
  doc_type: string
  attendance_count: number | null
  names: string[]
  passed_count: number | null
  scores: Record<string, unknown>[]
  confidence: 'high' | 'medium' | 'low'
  notes?: string
  unrecognized?: string[]
}

export interface ParseRecordResult {
  record_id: string
  parse: TrainingRecordParse
  writeback_keys: string[]
}

export function parseTrainingRecord(recordId: string): Promise<ParseRecordResult> {
  return apiPost(`${BASE}/record/parse`, { record_id: recordId })
}
