'use client'

import React, { useState, useRef, useCallback } from 'react'
import { Modal, Button, message, Typography } from 'antd'
import {
  InboxOutlined,
  FileWordOutlined,
  CloseOutlined,
  CheckCircleFilled,
  LoadingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'

import { T } from '@/components/safety/shared-styles'

const { Text } = Typography

/* ─────── local aliases ─────── */

const TOKENS = {
  primary: T.primary,
  primaryPressed: '#4534b3',
  ink: T.ink,
  charcoal: T.charcoal,
  slate: T.slate,
  steel: T.steel,
  muted: T.muted,
  canvas: T.canvas,
  surface: T.surface,
  surfaceSoft: '#fafaf9',
  hairline: T.hairline,
  hairlineSoft: T.hairlineSoft,
  hairlineStrong: '#c8c4be',
  cardTintLavender: T.cardTintLavender,
  brandPurple800: '#391c57',
  linkBlue: '#0075de',
  semanticError: '#e03131',
  inkDeep: '#000000',
  wordBlue: '#2b579a',
} as const

const RADIUS = { md: 8, lg: 12, xl: 16, full: 9999 } as const

/* ─────── component interface ─────── */

interface SopGeneratorModalProps {
  open: boolean
  onClose: () => void
  onGenerated: (result: {
    regulation_id: string
    meta: Record<string, string>
    content: string
  }) => void
}

/* ─────── helpers ─────── */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/* ─────── styles ─────── */

const styles = {
  // thin purple decorative bar at the very top
  accentBar: {
    height: 4,
    background: TOKENS.primary,
    margin: '-24px -24px 0 -24px',
  } as React.CSSProperties,

  // main content container below the accent bar
  content: {
    padding: '32px 24px 0 24px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 0,
  } as React.CSSProperties,

  // large document icon
  docIcon: {
    fontSize: 56,
    color: TOKENS.primary,
    marginBottom: 16,
  } as React.CSSProperties,

  // main title
  title: {
    fontSize: 28,
    fontWeight: 600,
    lineHeight: 1.25,
    color: TOKENS.ink,
    textAlign: 'center',
    marginBottom: 8,
  } as React.CSSProperties,

  // subtitle / description
  subtitle: {
    fontSize: 14,
    fontWeight: 400,
    lineHeight: 1.5,
    color: TOKENS.steel,
    textAlign: 'center',
    maxWidth: 480,
    marginBottom: 20,
  } as React.CSSProperties,

  // step badge
  stepBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    background: TOKENS.canvas,
    border: `1px solid ${TOKENS.hairline}`,
    color: TOKENS.brandPurple800,
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.4,
    padding: '4px 12px',
    borderRadius: RADIUS.md,
    marginBottom: 24,
  } as React.CSSProperties,

  // upload drop zone (empty state)
  dropZone: {
    width: '100%',
    height: 200,
    background: TOKENS.canvas,
    border: `2px dashed ${TOKENS.hairlineStrong}`,
    borderRadius: RADIUS.lg,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    cursor: 'pointer',
    transition: 'all 0.2s ease',
    padding: '40px 24px',
  } as React.CSSProperties,

  dropZoneHover: {
    borderColor: TOKENS.primary,
    background: '#dcd4f5',
  } as React.CSSProperties,

  dropIcon: {
    fontSize: 44,
    color: TOKENS.primary,
    opacity: 0.85,
    transition: 'opacity 0.2s ease',
  } as React.CSSProperties,

  dropTitle: {
    fontSize: 18,
    fontWeight: 600,
    lineHeight: 1.4,
    color: TOKENS.charcoal,
  } as React.CSSProperties,

  dropSubtitle: {
    fontSize: 14,
    fontWeight: 400,
    lineHeight: 1.5,
    color: TOKENS.steel,
  } as React.CSSProperties,

  dropHint: {
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 1.4,
    color: TOKENS.muted,
    marginTop: 4,
  } as React.CSSProperties,

  // file card (when file is selected)
  fileCard: {
    width: '100%',
    background: TOKENS.canvas,
    border: `1px solid ${TOKENS.hairline}`,
    borderRadius: RADIUS.lg,
    padding: '20px 24px',
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    boxShadow: '0px 1px 2px 0px rgba(15,15,15,0.04)',
  } as React.CSSProperties,

  fileIconWrap: {
    width: 52,
    height: 52,
    borderRadius: RADIUS.md,
    background: '#e8f0fe',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  } as React.CSSProperties,

  fileIcon: {
    fontSize: 30,
    color: TOKENS.wordBlue,
  } as React.CSSProperties,

  fileInfo: {
    flex: 1,
    minWidth: 0,
  } as React.CSSProperties,

  fileName: {
    fontSize: 16,
    fontWeight: 500,
    lineHeight: 1.4,
    color: TOKENS.ink,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    marginBottom: 4,
  } as React.CSSProperties,

  fileMeta: {
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 1.4,
    color: TOKENS.slate,
  } as React.CSSProperties,

  removeBtn: {
    width: 32,
    height: 32,
    borderRadius: RADIUS.full,
    border: 'none',
    background: 'transparent',
    color: TOKENS.steel,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 16,
    flexShrink: 0,
    transition: 'all 0.15s ease',
  } as React.CSSProperties,

  // generating overlay
  generatingOverlay: {
    width: '100%',
    padding: '32px 24px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 20,
    opacity: 0.7,
  } as React.CSSProperties,

  generatingPulse: {
    width: 64,
    height: 64,
    borderRadius: RADIUS.full,
    background: 'rgba(86,69,212,0.08)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
    animation: 'pulseRing 2s ease-in-out infinite',
  } as React.CSSProperties,

  generatingText: {
    fontSize: 16,
    fontWeight: 500,
    lineHeight: 1.55,
    color: TOKENS.charcoal,
  } as React.CSSProperties,

  // footer
  footer: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '24px 0 0 0',
  } as React.CSSProperties,

  // error banner
  errorBanner: {
    width: '100%',
    background: '#fef2f2',
    border: `1px solid #fecaca`,
    borderRadius: RADIUS.md,
    padding: '10px 16px',
    color: TOKENS.semanticError,
    fontSize: 13,
    fontWeight: 500,
    lineHeight: 1.5,
    marginBottom: 20,
  } as React.CSSProperties,
}

