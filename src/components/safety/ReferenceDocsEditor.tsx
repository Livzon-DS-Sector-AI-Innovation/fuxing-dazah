'use client'

import { useState, useRef } from 'react'
import {
  Input,
  Button,
  Dropdown,
  Upload,
  Typography,
  Space,
  Tooltip,
  App,
  Spin,
} from 'antd'
import {
  PaperClipOutlined,
  DeleteOutlined,
  LinkOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileExcelOutlined,
  FileTextOutlined,
  BookOutlined,
  InboxOutlined,
} from '@ant-design/icons'
import { uploadWorkflowAttachment, deleteWorkflowAttachment, createKnowledgeAttachments } from '@/actions/safety'
import KnowledgeBasePicker from './KnowledgeBasePicker'
import type { ReferenceDocsValue, ReferenceAttachment } from '@/types/safety'

const { TextArea } = Input
const { Text } = Typography

interface Props {
  value?: ReferenceDocsValue | string
  onChange?: (value: ReferenceDocsValue) => void
}

/** 文件图标映射 */
function getFileIcon(fileType?: string) {
  switch (fileType) {
    case 'pdf':
      return <FilePdfOutlined style={{ color: '#e74c3c', fontSize: 18 }} />
    case 'docx':
    case 'doc':
      return <FileWordOutlined style={{ color: '#2b7bd6', fontSize: 18 }} />
    case 'xlsx':
    case 'xls':
      return <FileExcelOutlined style={{ color: '#27ae60', fontSize: 18 }} />
    case 'txt':
    case 'md':
      return <FileTextOutlined style={{ color: '#787671', fontSize: 18 }} />
    case 'knowledge':
      return <BookOutlined style={{ color: '#8b5cf6', fontSize: 18 }} />
    default:
      return <PaperClipOutlined style={{ color: '#787671', fontSize: 18 }} />
  }
}

