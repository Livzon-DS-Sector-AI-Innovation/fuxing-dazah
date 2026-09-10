'use client'

import React, { useState, useCallback, useRef, useEffect } from 'react'
import { App, Button, Drawer, Empty, Space, Spin, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  InboxOutlined,
  FileWordOutlined,
  ThunderboltOutlined,
  EyeOutlined,
  CloseOutlined,
  LoadingOutlined,
  FileTextOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { getRegulations, retryAiReview } from '@/actions/safety'
import type { OperationRegulation } from '@/types/safety'
import type { AiReviewNote } from '@/types/safety'
import {
  actionLink,
  pillInfo,
  pillDefault,
  pillSuccess,
  pillError,
  pillWarning,
  pillPurple,
  pillNeutral,
  T,
} from '@/components/safety/shared-styles'
import dayjs from 'dayjs'
import animStyles from './safety-animations.module.css'

const { Text } = Typography

/* ─────── helpers ─────── */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** AI 审核状态 → 中文标签 + 颜色 pill */
function aiReviewStatusMeta(status?: string): { label: string; style: React.CSSProperties } {
  switch (status) {
    case 'reviewing':
      return { label: '审核中', style: pillInfo }
    case 'completed':
      return { label: '已审核', style: pillSuccess }
    case 'failed':
      return { label: '审核失败', style: pillError }
    case 'pending':
    default:
      return { label: '待审核', style: pillDefault }
  }
}

/** 审核维度结论 → 状态 pill */
function dimStatusMeta(status?: string): { label: string; style: React.CSSProperties } {
  switch (status) {
    case 'pass':
      return { label: '通过', style: pillSuccess }
    case 'fail':
      return { label: '不通过', style: pillError }
    case 'warn':
    default:
      return { label: '需关注', style: pillWarning }
  }
}

/** 章节修正动作 → 标签 */
function fixActionMeta(action?: string): { label: string; style: React.CSSProperties } {
  switch (action) {
    case 'rewrite':
      return { label: '重写', style: pillPurple }
    case 'append':
      return { label: '追加', style: pillInfo }
    case 'keep':
    default:
      return { label: '保留', style: pillNeutral }
  }
}

/** 排版布局问题严重度 → 标签 */
function layoutSeverityMeta(severity?: string): { label: string; style: React.CSSProperties } {
  switch (severity) {
    case 'fail':
      return { label: '严重', style: pillError }
    case 'warn':
    default:
      return { label: '轻微', style: pillWarning }
  }
}

/* ─────── component ─────── */

interface SopGeneratorPanelProps {
  onOpenEditor: (regulation: OperationRegulation) => void
  onGenerated: (result: {
    regulation_id: string
    meta: Record<string, string>
    content: string
  }) => void
}

export default function SopGeneratorPanel({
  onOpenEditor,
  onGenerated,
}: SopGeneratorPanelProps) {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [generatedSops, setGeneratedSops] = useState<OperationRegulation[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [reviewTarget, setReviewTarget] = useState<OperationRegulation | null>(null)
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { message } = App.useApp()

  const loadGeneratedSops = useCallback(async () => {
    setLoadingList(true)
    try {
      const response = await getRegulations({
        page: 1,
        page_size: 200,
        status: 'generated,ai_reviewed',
      })
      if (response.code === 200) {
        setGeneratedSops(response.data as OperationRegulation[])
      }
    } catch {
      // silent
    } finally {
      setLoadingList(false)
    }
  }, [])

  useEffect(() => {
    loadGeneratedSops()
  }, [loadGeneratedSops])

  /* ── AI 审核重试 ── */

  const handleRetryReview = useCallback(async (record: OperationRegulation) => {
    setRetryingId(record.id)
    try {
      const response = await retryAiReview(record.id)
      if (response.code === 200) {
        message.success('已重新触发 AI 审核，请稍后刷新查看结果')
      } else {
        message.error(response.message || '重试失败')
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '重试失败')
    } finally {
      setRetryingId(null)
    }
  }, [message])

  /* ── file handling ── */

  const acceptFile = useCallback((f: File) => {
    setErrorMsg(null)
    if (!f.name.endsWith('.docx')) {
      setErrorMsg('仅支持 .docx 格式的操规初稿文件')
      return
    }
    if (f.size > 20 * 1024 * 1024) {
      setErrorMsg('文件大小不能超过 20MB')
      return
    }
    setFile(f)
  }, [])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0]
      if (f) acceptFile(f)
      e.target.value = ''
    },
    [acceptFile],
  )

  const handleRemoveFile = useCallback(() => {
    setFile(null)
    setErrorMsg(null)
  }, [])

  /* ── drag & drop ── */

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragOver(false)
      const f = e.dataTransfer.files?.[0]
      if (f) acceptFile(f)
    },
    [acceptFile],
  )

  /* ── generate ── */

  const handleGenerate = async () => {
    if (!file) {
      message.warning('请先选择操规初稿文件 (.docx)')
      return
    }

    setUploading(true)
    setErrorMsg(null)
    try {
      const { generateSop } = await import('@/actions/safety')
      const response = await generateSop(file)

      if (response.code && response.code !== 200) {
        setErrorMsg(response.message || '生成失败，请重试')
        return
      }

      const result = response.data
      onGenerated({
        regulation_id: result.regulation_id,
        meta: result.meta || {},
        content: result.content || '',
      })
      setFile(null)
      loadGeneratedSops()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '生成失败，请重试'
      setErrorMsg(msg)
    } finally {
      setUploading(false)
    }
  }

  /* ── status rendering ── */

  const renderStatus = (status: string | undefined) => {
    switch (status) {
      case 'generated':
        return <span style={pillInfo}>待审核</span>
      case 'ai_reviewed':
        return <span style={pillSuccess}>已AI审核</span>
      default:
        return <span style={pillDefault}>{status || '草稿'}</span>
    }
  }

  /* ── table columns ── */

  const $purple = actionLink('#5645d4')
  const $danger = actionLink('#e03131')

  const columns: ColumnsType<OperationRegulation> = [
    {
      title: '操规编号',
      dataIndex: 'regulation_no',
      key: 'regulation_no',
      width: 140,
      render: (no: string) => (
        <span style={{ fontFamily: '"JetBrains Mono", "SF Mono", monospace', fontSize: 13, color: T.slate }}>
          {no}
        </span>
      ),
    },
    {
      title: '操规名称',
      dataIndex: 'regulation_name',
      key: 'regulation_name',
      width: 220,
      ellipsis: true,
    },
    {
      title: '所属岗位',
      dataIndex: 'position',
      key: 'position',
      width: 100,
      render: (pos: string) => pos || '-',
    },
    {
      title: '内容状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => renderStatus(status),
    },
    {
      title: 'AI 审核',
      dataIndex: 'ai_review_status',
      key: 'ai_review_status',
      width: 96,
      render: (status: string, record) => {
        const meta = aiReviewStatusMeta(status)
        return (
          <Space size={6}>
            <span style={meta.style}>{meta.label}</span>
            {status === 'completed' && record.ai_review_note && (
              <span
                role="button"
                style={$purple}
                onClick={() => setReviewTarget(record)}
              >
                <EyeOutlined />详情
              </span>
            )}
          </Space>
        )
      },
    },
    {
      title: '内容长度',
      dataIndex: 'content',
      key: 'content_length',
      width: 90,
      render: (content: string | undefined) => {
        const chars = content ? content.replace(/\s/g, '').length : 0
        return (
          <Text style={{ fontSize: 13, color: T.steel }}>
            {chars.toLocaleString()} 字
          </Text>
        )
      },
    },
    {
      title: '生成时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 120,
      render: (date: string) =>
        date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_, record) => (
        <Space size={10}>
          <span role="button" style={$purple} onClick={() => onOpenEditor(record)}>
            <EyeOutlined />编辑审阅
          </span>
          {record.ai_review_status === 'failed' && (
            <span role="button" style={$danger} onClick={() => handleRetryReview(record)}>
              {retryingId === record.id ? <LoadingOutlined /> : <ReloadOutlined />}重试
            </span>
          )}
        </Space>
      ),
    },
  ]

  /* ── render ── */

  return (
    <App>
    <div>
      {/* ═══ Upload Section ═══ */}
      <div
        style={{
          background: T.canvas,
          border: `1px solid ${T.hairline}`,
          borderRadius: 12,
          padding: '28px 32px',
          marginBottom: 24,
        }}
      >
        {/* Section header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 14,
            marginBottom: 20,
          }}
        >
          <div
            style={{
              width: 42,
              height: 42,
              borderRadius: 10,
              background: T.canvas,
              border: `1px solid ${T.hairline}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <ThunderboltOutlined style={{ fontSize: 20, color: T.primary }} />
          </div>
          <div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 600,
                color: T.ink,
                lineHeight: 1.4,
                marginBottom: 2,
              }}
            >
              上传旧版操规生成标准化版本
            </div>
            <div style={{ fontSize: 13, color: T.steel, lineHeight: 1.5 }}>
              上传 .docx 格式的操规初稿，AI 将自动分析工艺步骤并生成 9 章标准化安全操作规程
            </div>
          </div>
        </div>

        {/* Error banner */}
        {errorMsg && (
          <div
            style={{
              background: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: 8,
              padding: '10px 16px',
              color: '#e03131',
              fontSize: 13,
              fontWeight: 500,
              marginBottom: 16,
            }}
          >
            {errorMsg}
          </div>
        )}

        {/* Upload area or generating state */}
        {uploading ? (
          <div
            style={{
              background: T.canvas,
              border: `1px solid ${T.hairline}`,
              borderRadius: 12,
              padding: '48px 24px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 16,
            }}
          >
            <div
              className={animStyles.pulse16}
              style={{
                width: 64,
                height: 64,
                borderRadius: 9999,
                background: 'rgba(86,69,212,0.08)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <LoadingOutlined style={{ fontSize: 28, color: T.primary }} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 500, color: T.charcoal }}>
              AI 正在分析工艺步骤并生成标准化操规...
            </div>
            <Text style={{ fontSize: 13, color: T.steel }}>
              预计需要 5-10 秒，请耐心等待
            </Text>
          </div>
        ) : file ? (
          /* file selected */
          <div
            style={{
              background: T.canvas,
              border: `1px solid ${T.hairline}`,
              borderRadius: 12,
              padding: '24px 28px',
              display: 'flex',
              alignItems: 'center',
              gap: 16,
            }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: 10,
                background: T.surface,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                boxShadow: '0px 1px 2px rgba(15,15,15,0.04)',
              }}
            >
              <FileWordOutlined style={{ fontSize: 26, color: '#2b579a' }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 15,
                  fontWeight: 500,
                  color: T.ink,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  marginBottom: 2,
                }}
              >
                {file.name}
              </div>
              <div style={{ fontSize: 13, color: T.slate }}>
                {formatFileSize(file.size)} · 已就绪
              </div>
            </div>
            <button
              onClick={handleRemoveFile}
              style={{
                width: 32,
                height: 32,
                borderRadius: 9999,
                border: 'none',
                background: 'transparent',
                color: T.steel,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 16,
              }}
              title="移除文件"
            >
              <CloseOutlined />
            </button>
          </div>
        ) : (
          /* empty drop zone */
          <div
            style={{
              background: T.canvas,
              border: `2px dashed ${isDragOver ? T.primary : T.hairline}`,
              borderRadius: 12,
              padding: '48px 24px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 10,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <InboxOutlined
              style={{
                fontSize: 40,
                color: T.primary,
                opacity: isDragOver ? 1 : 0.8,
                transition: 'opacity 0.2s ease',
              }}
            />
            <div style={{ fontSize: 16, fontWeight: 600, color: T.charcoal }}>
              点击上传或拖拽 .docx 文件到此区域
            </div>
            <div style={{ fontSize: 13, color: T.muted }}>
              支持 .docx 格式操规初稿，最大 20MB
            </div>
          </div>
        )}

        {/* Action button row */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            marginTop: 20,
          }}
        >
          <Button
            icon={<ThunderboltOutlined />}
            loading={uploading}
            disabled={!file || uploading}
            onClick={handleGenerate}
            style={{
              height: 40,
              paddingLeft: 24,
              paddingRight: 24,
              fontSize: 14,
              fontWeight: 600,
              borderRadius: 8,
              background: T.canvas,
              borderColor: T.primary,
              color: T.primary,
              boxShadow: 'none',
            }}
          >
            {uploading ? '正在生成...' : '开始生成标准化操规'}
          </Button>
        </div>

        {/* hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".docx"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />

        {/* pulse animation now via safety-animations.module.css */}
      </div>

      {/* ═══ Generated SOPs List ═══ */}
      <div
        style={{
          background: T.canvas,
          border: `1px solid ${T.hairline}`,
          borderRadius: 12,
          overflow: 'hidden',
        }}
      >
        {/* list header */}
        <div
          style={{
            padding: '14px 24px',
            borderBottom: `1px solid ${T.hairlineSoft}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileTextOutlined style={{ fontSize: 15, color: T.primary }} />
            <span style={{ fontSize: 15, fontWeight: 600, color: T.ink }}>
              已生成 / 已审核的标准化操规
            </span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: T.steel,
                background: T.surface,
                padding: '2px 10px',
                borderRadius: 9999,
              }}
            >
              {generatedSops.length}
            </span>
          </div>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={loadGeneratedSops}
            loading={loadingList}
            style={{
              fontSize: 13,
              color: T.steel,
              border: `1px solid ${T.hairline}`,
              borderRadius: 8,
              fontWeight: 500,
            }}
          >
            刷新列表
          </Button>
        </div>

        {/* table */}
        {loadingList ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 64 }}>
            <Spin size="medium" />
          </div>
        ) : generatedSops.length === 0 ? (
          <div style={{ padding: 64 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span style={{ color: T.muted, fontSize: 13 }}>
                  还没有待审核的标准化操规
                  <br />
                  上传旧版操规初稿即可开始生成
                </span>
              }
            />
          </div>
        ) : (
          <Table
            columns={columns}
            dataSource={generatedSops}
            rowKey="id"
            size="small"
            pagination={{
              pageSize: 10,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条`,
            }}
            scroll={{ x: 980 }}
          />
        )}
      </div>

      {/* ═══ AI 审核详情抽屉 ═══ */}
      <Drawer
        open={!!reviewTarget}
        onClose={() => setReviewTarget(null)}
        width={620}
        title={
          reviewTarget ? (
            <Space size={8}>
              <RobotOutlined style={{ color: T.primary }} />
              <span style={{ fontWeight: 600 }}>
                AI 审核详情 · {reviewTarget.regulation_no}
              </span>
              <span style={aiReviewStatusMeta(reviewTarget.ai_review_status).style}>
                {aiReviewStatusMeta(reviewTarget.ai_review_status).label}
              </span>
            </Space>
          ) : null
        }
      >
        {reviewTarget && reviewTarget.ai_review_note
          ? (() => {
              const note = reviewTarget.ai_review_note as AiReviewNote
              return (
                <div style={{ fontSize: 13 }}>
                  {/* 审核时间 */}
                  {note.reviewed_at && (
                    <div style={{ color: T.muted, marginBottom: 14 }}>
                      审核完成于 {dayjs(note.reviewed_at).format('YYYY-MM-DD HH:mm')}
                    </div>
                  )}

                  {/* 总体结论 */}
                  <div style={{ fontWeight: 600, color: T.ink, marginBottom: 6 }}>
                    总体结论
                  </div>
                  <div
                    style={{
                      background: T.canvas,
                      border: `1px solid ${T.hairlineSoft}`,
                      borderRadius: 8,
                      padding: '10px 14px',
                      color: T.charcoal,
                      lineHeight: 1.7,
                      marginBottom: 20,
                    }}
                  >
                    {note.summary || '—'}
                  </div>

                  {/* 分维度结论 */}
                  <div style={{ fontWeight: 600, color: T.ink, marginBottom: 8 }}>
                    分维度审核结论
                  </div>
                  <div style={{ marginBottom: 20 }}>
                    {(note.dimensions || []).map((dim) => {
                      const meta = dimStatusMeta(dim.status)
                      return (
                        <div
                          key={dim.dimension}
                          style={{
                            border: `1px solid ${T.hairlineSoft}`,
                            borderRadius: 8,
                            padding: '10px 14px',
                            marginBottom: 8,
                            background: T.canvas,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                            <span style={{ fontWeight: 600, color: T.charcoal, fontSize: 13 }}>
                              {dim.dimension}
                            </span>
                            <span style={meta.style}>{meta.label}</span>
                          </div>
                          <div style={{ color: T.steel, lineHeight: 1.6 }}>
                            {dim.detail || '—'}
                          </div>
                        </div>
                      )
                    })}
                    {(note.dimensions || []).length === 0 && (
                      <div style={{ color: T.muted }}>无维度结论</div>
                    )}
                  </div>

                  {/* 排版布局问题（视觉审核） */}
                  {((note.layout_issues || []).length > 0 || note.layout_summary) && (
                    <>
                      <div style={{ fontWeight: 600, color: T.ink, marginBottom: 8 }}>
                        排版布局问题
                      </div>
                      {note.layout_summary && (
                        <div
                          style={{
                            background: T.canvas,
                            border: `1px solid ${T.hairlineSoft}`,
                            borderRadius: 8,
                            padding: '10px 14px',
                            color: T.charcoal,
                            lineHeight: 1.7,
                            marginBottom: 8,
                          }}
                        >
                          {note.layout_summary}
                        </div>
                      )}
                      <div style={{ marginBottom: 20 }}>
                        {(note.layout_issues || []).map((issue, idx) => {
                          const meta = layoutSeverityMeta(issue.severity)
                          return (
                            <div
                              key={`${issue.page}-${issue.issue_type}-${idx}`}
                              style={{
                                border: `1px solid ${T.hairlineSoft}`,
                                borderRadius: 8,
                                padding: '10px 14px',
                                marginBottom: 8,
                                background: T.canvas,
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                <span style={{ fontWeight: 600, color: T.charcoal, fontSize: 13 }}>
                                  第 {issue.page} 页
                                </span>
                                <span style={{ color: T.steel, fontSize: 12 }}>{issue.issue_type}</span>
                                <span style={meta.style}>{meta.label}</span>
                              </div>
                              <div style={{ color: T.steel, lineHeight: 1.6 }}>
                                {issue.description}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  )}

                  {/* 章节修正建议 */}
                  <div style={{ fontWeight: 600, color: T.ink, marginBottom: 8 }}>
                    章节修正建议
                  </div>
                  {(note.chapter_fixes || []).map((fix) => {
                    const meta = fixActionMeta(fix.action)
                    return (
                      <div
                        key={fix.chapter}
                        style={{
                          border: `1px solid ${T.hairlineSoft}`,
                          borderRadius: 8,
                          padding: '10px 14px',
                          marginBottom: 8,
                          background: T.canvas,
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <span style={{ fontWeight: 600, color: T.charcoal, fontSize: 13 }}>
                            第 {fix.chapter} 章 · {fix.title || ''}
                          </span>
                          <span style={meta.style}>{meta.label}</span>
                        </div>
                        {fix.note && (
                          <div style={{ color: T.steel, lineHeight: 1.6, marginTop: 2 }}>
                            {fix.note}
                          </div>
                        )}
                      </div>
                    )
                  })}
                  {(note.chapter_fixes || []).length === 0 && (
                    <div style={{ color: T.muted }}>无章节修正建议</div>
                  )}
                </div>
              )
            })()
          : (
            <div style={{ color: T.muted, padding: 24, textAlign: 'center' }}>
              暂无 AI 审核说明
            </div>
          )}
      </Drawer>
    </div>
    </App>
  )
}
