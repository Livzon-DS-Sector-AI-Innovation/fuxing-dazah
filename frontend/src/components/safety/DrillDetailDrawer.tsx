'use client'

import { useState } from 'react'
import { Button, Descriptions, Drawer, Modal, Tag, Tooltip, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { DrillRecord } from '@/types/safety'
import { generateDrillEval } from '@/actions/safety'
import { DRILL_TYPE_UI, REVIEW_STATUS_UI, STAGE_UI, T, UI } from './emergencyDrillConstants'

interface Props {
  open: boolean
  record: DrillRecord | null
  onClose: () => void
  onRefresh?: () => void
}

/** 渲染文件列表 — 本地路径显示可点击文件名，JSON 元数据显示占位名 */
function _renderFiles(files: string[] | undefined | null) {
  if (!files?.length) return '-'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {files.map((f, i) => {
        // 本地文件路径提取文件名
        const parts = f.replace(/\\/g, '/').split('/')
        const displayName = parts[parts.length - 1] || f
        return (
          <a key={i} style={{ fontSize: 13, wordBreak: 'break-all' }}
             href={`/api/v1/safety/files/${encodeURIComponent(f)}`}
             target="_blank" rel="noopener noreferrer"
             title={f}>
            {displayName}
          </a>
        )
      })}
    </div>
  )
}

export default function DrillDetailDrawer({ open, record, onClose, onRefresh }: Props) {
  const [evalGenerating, setEvalGenerating] = useState(false)
  if (!record) return null

  const stage = record.status ? 'review' : record.execution_time ? 'execution' : 'plan'
  const stageUi = STAGE_UI[stage]
  const hasRecordForm = Boolean(record.drill_record_file?.length)

  const handleRegenerateEval = () => {
    Modal.confirm({
      title: '重新生成评估表（AI）',
      content: '将基于当前演练记录表重新生成评估表，新版本会覆盖多维表格中已生成的附件，确认继续？',
      okText: '开始生成',
      cancelText: '取消',
      onOk: async () => {
        setEvalGenerating(true)
        try {
          const res = await generateDrillEval(record.id)
          if (res.code === 200 && res.data) {
            message.success('评估表生成成功')
            onRefresh?.()
          } else {
            message.error(res.message || '评估表生成失败')
          }
        } catch {
          message.error('AI 评估表生成失败')
        } finally {
          setEvalGenerating(false)
        }
      },
    })
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={record.drill_content || '演练详情'}
      width={640}
      styles={{ body: { padding: '16px 24px' } }}
      extra={
        <Tooltip title={hasRecordForm ? '基于演练记录表重新生成评估表（AI）' : '请先上传演练记录表'}>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={evalGenerating}
            disabled={!hasRecordForm}
            onClick={handleRegenerateEval}
            style={{ fontSize: 12 }}
          >
            重新生成评估
          </Button>
        </Tooltip>
      }
    >
      {/* 环节 + 状态 */}
      <div style={{ marginBottom: 20, display: 'flex', gap: 10, alignItems: 'center' }}>
        <Tag style={{ fontSize: 13, padding: '4px 12px', borderRadius: 6, color: stageUi.color, background: stageUi.bg, border: 'none', fontWeight: 600 }}>
          {stageUi.label}
        </Tag>
        {record.status && (
          <Tag style={{ fontSize: 13, padding: '4px 12px', borderRadius: 6, color: REVIEW_STATUS_UI[record.status]?.color, background: REVIEW_STATUS_UI[record.status]?.bg, border: 'none', fontWeight: 600 }}>
            {REVIEW_STATUS_UI[record.status]?.label}
          </Tag>
        )}
      </div>

      {/* ── 计划阶段 ── */}
      <Descriptions title="计划信息" column={2} size="small" bordered style={{ marginBottom: 20 }}>
        <Descriptions.Item label="演练类型">{record.drill_type ? (DRILL_TYPE_UI[record.drill_type]?.label ?? record.drill_type) : '-'}</Descriptions.Item>
        <Descriptions.Item label="部门">{record.department || '-'}</Descriptions.Item>
        <Descriptions.Item label="组织人">{record.organizer || '-'}</Descriptions.Item>
        <Descriptions.Item label="组织人(人员)">{record.organizer_person || '-'}</Descriptions.Item>
        <Descriptions.Item label="参与人员">{record.participants || '-'}</Descriptions.Item>
        <Descriptions.Item label="配合部门">{record.coop_department || '-'}</Descriptions.Item>
        <Descriptions.Item label="课时">{record.duration || '-'}</Descriptions.Item>
        <Descriptions.Item label="计划时间">{record.plan_time || '-'}</Descriptions.Item>
        <Descriptions.Item label="计划日期">{record.plan_time_ref ? dayjs(record.plan_time_ref).format('YYYY-MM-DD') : '-'}</Descriptions.Item>
        <Descriptions.Item label="提醒人员" span={2}>{record.alert_person || '-'}</Descriptions.Item>
        <Descriptions.Item label="备注" span={2}>{record.notes || '-'}</Descriptions.Item>
      </Descriptions>

      {/* ── 实施阶段 ── */}
      <Descriptions title="实施信息" column={2} size="small" bordered style={{ marginBottom: 20 }}>
        <Descriptions.Item label="实施时间">
          {record.execution_time ? dayjs(record.execution_time).format('YYYY-MM-DD') : '未执行'}
        </Descriptions.Item>
        <Descriptions.Item label="演练方案">
          {_renderFiles(record.drill_plan_file)}
        </Descriptions.Item>
        <Descriptions.Item label="签到表">
          {_renderFiles(record.signin_file)}
        </Descriptions.Item>
        <Descriptions.Item label="评估表">
          {_renderFiles(record.eval_form_file)}
        </Descriptions.Item>
        <Descriptions.Item label="评估表（AI）">
          {record.eval_ai_file?.length
            ? _renderFiles(record.eval_ai_file)
            : <span style={{ color: T.muted, fontSize: 12 }}>尚未生成（上传演练记录表后自动生成）</span>}
        </Descriptions.Item>
        <Descriptions.Item label="记录表" span={2}>
          {_renderFiles(record.drill_record_file)}
        </Descriptions.Item>
      </Descriptions>

      {/* ── 复核阶段 ── */}
      <Descriptions title="复核信息" column={2} size="small" bordered>
        <Descriptions.Item label="演练问题" span={2}>{record.issues || '-'}</Descriptions.Item>
        <Descriptions.Item label="整改责任人">{record.rectification_person || '-'}</Descriptions.Item>
        <Descriptions.Item label="确认人">{record.confirmer || '-'}</Descriptions.Item>
        <Descriptions.Item label="复核状态" span={2}>
          {record.status ? (
            <Tag style={{ color: REVIEW_STATUS_UI[record.status]?.color, background: REVIEW_STATUS_UI[record.status]?.bg, border: 'none', fontWeight: 600 }}>
              {REVIEW_STATUS_UI[record.status]?.label}
            </Tag>
          ) : '-'}
        </Descriptions.Item>
      </Descriptions>
    </Drawer>
  )
}
