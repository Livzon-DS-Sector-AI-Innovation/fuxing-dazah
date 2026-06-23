// ═══════════════════════════════════════════════════════════════
// Special Operations — shared constants
// Used by: SpecialOpsManagement / SpecialOpsReportPanel / SpecialOpsLedger
// ═══════════════════════════════════════════════════════════════

import {
  FireOutlined,
  AlertOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  AimOutlined,
  DropboxOutlined,
  ExpandOutlined,
  CarryOutOutlined,
} from '@ant-design/icons'

// ── DESIGN.md Token Colors ──
export const T = {
  primary: '#5645d4', error: '#E03131', warning: '#DD5B00', success: '#1AAE39',
  ink: '#1a1a1a', charcoal: '#37352f', slate: '#5d5b54', steel: '#787671',
  muted: '#bbb8b1', hairline: '#e5e3df', surface: '#f6f5f4', canvas: '#ffffff',
  sky: '#dcecfa', lavender: '#e6e0f5', peach: '#ffe8d4', rose: '#fde0ec',
  mint: '#d9f3e1', yellow: '#fef7d6',
}

// ── Operation type labels, colors & icons ──
export const OP_TYPE_CONFIG: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  hot_work: { label: '动火作业', color: '#DC2626', bg: '#fef2f2', icon: <FireOutlined /> },
  confined_space: { label: '受限空间', color: '#7C3AED', bg: '#f5f3ff', icon: <DropboxOutlined /> },
  height_work: { label: '高处作业', color: '#2563EB', bg: '#eff6ff', icon: <ExpandOutlined /> },
  temporary_electricity: { label: '临时用电', color: '#D97706', bg: '#fffbeb', icon: <ThunderboltOutlined /> },
  blind_plate: { label: '盲板抽堵', color: '#059669', bg: '#ecfdf5', icon: <AimOutlined /> },
  excavation: { label: '动土作业', color: '#9333EA', bg: '#faf5ff', icon: <ToolOutlined /> },
  lifting: { label: '起重吊装', color: '#0891B2', bg: '#ecfeff', icon: <CarryOutOutlined /> },
  road_breaking: { label: '断路作业', color: '#4F46E5', bg: '#eef2ff', icon: <AlertOutlined /> },
}

export const OP_LEVEL_LABELS: Record<string, string> = {
  special: '特级', grade1: '一级', grade2: '二级', not_applicable: '不涉及',
}

export const OP_LEVEL_OPTIONS = [
  { value: 'special', label: '特级' },
  { value: 'grade1', label: '一级' },
  { value: 'grade2', label: '二级' },
  { value: 'not_applicable', label: '不涉及' },
]

export const STATUS_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  draft: { color: '#787671', bg: '#f6f5f4', label: '草稿' },
  submitted: { color: '#D97706', bg: '#fffbeb', label: '审批中' },
  approved: { color: '#059669', bg: '#ecfdf5', label: '已审批' },
  rejected: { color: '#DC2626', bg: '#fef2f2', label: '已驳回' },
}

export const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'submitted', label: '审批中' },
  { value: 'approved', label: '已审批' },
  { value: 'rejected', label: '已驳回' },
]

export const RISK_LEVEL_OPTIONS = [
  { value: 'level_1', label: '重大风险' },
  { value: 'level_2', label: '较大风险' },
  { value: 'level_3', label: '一般风险' },
  { value: 'level_4', label: '低风险' },
]

// Ordered operation type keys for stats cards
export const OP_TYPE_KEYS = [
  'hot_work', 'confined_space', 'height_work', 'temporary_electricity',
  'blind_plate', 'excavation', 'lifting', 'road_breaking',
]