/* ─────── component ─────── */

export default function SopGeneratorModal({
  open,
  onClose,
  onGenerated,
}: SopGeneratorModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  /* ── reset state when modal opens/closes ── */

  const handleClose = useCallback(() => {
    if (uploading) return // prevent close during generation
    setFile(null)
    setErrorMsg(null)
    setIsDragOver(false)
    onClose()
  }, [uploading, onClose])

  React.useEffect(() => {
    if (open) {
      setFile(null)
      setErrorMsg(null)
      setIsDragOver(false)
    }
  }, [open])

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
      // reset input so re-selecting the same file works
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
      message.success('标准化操规生成成功！')
      onGenerated({
        regulation_id: result.regulation_id,
        meta: result.meta || {},
        content: result.content || '',
      })
      setFile(null)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '生成失败，请重试'
      setErrorMsg(msg)
    } finally {
      setUploading(false)
    }
  }

  /* ── prevent modal close via mask click during generation ── */

  const maskClosable = !uploading

  return (
    <Modal
      title={null}
      open={open}
      onCancel={handleClose}
      width={640}
      footer={null}
      destroyOnClose
      maskClosable={maskClosable}
      closable={!uploading}
      styles={{
        body: { padding: 24 },
      }}
    >
      {/* decorative accent bar */}
      <div style={styles.accentBar} />

      <div style={styles.content}>
        {/* icon + title */}
        <ThunderboltOutlined style={styles.docIcon} />
        <div style={styles.title}>生成标准化操规</div>
        <div style={styles.subtitle}>
          上传旧版操规初稿（.docx 格式），系统将智能分析工艺步骤，
          自动生成包含 9 章完整内容的标准化安全操作规程
        </div>

        {/* step badge */}
        <div style={styles.stepBadge}>
          <span>Step 1 / 2</span>
          <CheckCircleFilled style={{ fontSize: 12 }} />
        </div>

        {/* error banner */}
        {errorMsg && <div style={styles.errorBanner}>{errorMsg}</div>}

        {/* main area: drop zone or file card or generating */}
        {uploading ? (
          /* ── generating state ── */
          <div style={styles.generatingOverlay}>
            <div style={styles.generatingPulse}>
              <LoadingOutlined style={{ fontSize: 28, color: TOKENS.primary }} />
            </div>
            <div style={styles.generatingText}>
              AI 正在分析工艺步骤并生成标准化操规...
            </div>
            <Text type="secondary" style={{ fontSize: 13 }}>
              预计需要 5-10 秒，请耐心等待
            </Text>
          </div>
        ) : file ? (
          /* ── file selected state ── */
          <div style={styles.fileCard}>
            <div style={styles.fileIconWrap}>
              <FileWordOutlined style={styles.fileIcon} />
            </div>
            <div style={styles.fileInfo}>
              <div style={styles.fileName}>{file.name}</div>
              <div style={styles.fileMeta}>
                {formatFileSize(file.size)} · 已就绪，点击下方按钮开始生成
              </div>
            </div>
            <button
              style={styles.removeBtn}
              onClick={handleRemoveFile}
              title="移除文件"
              aria-label="移除文件"
            >
              <CloseOutlined />
            </button>
          </div>
        ) : (
          /* ── empty drop zone ── */
          <div
            style={{
              ...styles.dropZone,
              ...(isDragOver ? styles.dropZoneHover : {}),
            }}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <InboxOutlined style={styles.dropIcon} />
            <div style={styles.dropTitle}>上传旧版操规 (.docx)</div>
            <div style={styles.dropSubtitle}>
              点击选择文件或将文件拖拽到此区域
            </div>
            <div style={styles.dropHint}>支持 .docx 格式，最大 20MB</div>
          </div>
        )}

        {/* hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".docx"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />

        {/* footer action buttons */}
        <div style={styles.footer}>
          <button
            onClick={handleClose}
            disabled={uploading}
            style={{
              background: 'transparent',
              border: 'none',
              color: TOKENS.linkBlue,
              fontSize: 14,
              fontWeight: 500,
              cursor: uploading ? 'not-allowed' : 'pointer',
              padding: 0,
              opacity: uploading ? 0.5 : 1,
            }}
          >
            {uploading ? '取消生成' : '取消'}
          </button>

          <Button
            loading={uploading}
            disabled={!file || uploading}
            onClick={handleGenerate}
            icon={<ThunderboltOutlined />}
            style={{
              height: 40,
              paddingLeft: 20,
              paddingRight: 20,
              fontSize: 14,
              fontWeight: 500,
              borderRadius: RADIUS.md,
              background: TOKENS.canvas,
              borderColor: TOKENS.primary,
              color: TOKENS.primary,
              boxShadow: 'none',
            }}
          >
            {uploading ? '正在生成...' : '开始生成'}
          </Button>
        </div>
      </div>

      {/* keyframe animation for the pulse ring */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes pulseRing {
              0%   { box-shadow: 0 0 0 0 rgba(86, 69, 212, 0.3); }
              50%  { box-shadow: 0 0 0 12px rgba(86, 69, 212, 0); }
              100% { box-shadow: 0 0 0 0 rgba(86, 69, 212, 0); }
            }
          `,
        }}
      />
    </Modal>
  )
}