/** 格式化文件大小 */
function formatSize(bytes?: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function ReferenceDocsEditor({ value, onChange }: Props) {
  const { message } = App.useApp()
  const [uploading, setUploading] = useState(false)
  const [kbPickerOpen, setKbPickerOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 解析 value：兼容字符串（旧格式）和对象（新格式）
  const currentValue: ReferenceDocsValue = typeof value === 'string'
    ? { text: value, attachments: [] }
    : value || { text: '', attachments: [] }

  const { text, attachments } = currentValue

  const emit = (partial: Partial<ReferenceDocsValue>) => {
    onChange?.({ ...currentValue, ...partial })
  }

  const handleTextChange = (newText: string) => {
    emit({ text: newText })
  }

  // ========== 文件上传 ==========
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // 校验格式
    const allowedExts = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.txt', '.md']
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!allowedExts.includes(ext)) {
      message.error(`不支持的文件格式: ${ext}，支持: ${allowedExts.join(', ')}`)
      return
    }

    setUploading(true)
    try {
      const res = await uploadWorkflowAttachment(file)
      if (res.data) {
        const newAtt: ReferenceAttachment = res.data
        emit({ attachments: [...attachments, newAtt] })
        message.success(`${file.name} 已上传并转为 Markdown`)
      } else {
        message.error(res.message || '上传失败')
      }
    } catch {
      message.error('上传失败，请重试')
    } finally {
      setUploading(false)
      // 重置 file input 以允许重复上传同一文件
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // ========== 知识库选择 ==========
  const handleKnowledgeSelect = async (articles: { id: string }[]) => {
    if (articles.length === 0) return
    setKbPickerOpen(false)

    const knowledgeIds = articles.map((a) => a.id)
    // 过滤掉已存在的知识库附件
    const existIds = new Set(attachments.filter((a) => a.type === 'knowledge').map((a) => a.knowledge_id))
    const newIds = knowledgeIds.filter((id) => !existIds.has(id))

    if (newIds.length === 0) {
      message.warning('所选文章已全部存在于附件列表中')
      return
    }

    setUploading(true)
    try {
      const res = await createKnowledgeAttachments(newIds)
      if (res.data) {
        emit({ attachments: [...attachments, ...res.data] })
        message.success(`已添加 ${res.data.length} 篇知识库文章`)
      } else {
        message.error(res.message || '添加失败')
      }
    } catch {
      message.error('添加失败，请重试')
    } finally {
      setUploading(false)
    }
  }

  // ========== 删除附件 ==========
  const handleDeleteAttachment = async (attachment: ReferenceAttachment) => {
    try {
      await deleteWorkflowAttachment(attachment.id)
    } catch {
      // 静默处理，本地删除即可
    }
    emit({ attachments: attachments.filter((a) => a.id !== attachment.id) })
  }

  // 已存在的知识库附件 ID（排除用）
  const existingKbIds = attachments
    .filter((a) => a.type === 'knowledge' && a.knowledge_id)
    .map((a) => a.knowledge_id!)

  return (
    <div>
      {/* ── 文本编辑区 ── */}
      <TextArea
        value={text}
        onChange={(e) => handleTextChange(e.target.value)}
        rows={5}
        placeholder="引用标准规范、关联 Skill、业务规则说明…\n例如：\n- GB/T 13861-2022《生产过程危险和有害因素分类与代码》\n- 企业风险分级管控管理制度"
        style={{ borderRadius: 8, fontFamily: 'monospace', fontSize: 13 }}
      />

      {/* ── 附件列表 ── */}
      {attachments.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text style={{ fontSize: 12, fontWeight: 600, color: '#787671', display: 'block', marginBottom: 8 }}>
            📎 附件 ({attachments.length})
          </Text>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {attachments.map((att) => (
              <div
                key={att.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 12px',
                  background: '#f6f5f4',
                  borderRadius: 8,
                  border: '1px solid #e5e3df',
                  gap: 8,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                  {getFileIcon(att.type === 'knowledge' ? 'knowledge' : att.file_type)}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Tooltip title={att.type === 'file' ? att.original_name : att.name}>
                      <Text
                        ellipsis
                        style={{ fontSize: 13, color: '#37352f', display: 'block' }}
                      >
                        {att.type === 'file' ? att.original_name || att.name : `📚 ${att.name}`}
                      </Text>
                    </Tooltip>
                    <Text style={{ fontSize: 11, color: '#bbb8b1' }}>
                      {att.type === 'knowledge' ? '知识库文章' : att.file_type?.toUpperCase()}
                      {att.file_size ? ` · ${formatSize(att.file_size)}` : ''}
                    </Text>
                  </div>
                </div>
                <Space size={4}>
                  <Tooltip title="在新标签页预览">
                    <Button
                      type="link"
                      size="small"
                      icon={<LinkOutlined />}
                      onClick={() => window.open(att.url, '_blank')}
                      style={{ color: '#5645d4' }}
                    />
                  </Tooltip>
                  <Tooltip title="删除">
                    <Button
                      type="link"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDeleteAttachment(att)}
                    />
                  </Tooltip>
                </Space>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 添加附件按钮 ── */}
      <div style={{ marginTop: 12 }}>
        {uploading ? (
          <Spin size="small" style={{ marginRight: 8 }} />
        ) : null}
        <Dropdown
          menu={{
            items: [
              {
                key: 'upload',
                label: '📤 上传文件 (PDF/Word/Excel/TXT)',
                onClick: () => fileInputRef.current?.click(),
              },
              {
                key: 'knowledge',
                label: '📚 从知识库选择',
                onClick: () => setKbPickerOpen(true),
              },
            ],
          }}
          trigger={['click']}
        >
          <Button
            icon={<PaperClipOutlined />}
            style={{ borderRadius: 8 }}
            loading={uploading}
          >
            添加附件
          </Button>
        </Dropdown>
        <Text style={{ fontSize: 11, color: '#bbb8b1', marginLeft: 8 }}>
          上传的附件将自动转换为 Markdown 供 AI 读取
        </Text>
      </div>

      {/* ── 隐藏的文件 input ── */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />

      {/* ── 知识库选择弹窗 ── */}
      <KnowledgeBasePicker
        open={kbPickerOpen}
        onClose={() => setKbPickerOpen(false)}
        onSelect={handleKnowledgeSelect}
        excludeIds={existingKbIds}
      />
    </div>
  )
}
