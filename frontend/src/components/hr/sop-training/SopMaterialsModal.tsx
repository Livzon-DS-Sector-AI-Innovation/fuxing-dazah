'use client'

// 生成全套培训材料的评估表统计预填弹窗：培训发起时导出的材料还没有成绩，
// 统计区默认空白；这里可手动填或一键随机生成「全员合格」的统计（不合格恒为 0）。
// 由父组件换 key 重新挂载（与 SopQaGenerateModal 同款约定），打开即初始状态，不用 effect 复位。

import { useState } from 'react'
import { Alert, App, Button, InputNumber, Modal, Space, Typography } from 'antd'
import type { SopEvaluationStats, SopMaterialsPreview } from '@/types/hr'

interface SopMaterialsModalProps {
  open: boolean
  /** 统计基数（父组件调 materials-preview 拉取）；null = 还在加载或拉取失败 */
  base: SopMaterialsPreview | null
  /** 打开时的预填初值（父组件随机生成；配合父组件换 key 重挂载生效） */
  initialStats: SopEvaluationStats | null
  onClose: () => void
  /** 确认导出：stats=null 表示不预填（评估表统计区保持空白） */
  onExport: (stats: SopEvaluationStats | null) => void
  loading: boolean
}

/** 随机口径（用户拍板）：全员实到（应到-病产假），优秀占参加考核人数 20%~60% 随机，其余全合格 */
export function randomStats(base: SopMaterialsPreview): SopEvaluationStats {
  const actual = Math.max(base.expected_count - base.sick_leave - base.maternity_leave, 0)
  const exam = actual
  const excellent = exam > 0
    ? Math.min(Math.max(1, Math.round(exam * (0.2 + Math.random() * 0.4))), exam)
    : 0
  return { actual_count: actual, exam_count: exam, excellent_count: excellent, qualified_count: exam - excellent }
}

export default function SopMaterialsModal({ open, base, initialStats, onClose, onExport, loading }: SopMaterialsModalProps) {
  const { message } = App.useApp()
  // 初值来自父组件（拉到基数后随机好传入）；本组件内「随机/清空」走事件回调
  const [actual, setActual] = useState<number | null>(initialStats?.actual_count ?? null)
  const [exam, setExam] = useState<number | null>(initialStats?.exam_count ?? null)
  const [excellent, setExcellent] = useState<number | null>(initialStats?.excellent_count ?? null)

  const handleRandom = () => {
    if (!base || base.expected_count <= 0) {
      message.warning('还没有参训人员基数（名单为空），无法随机生成')
      return
    }
    const s = randomStats(base)
    setActual(s.actual_count)
    setExam(s.exam_count)
    setExcellent(s.excellent_count)
  }

  const handleClear = () => {
    setActual(null)
    setExam(null)
    setExcellent(null)
  }

  // 合格自动 = 参加考核 - 优秀（防填错，不给输入）
  const qualified = exam !== null && excellent !== null ? Math.max(exam - excellent, 0) : null
  // 表单级校验：有任一数就要求三格齐全且不超基数
  const filled = [actual, exam, excellent].some((v) => v !== null && v > 0)
  let invalid = ''
  if (filled) {
    if (!base) invalid = '统计基数还没加载完成'
    else if (actual === null || exam === null || excellent === null) invalid = '实到 / 参加考核 / 优秀人数请填写完整'
    else if (actual > base.expected_count) invalid = `实到人数不能超过应到人数（${base.expected_count}）`
    else if (exam > actual) invalid = '参加考核人数不能超过实到人数'
    else if (excellent > exam) invalid = '优秀人数不能超过参加考核人数'
  }
  const stats: SopEvaluationStats | null = filled && !invalid
    ? { actual_count: actual!, exam_count: exam!, excellent_count: excellent!, qualified_count: qualified! }
    : null

  const participation = base && stats && base.expected_count > 0
    ? `参与率 ${Math.round((stats.actual_count / base.expected_count) * 100)}%`
    : null

  return (
    <Modal
      title="生成培训材料"
      open={open}
      onCancel={onClose}
      width={480}
      mask={{ closable: false }}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={handleClear}>清空</Button>
          <Button onClick={handleRandom}>随机生成合格数据</Button>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={loading} onClick={() => onExport(stats)}>生成材料</Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        title="统计将写入培训效果评估表；不合格恒为 0（优秀+合格=参加考核）。清空后导出，评估表统计区保持空白。"
        style={{ marginBottom: 16 }}
      />
      <div className="text-[13px] text-[var(--color-steel)] mb-2">
        应到人数 <b className="text-[var(--color-text)]">{base ? base.expected_count : '…'}</b>
        {base && (base.sick_leave > 0 || base.maternity_leave > 0) && (
          <>（名单外另有病假 {base.sick_leave} 人、产假 {base.maternity_leave} 人）</>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        <label className="text-[13px] flex items-center justify-between gap-2">
          实到人数
          <InputNumber
            min={0}
            max={base?.expected_count ?? undefined}
            value={actual}
            onChange={(v) => setActual(v)}
            style={{ width: 120 }}
          />
        </label>
        <label className="text-[13px] flex items-center justify-between gap-2">
          参加考核
          <InputNumber
            min={0}
            max={actual ?? undefined}
            value={exam}
            onChange={(v) => setExam(v)}
            style={{ width: 120 }}
          />
        </label>
        <label className="text-[13px] flex items-center justify-between gap-2">
          优秀人数
          <InputNumber
            min={0}
            max={exam ?? undefined}
            value={excellent}
            onChange={(v) => setExcellent(v)}
            style={{ width: 120 }}
          />
        </label>
        <label className="text-[13px] flex items-center justify-between gap-2 text-[var(--color-steel)]">
          合格人数
          <InputNumber value={qualified} disabled style={{ width: 120 }} />
        </label>
      </div>
      <div className="mt-3 text-[13px]">
        {invalid ? (
          <Typography.Text type="danger">{invalid}</Typography.Text>
        ) : stats && participation ? (
          <span className="text-[var(--color-steel)]">
            将写入：参与率 {Math.round((stats.actual_count / base!.expected_count) * 100)}%、
            合格率 {stats.exam_count > 0 ? '100%' : '—'}、不合格 0 人
          </span>
        ) : (
          <span className="text-[var(--color-steel)]">未填写统计——评估表统计区导出为空白（事后可从培训台账导出带真实成绩的评估表）</span>
        )}
      </div>
    </Modal>
  )
}
