'use client'

import React, { useState, useCallback, useRef, useEffect } from 'react'
import { Table, Button, Space, message, Typography, Empty, Spin } from 'antd'
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
} from '@ant-design/icons'
import { getRegulations } from '@/actions/safety'
import type { OperationRegulation } from '@/types/safety'
import {
  actionLink,
  pillInfo,
  pillDefault,
  T,
} from '@/components/safety/shared-styles'
import dayjs from 'dayjs'

const { Text } = Typography

/* ─────── helpers ─────── */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
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
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadGeneratedSops = useCallback(async () => {
    setLoadingList(true)
    try {
      const response = await getRegulations({
        page: 1,
        page_size: 200,
        status: 'generated',
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
      default:
        return <span style={pillDefault}>{status || '草稿'}</span>
    }
  }

  /* ── table columns ── */

  const $purple = actionLink('#5645d4')

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
      width: 240,
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
      width: 100,
      render: (_, record) => (
        <span role="button" style={$purple} onClick={() => onOpenEditor(record)}>
          <EyeOutlined />编辑审阅
        </span>
      ),
    },
  ]

  /* ── render ── */

  return (
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
              style={{
                width: 64,
                height: 64,
                borderRadius: 9999,
                background: 'rgba(86,69,212,0.08)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                animation: 'pulseRing 2s ease-in-out infinite',
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

        {/* pulse animation keyframes */}
        <style
          dangerouslySetInnerHTML={{
            __html: `
              @keyframes pulseRing {
                0%   { box-shadow: 0 0 0 0 rgba(86, 69, 212, 0.3); }
                50%  { box-shadow: 0 0 0 16px rgba(86, 69, 212, 0); }
                100% { box-shadow: 0 0 0 0 rgba(86, 69, 212, 0); }
              }
            `,
          }}
        />
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
              待审核的标准化操规
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
            <Spin size="default" />
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
            scroll={{ x: 880 }}
          />
        )}
      </div>
    </div>
  )
}
