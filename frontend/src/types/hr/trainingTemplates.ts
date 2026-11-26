// 培训导出模板（用户自维护）类型 —— 数据源 GET /hr/training-export-templates
// 独立成文件：'use server' 的 actions 文件不能导出类型（turbopack ACTIONS_MANIFEST 陷阱）。

export interface TrainingTemplateMarker {
  /** 标记字面文本（含花括号），如 "{姓名}" */
  name: string
  description: string
  required: boolean
}

export interface TrainingTemplateVersion {
  id: string
  template_key: string
  version_no: number
  is_current: boolean
  file_name: string
  size: number
  remark: string | null
  uploaded_by: string | null
  uploaded_at: string | null
}

export interface TrainingTemplateDef {
  key: string
  name: string
  description: string
  default_file: string
  markers: TrainingTemplateMarker[]
  notes: string[]
  /** 当前生效的自定义版本；null = 使用官方默认模板 */
  custom: TrainingTemplateVersion | null
  version_count: number
}
