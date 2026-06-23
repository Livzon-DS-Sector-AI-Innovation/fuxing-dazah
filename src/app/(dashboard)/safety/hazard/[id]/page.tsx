'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import {
  Button,
  Space,
  Typography,
  App,
  Spin,
  Image,
  Row,
  Col,
  Select,
  Input,
  DatePicker,
  Flex,
  Upload,
  Avatar,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  EditOutlined,
  CloseOutlined,
  SaveOutlined,
  CloseCircleOutlined,
  RobotOutlined,
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  ToolOutlined,
  CameraOutlined,
  InboxOutlined,
} from '@ant-design/icons'
import { getHazard, updateHazard, replyRectification, uploadRectificationPhoto, getDepartmentLeader } from '@/actions/safety'
import type { HazardReport } from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
  INSPECTION_CATEGORY_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
  INSPECTOR_DEPARTMENT_OPTIONS,
} from '@/types/safety'
import HazardVerifyModal from '@/components/safety/HazardVerifyModal'
import dayjs from 'dayjs'

const { Text } = Typography
const { TextArea } = Input

// ── 后端静态文件基础 URL ──
const BACKEND_HOST = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1')
  .replace(/\/api\/v1$/, '')

// ── 解析照片 JSON 数组 → 完整 URL ──
// 兼容两种格式：
//   A) 本地路径字符串（平台上传/下载后） → 拼接 BACKEND_HOST
//   B) Bitable attachment 对象 {file_token, name, url?} → 优先用 url
function parsePhotos(photos?: string | null): string[] {
  if (!photos) return []
  let arr: unknown[] = []
  try {
    arr = JSON.parse(photos)
    if (!Array.isArray(arr)) return []
  } catch {
    return photos.split(',').map((s) => s.trim()).filter(Boolean)
  }
  return arr
    .map((item): string | null => {
      // 本地路径字符串
      if (typeof item === 'string') {
        if (item.startsWith('http')) return item
        return `${BACKEND_HOST}/${item.replace(/^\/+/, '')}`
      }
      // Bitable attachment 对象：优先用预签名 url / tmp_url
      if (typeof item === 'object' && item !== null) {
        const att = item as Record<string, unknown>
        if (typeof att.url === 'string' && att.url) return att.url
        if (typeof att.tmp_url === 'string' && att.tmp_url) return att.tmp_url
        // 无可用 URL：记录 name 供调试，跳过展示
        if (typeof att.name === 'string') {
          console.warn('照片无可用下载链接(file_token):', att.name)
        }
      }
      return null
    })
    .filter((url): url is string => url !== null)
}

// ── 日期格式化 ──
function fmtDate(iso?: string | null, format = 'YYYY-MM-DD HH:mm'): string {
  if (!iso) return '-'
  return dayjs(iso).format(format)
}

// ── 隐患等级颜色/标签 ──
function getLevelColor(level: string) {
  const opt = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
  return opt?.color || 'default'
}
function getLevelLabel(level: string) {
  const opt = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
  return opt?.label || level
}

// ── 隐患类别 label map ──
const HAZARD_CATEGORY_LABEL_MAP: Record<string, string> = {}
HAZARD_CATEGORY_OPTIONS.forEach((o) => { HAZARD_CATEGORY_LABEL_MAP[o.value] = o.label })

// ═══════════════════════════════════════════════════════════
// 视觉组件 — 参照 equipment 模块设计语言
// ═══════════════════════════════════════════════════════════

/** Status Pill — 参照 equipment/shared-styles.ts statusPill */
function StatusPill({
  color,
  bg,
  icon,
  children,
}: {
  color: string
  bg: string
  icon?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 10px',
        borderRadius: 4,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: '20px',
        color,
        background: bg,
        whiteSpace: 'nowrap',
      }}
    >
      {icon}
      {children}
    </span>
  )
}

const pillSuccess = (text: string) => (
  <StatusPill color="#1aae39" bg="#d9f3e1" icon={<CheckCircleOutlined />}>{text}</StatusPill>
)
const pillInfo = (text: string) => (
  <StatusPill color="#0075de" bg="#dcecfa" icon={<ClockCircleOutlined />}>{text}</StatusPill>
)
const pillError = (text: string) => (
  <StatusPill color="#e03131" bg="#fde0ec" icon={<CloseCircleOutlined />}>{text}</StatusPill>
)
const pillNeutral = (text: string) => (
  <StatusPill color="#787671" bg="#f0eeec">{text}</StatusPill>
)
const pillWarning = (text: string) => (
  <StatusPill color="#dd5b00" bg="#ffe8d4" icon={<ExclamationCircleOutlined />}>{text}</StatusPill>
)
const pillPurple = (text: string) => (
  <StatusPill color="#5645d4" bg="#e6e0f5">{text}</StatusPill>
)

/** 阶段编号圆点 */
function StageDot({ num, active }: { num: number; active: boolean }) {
  return (
    <div
      style={{
        width: 28,
        height: 28,
        borderRadius: '50%',
        background: active ? '#5645d4' : '#c8c4be',
        color: '#ffffff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        fontWeight: 700,
        flexShrink: 0,
        transition: 'background 0.3s ease',
      }}
    >
      {num}
    </div>
  )
}

/** 阶段连接竖线 */
function StageConnector() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '4px 0' }}>
      <div style={{ width: 2, height: 20, background: '#ede9e4', borderRadius: 1 }} />
    </div>
  )
}

/** Stage Card — 左侧 accent bar + hover 动效 */
function StageCard({
  accentColor,
  bgColor,
  children,
}: {
  accentColor: string
  bgColor?: string
  children: React.ReactNode
}) {
  return (
    <div
      style={{
        position: 'relative',
        background: bgColor || '#ffffff',
        borderRadius: 12,
        border: '1px solid #e5e3df',
        borderLeft: `4px solid ${accentColor}`,
        overflow: 'hidden',
        transition: 'all 0.2s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = '#c8c4be'
        e.currentTarget.style.boxShadow = 'rgba(15,15,15,0.06) 0px 2px 8px 0px'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = '#e5e3df'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      <div style={{ padding: '20px 24px' }}>{children}</div>
    </div>
  )
}

/** Stage Header — 图标 + 标题 + 状态 pill + 右侧操作 */
function StageHeader({
  icon,
  title,
  statusPill: sp,
  extra,
}: {
  icon: React.ReactNode
  title: string
  statusPill?: React.ReactNode
  extra?: React.ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 20,
        paddingBottom: 16,
        borderBottom: '1px solid #ede9e4',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: '#5645d4', fontSize: 18, display: 'inline-flex' }}>{icon}</span>
        <span style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a' }}>{title}</span>
        {sp}
      </div>
      {extra}
    </div>
  )
}

/** 字段块标题 */
function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 13, color: '#5d5b54' }}>
      {children}
    </Text>
  )
}

/** 带线框的字段值容器 */
function FieldTile({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        border: '1px solid #e5e3df',
        borderRadius: 8,
        padding: '10px 14px',
        background: '#fafaf9',
        minHeight: 40,
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 4,
      }}
    >
      {children}
    </div>
  )
}

/** 通用文本块 */
function TextBlock({
  style,
  children,
}: {
  style?: React.CSSProperties
  children: React.ReactNode
}) {
  return (
    <div
      style={{
        background: '#fafaf9',
        padding: 12,
        borderRadius: 8,
        fontSize: 14,
        lineHeight: 1.7,
        whiteSpace: 'pre-wrap',
        border: '1px solid #ede9e4',
        color: '#37352f',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** 照片画廊 */
function PhotoGallery({ photos: urls }: { photos: string[] }) {
  if (urls.length === 0) return null
  return (
    <Image.PreviewGroup>
      <Flex gap={10} wrap="wrap">
        {urls.map((url, i) => (
          <div
            key={i}
            style={{
              borderRadius: 10,
              overflow: 'hidden',
              border: '1px solid #ede9e4',
              transition: 'transform 0.2s ease',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.04)' }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)' }}
          >
            <Image
              src={url}
              alt={`照片 ${i + 1}`}
              width={130}
              height={130}
              style={{ objectFit: 'cover', display: 'block' }}
              preview={{ mask: <CameraOutlined style={{ fontSize: 20 }} /> }}
            />
          </div>
        ))}
      </Flex>
    </Image.PreviewGroup>
  )
}

/** 编辑按钮（actionLink 风格） */
function EditButton({
  editing,
  loading,
  onEdit,
  onCancel,
  onSave,
}: {
  editing: boolean
  loading: boolean
  onEdit: () => void
  onCancel: () => void
  onSave: () => void
}) {
  if (editing) {
    return (
      <Space size={8}>
        <Button size="small" icon={<CloseOutlined />} onClick={onCancel}>取消</Button>
        <Button size="small" type="primary" icon={<SaveOutlined />} loading={loading} onClick={onSave}>保存</Button>
      </Space>
    )
  }
  return (
    <Button
      size="small"
      icon={<EditOutlined />}
      onClick={onEdit}
      style={{
        color: '#0075de',
        fontSize: 13,
        fontWeight: 600,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        border: 'none',
        padding: '4px 8px',
        borderRadius: 6,
        background: 'transparent',
      }}
    >
      编辑
    </Button>
  )
}

/** 表单字段编辑器 */
function FieldEditor({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <Text style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
        {label}
      </Text>
      {children}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════

export default function HazardLedgerDetailPage() {
  const router = useRouter()
  const params = useParams()
  const id = params.id as string
  const { message, modal } = App.useApp()

  const [record, setRecord] = useState<HazardReport | null>(null)
  const [loading, setLoading] = useState(true)

  // 编辑状态
  const [editSection, setEditSection] = useState<'registration' | 'ai' | 'rectification' | null>(null)
  const [edits, setEdits] = useState<Partial<Record<string, string>>>({})
  const [saving, setSaving] = useState(false)

  // 整改回复状态
  const [replyFiles, setReplyFiles] = useState<any[]>([])
  const [replySubmitting, setReplySubmitting] = useState(false)
  const [leaderLoading, setLeaderLoading] = useState(false)

  // ── 人员搜索状态 ──
  interface UserOption { value: string; label: string }
  const [userOptions, setUserOptions] = useState<UserOption[]>([])
  const [userSearchLoading, setUserSearchLoading] = useState(false)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const handleUserSearch = useCallback((keyword: string) => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!keyword || keyword.length < 1) {
      setUserOptions([])
      return
    }
    searchTimerRef.current = setTimeout(async () => {
      setUserSearchLoading(true)
      try {
        const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
        const params = new URLSearchParams({ keyword, limit: '50' })
        const resp = await fetch(`${API_BASE}/api/v1/identity/personnel?${params}`)
        if (resp.ok) {
          const json = await resp.json()
          const items = (json.data?.items ?? []) as Record<string, unknown>[]
          setUserOptions(items.map((u) => ({
            value: String(u.id),
            label: `${String(u.name)} - ${String(u.department || '未知部门')}`,
          })))
        }
      } catch { /* 静默失败 */ } finally {
        setUserSearchLoading(false)
      }
    }, 300)
  }, [])

  // Modal 状态
  const [verifyModalVisible, setVerifyModalVisible] = useState(false)

  const loadRecord = async () => {
    try {
      const response = await getHazard(id)
      if (response.code === 200) {
        setRecord(response.data as HazardReport)
      } else {
        console.error('加载隐患详情失败:', { id, code: response.code, message: response.message })
        message.error(response.message || `加载失败 (${response.code})`)
        router.push('/safety/hazard-ledger')
      }
    } catch (err) {
      console.error('加载隐患详情异常:', { id, err })
      message.error('加载失败，请检查网络或后端服务')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (id) loadRecord()
  }, [id])

  // 获取字段当前值
  const fieldVal = (field: string): string => {
    if (editSection && field in edits) return edits[field] ?? (record as any)?.[field] ?? ''
    return (record as any)?.[field] ?? ''
  }

  const handleEdit = (section: 'registration' | 'ai' | 'rectification') => {
    setEditSection(section)
    setEdits({})
  }
  const handleCancelEdit = () => {
    setEditSection(null)
    setEdits({})
  }

  const handleDepartmentChange = async (dept: string) => {
    setEdits((p) => ({ ...p, department: dept }))
    if (!dept) return
    setLeaderLoading(true)
    try {
      const res = await getDepartmentLeader(dept)
      if (res.code === 200 && res.data?.leader_name) {
        const name: string = res.data.leader_name
        const leaderId: string | null = res.data.leader_id || null
        setEdits((p) => ({
          ...p,
          rectification_responsible_person: leaderId || '',
          rectification_responsible_person_name: name,
        }))
        // 预填负责人到选项列表，确保 Select 正确显示
        if (leaderId) {
          setUserOptions((prev) => {
            const exists = prev.some((o) => o.value === leaderId)
            if (exists) return prev
            return [{ value: leaderId, label: `${name} - ${dept}` }, ...prev]
          })
        }
      }
    } catch {
      // silently ignore — user can search manually
    } finally {
      setLeaderLoading(false)
    }
  }

  const handleSave = async () => {
    if (Object.keys(edits).length === 0) { setEditSection(null); return }
    setSaving(true)
    try {
      const res = await updateHazard(id, edits as any)
      if (res.code === 200) {
        message.success('修改已保存')
        setRecord(res.data as HazardReport)
        setEditSection(null)
        setEdits({})
      } else {
        message.error(res.message || '保存失败')
      }
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!record) return null

  // ── 状态判定 ──
  const rStatus = record.rectification_status
  const isGeneral = record.hazard_level === 'general'
  const v1 = record.verify_level_1_status
  const v2 = record.verify_level_2_status
  const v3 = record.verify_level_3_status
  const v1Done = v1 === 'approved' || v1 === 'rejected'
  const v2Done = v2 === 'approved' || v2 === 'rejected'
  const v3Done = v3 === 'approved' || v3 === 'rejected'

  const currentLevel = (() => {
    if (!rStatus || rStatus === 'pending' || rStatus === 'in_progress') return null
    if (!v1Done) return 1
    if (!isGeneral && !v2Done) return 2
    if (!v3Done) return isGeneral && v2Done ? 3 : (v2Done || isGeneral ? 3 : 2)
    return null
  })()

  // ── 复核操作按钮（仅用于 section ④）──
  const renderVerifyAction = () => {
    if (rStatus === 'replied') {
      return (
        <Button type="primary" icon={<CheckCircleOutlined />} size="middle"
          onClick={() => setVerifyModalVisible(true)}>
          部门负责人复核
        </Button>
      )
    }
    if (rStatus === 'level1_approved') {
      const label = isGeneral ? '检查人员复核' : '分管领导复核'
      return (
        <Button type="primary" icon={<CheckCircleOutlined />} size="middle"
          onClick={() => setVerifyModalVisible(true)}>
          {label}
        </Button>
      )
    }
    if (rStatus === 'level2_approved') {
      return (
        <Button type="primary" icon={<CheckCircleOutlined />} size="middle"
          onClick={() => setVerifyModalVisible(true)}>
          检查人员复核
        </Button>
      )
    }
    return null
  }

  // ── 整改回复提交 ──
  const handleReplySubmit = async () => {
    if (!record) return
    setReplySubmitting(true)
    try {
      // 1. 保存字段编辑
      if (Object.keys(edits).length > 0) {
        const updateRes = await updateHazard(id, edits as any)
        if (updateRes.code !== 200) {
          message.error(updateRes.message || '保存失败')
          setReplySubmitting(false)
          return
        }
      }

      // 2. 上传新照片
      const pendingFiles = replyFiles.filter((f) => f.originFileObj)
      // 从数据库读取原始路径（不经过 URL 转换），避免存储混合格式
      let existingPaths: string[] = []
      if (record.rectification_photos) {
        try {
          const raw = JSON.parse(record.rectification_photos)
          if (Array.isArray(raw)) existingPaths = raw.filter((p: unknown) => typeof p === 'string')
        } catch { /* ignore */ }
      }
      const newPaths: string[] = []

      if (pendingFiles.length > 0) {
        for (const file of pendingFiles) {
          try {
            const uploadRes = await uploadRectificationPhoto(id, file.originFileObj as File)
            if (uploadRes.code === 200 && uploadRes.data) {
              // 获取最新 rectification_photos
              const data = uploadRes.data as HazardReport
              if (data.rectification_photos) {
                try {
                  const photos = JSON.parse(data.rectification_photos)
                  if (Array.isArray(photos) && photos.length > 0) {
                    newPaths.push(photos[photos.length - 1])
                  }
                } catch { /* ignore */ }
              }
            }
          } catch {
            message.error('照片上传失败')
          }
        }
      }

      const allPhotoPaths = [...existingPaths, ...newPaths]

      // 3. 调用 replyRectification
      const replyContent = edits.rectification_reply || record.rectification_reply || fieldVal('rectification_reply')
      const replyRes = await replyRectification(id, {
        reply_content: replyContent,
        rectification_photos: allPhotoPaths.length > 0 ? JSON.stringify(allPhotoPaths) : undefined,
      })

      if (replyRes.code === 200) {
        message.success('整改回复已提交')
        setRecord(replyRes.data as HazardReport)
        setEditSection(null)
        setEdits({})
        setReplyFiles([])
      } else {
        message.error(replyRes.message || '提交失败')
      }
    } catch {
      message.error('提交整改回复失败')
    } finally {
      setReplySubmitting(false)
    }
  }

  // ── 整改状态 pill ──
  const makeRectificationPill = () => {
    const label = RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === (rStatus || 'pending'))?.label || '待整改'
    if (rStatus === 'completed' || rStatus === 'closed') return pillSuccess(label)
    if (rStatus === 'rejected') return pillError(label)
    if (rStatus === 'replied' || rStatus === 'level1_approved' || rStatus === 'level2_approved')
      return pillInfo(label)
    if (rStatus === 'in_progress') return pillWarning(label)
    return pillNeutral(label)
  }
  const rectificationPill = makeRectificationPill()

  // ── 阶段状态 pill ──
  const stage1Pill = pillSuccess('已完成')
  const stage2Pill = record.ai_generated ? pillPurple('AI 已识别') : pillNeutral('待识别')
  const stage3Pill = record.rectification_reply ? pillSuccess('已回复') : pillNeutral('待回复')

  // 整改期限 = 检查日期 + 2 个月（不可更改）
  const deadlineDefault = record.discovered_at
    ? dayjs(record.discovered_at).add(2, 'month').format('YYYY-MM-DD')
    : '-'

  const photos = {
    defect: parsePhotos(record.defect_photos),
    rectification: parsePhotos(record.rectification_photos),
  }

  // ── 复核卡片渲染 ──
  const reviewCard = (
    _level: number,
    label: string,
    status: string | undefined,
    isCurrent: boolean,
  ) => {
    const done = status === 'approved' || status === 'rejected'
    const approved = status === 'approved'
    const rejected = status === 'rejected'

    let cardBg = '#fafaf9'
    let cardBorder = '#e5e3df'
    let dotColor = '#c8c4be'
    let statusText = '未开始'
    let statusColor = '#787671'
    let statusBg = '#f0eeec'

    if (approved) {
      cardBg = '#f6ffed'; cardBorder = '#b7eb8f'; dotColor = '#1aae39'
      statusText = '已同意'; statusColor = '#1aae39'; statusBg = '#d9f3e1'
    } else if (rejected) {
      cardBg = '#fff2f0'; cardBorder = '#ffccc7'; dotColor = '#e03131'
      statusText = '已驳回'; statusColor = '#e03131'; statusBg = '#fde0ec'
    } else if (isCurrent) {
      cardBg = '#f0f7ff'; cardBorder = '#1677ff'; dotColor = '#1677ff'
      statusText = '待复核'; statusColor = '#0075de'; statusBg = '#dcecfa'
    }

    return (
      <div
        style={{
          flex: '1 1 200px',
          minWidth: 200,
          background: cardBg,
          border: `1.5px solid ${cardBorder}`,
          borderRadius: 12,
          padding: '18px 16px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 8,
          transition: 'all 0.2s ease',
          boxShadow: isCurrent ? '0 0 0 2px rgba(22,119,255,0.15)' : undefined,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateY(-2px)'
          e.currentTarget.style.boxShadow = isCurrent
            ? '0 0 0 2px rgba(22,119,255,0.2), rgba(15,15,15,0.08) 0px 4px 12px 0px'
            : 'rgba(15,15,15,0.08) 0px 4px 12px 0px'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'none'
          e.currentTarget.style.boxShadow = isCurrent ? '0 0 0 2px rgba(22,119,255,0.15)' : 'none'
        }}
      >
        {/* 状态圆点 */}
        <div style={{ width: 14, height: 14, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />
        {/* 状态标签 */}
        <StatusPill color={statusColor} bg={statusBg}>{statusText}</StatusPill>
        {/* 角色名称 */}
        <Text strong style={{ fontSize: 14, color: '#1a1a1a' }}>{label}</Text>
        {!done && isCurrent && <Text style={{ fontSize: 12, color: '#1677ff' }}>等待复核</Text>}
      </div>
    )
  }

  // ── 隐患级别 pill ──
  const levelPillColor = getLevelColor(record.hazard_level)
  const levelPill = (() => {
    const c = levelPillColor === 'red' ? '#e03131' : levelPillColor === 'orange' ? '#dd5b00' : '#5645d4'
    const b = levelPillColor === 'red' ? '#fde0ec' : levelPillColor === 'orange' ? '#ffe8d4' : '#e6e0f5'
    return <StatusPill color={c} bg={b}>{getLevelLabel(record.hazard_level)}</StatusPill>
  })()

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1100, margin: '0 auto' }}>
      {/* ═══════ 页面头部（Equipment 风格）═══════ */}
      <div style={{ marginBottom: 28 }}>
        <button
          type="button"
          onClick={() => router.push('/safety/hazard-ledger')}
          style={{
            color: '#0075de', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', gap: 4,
            background: 'transparent', border: 'none', padding: 0,
            lineHeight: '22px', marginBottom: 12,
          }}
        >
          <ArrowLeftOutlined />返回台账
        </button>

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a', margin: 0, lineHeight: 1.3 }}>
              隐患台账详情
            </h2>
            <p style={{ fontSize: 14, color: '#787671', margin: '4px 0 0', lineHeight: 1.5 }}>
              编号 {record.hazard_no}
              <span style={{ color: '#c8c4be', margin: '0 8px' }}>·</span>
              {fmtDate(record.discovered_at, 'YYYY-MM-DD')}
              <span style={{ color: '#c8c4be', margin: '0 8px' }}>·</span>
              <StatusPill color={record.ai_generated ? '#391c57' : '#787671'} bg={record.ai_generated ? '#e6e0f5' : '#f0eeec'}>
                {record.ai_generated ? 'AI 识别' : '人工录入'}
              </StatusPill>
            </p>
          </div>
          <Space size={8}>
            {levelPill}
            {rectificationPill}
          </Space>
        </div>
      </div>

      {/* ═══════ 四阶段纵轴布局 ═══════ */}

      {/* ── ① 隐患登记 ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 28 }}>
          <StageDot num={1} active />
          <StageConnector />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <StageCard accentColor="#5d5b54">
            <StageHeader
              icon={<FileTextOutlined />}
              title="隐患登记"
              statusPill={stage1Pill}
              extra={<EditButton editing={editSection === 'registration'} loading={saving} onEdit={() => handleEdit('registration')} onCancel={handleCancelEdit} onSave={handleSave} />}
            />

            {editSection === 'registration' ? (
              <Row gutter={[16, 12]}>
                <Col span={8}>
                  <FieldEditor label="检查日期">
                    <DatePicker showTime style={{ width: '100%' }}
                      value={fieldVal('discovered_at') ? dayjs(fieldVal('discovered_at')) : null}
                      onChange={(d) => setEdits((p) => ({ ...p, discovered_at: d?.toISOString() || '' }))} />
                  </FieldEditor>
                </Col>
                <Col span={8}>
                  <FieldEditor label="检查人员">
                    <Input
                      placeholder="多维表格自动填入"
                      value={fieldVal('discovered_by_name')}
                      onChange={(e) => setEdits((p) => ({ ...p, discovered_by_name: e.target.value }))}
                    />
                  </FieldEditor>
                </Col>
                <Col span={8}>
                  <FieldEditor label="责任人">
                    <Input
                      placeholder="多维表格自动填入"
                      value={fieldVal('rectification_responsible_person_name')}
                      onChange={(e) => setEdits((p) => ({ ...p, rectification_responsible_person_name: e.target.value }))}
                    />
                  </FieldEditor>
                </Col>
                <Col span={8}>
                  <FieldEditor label="检查类别">
                    <Select style={{ width: '100%' }}
                      value={fieldVal('inspection_category')}
                      onChange={(v) => setEdits((p) => ({ ...p, inspection_category: v }))}
                      options={INSPECTION_CATEGORY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
                  </FieldEditor>
                </Col>
                <Col span={8}>
                  <FieldEditor label="责任部门">
                    <Select
                      showSearch
                      allowClear
                      style={{ width: '100%' }}
                      placeholder="请选择责任部门"
                      value={fieldVal('department') || undefined}
                      onChange={(v) => handleDepartmentChange(v || '')}
                      options={INSPECTOR_DEPARTMENT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                      filterOption={(input, option) =>
                        (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
                      }
                    />
                  </FieldEditor>
                </Col>
                <Col span={24}>
                  <FieldEditor label="隐患描述">
                    <TextArea rows={3} value={fieldVal('description')}
                      onChange={(e) => setEdits((p) => ({ ...p, description: e.target.value }))} />
                  </FieldEditor>
                </Col>
              </Row>
            ) : (
              <>
                <Row gutter={[20, 20]}>
                  <Col span={8}>
                    <FieldLabel>检查日期</FieldLabel>
                    <FieldTile>
                      <Text style={{ fontSize: 14 }}>{fmtDate(record.discovered_at, 'YYYY-MM-DD')}</Text>
                    </FieldTile>
                  </Col>
                  <Col span={8}>
                    <FieldLabel>检查人员</FieldLabel>
                    <FieldTile>
                      <Text style={{ fontSize: 14 }}>{record.discovered_by_name || '-'}</Text>
                    </FieldTile>
                  </Col>
                  <Col span={8}>
                    <FieldLabel>责任人</FieldLabel>
                    <FieldTile>
                      <Text style={{ fontSize: 14 }}>{record.rectification_responsible_person_name || '-'}</Text>
                    </FieldTile>
                  </Col>
                  <Col span={8}>
                    <FieldLabel>检查类别</FieldLabel>
                    <FieldTile>
                      {record.inspection_category
                        ? record.inspection_category.split(/[,，]/).filter(Boolean).map((c, i) => (
                          <StatusPill key={i} color="#5d5b54" bg="#f0eeec">{c.trim()}</StatusPill>))
                        : <Text style={{ fontSize: 14, color: '#a4a097' }}>-</Text>}
                    </FieldTile>
                  </Col>
                  <Col span={8}>
                    <FieldLabel>责任部门</FieldLabel>
                    <FieldTile>
                      <Text style={{ fontSize: 14 }}>{record.department || '-'}</Text>
                    </FieldTile>
                  </Col>
                </Row>

                {record.description && (
                  <div style={{ marginTop: 16 }}>
                    <FieldLabel>隐患描述</FieldLabel>
                    <TextBlock>{record.description}</TextBlock>
                  </div>
                )}

                {photos.defect.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <FieldLabel><CameraOutlined style={{ marginRight: 4 }} />缺陷照片</FieldLabel>
                    <PhotoGallery photos={photos.defect} />
                  </div>
                )}
              </>
            )}
          </StageCard>
        </div>
      </div>

      {/* ── ② AI 智能识别 ── */}
      {record.ai_generated && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 28 }}>
            <StageDot num={2} active />
            <StageConnector />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <StageCard accentColor="#5d5b54">
              <StageHeader
                icon={<RobotOutlined />}
                title="AI 智能识别"
                statusPill={stage2Pill}
                extra={<EditButton editing={editSection === 'ai'} loading={saving} onEdit={() => handleEdit('ai')} onCancel={handleCancelEdit} onSave={handleSave} />}
              />

              {editSection === 'ai' ? (
                <Row gutter={[16, 12]}>
                  <Col span={8}>
                    <FieldEditor label="隐患分类（AI）">
                      <Select style={{ width: '100%' }}
                        value={fieldVal('hazard_type')}
                        onChange={(v) => setEdits((p) => ({ ...p, hazard_type: v }))}
                        options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
                    </FieldEditor>
                  </Col>
                  <Col span={8}>
                    <FieldEditor label="隐患类别（AI）">
                      <Select style={{ width: '100%' }}
                        value={fieldVal('hazard_category')}
                        onChange={(v) => setEdits((p) => ({ ...p, hazard_category: v }))}
                        options={HAZARD_CATEGORY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
                    </FieldEditor>
                  </Col>
                  <Col span={8}>
                    <FieldEditor label="隐患级别（AI）">
                      <Select style={{ width: '100%' }}
                        value={fieldVal('hazard_level')}
                        onChange={(v) => setEdits((p) => ({ ...p, hazard_level: v }))}
                        options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
                    </FieldEditor>
                  </Col>
                  <Col span={24}>
                    <FieldEditor label="隐患描述（AI）">
                      <TextArea rows={3} value={fieldVal('key_defect')}
                        onChange={(e) => setEdits((p) => ({ ...p, key_defect: e.target.value }))} />
                    </FieldEditor>
                  </Col>
                  <Col span={24}>
                    <FieldEditor label="隐患判定依据（AI）">
                      <TextArea rows={2} value={fieldVal('major_hazard_basis')}
                        onChange={(e) => setEdits((p) => ({ ...p, major_hazard_basis: e.target.value }))} />
                    </FieldEditor>
                  </Col>
                  <Col span={24}>
                    <FieldEditor label="整改建议（AI）">
                      <TextArea rows={4} value={fieldVal('corrective_preventive_measures')}
                        onChange={(e) => setEdits((p) => ({ ...p, corrective_preventive_measures: e.target.value }))}
                        placeholder="AI 生成的整改建议，可手动修正" />
                    </FieldEditor>
                  </Col>
                </Row>
              ) : (
                <>
                  <Row gutter={[16, 12]}>
                    <Col span={8}>
                      <FieldLabel>隐患分类（AI）</FieldLabel>
                      <FieldTile>
                        {(() => {
                          const opt = HAZARD_TYPE_OPTIONS.find((o) => o.value === record.hazard_type)
                          return <StatusPill color="#391c57" bg="#e6e0f5">{opt?.label || record.hazard_type}</StatusPill>
                        })()}
                      </FieldTile>
                    </Col>
                    <Col span={8}>
                      <FieldLabel>隐患类别（AI）</FieldLabel>
                      <FieldTile>
                        <StatusPill color="#391c57" bg="#e6e0f5">
                          {HAZARD_CATEGORY_LABEL_MAP[record.hazard_category || ''] || record.hazard_category || '-'}
                        </StatusPill>
                      </FieldTile>
                    </Col>
                    <Col span={8}>
                      <FieldLabel>隐患级别（AI）</FieldLabel>
                      <FieldTile>
                        <StatusPill
                          color={getLevelColor(record.hazard_level) === 'red' ? '#e03131' : getLevelColor(record.hazard_level) === 'orange' ? '#dd5b00' : '#5645d4'}
                          bg={getLevelColor(record.hazard_level) === 'red' ? '#fde0ec' : getLevelColor(record.hazard_level) === 'orange' ? '#ffe8d4' : '#e6e0f5'}>
                          {getLevelLabel(record.hazard_level)}
                        </StatusPill>
                      </FieldTile>
                    </Col>
                  </Row>

                  {record.key_defect && (
                    <div style={{ marginTop: 16 }}>
                      <FieldLabel>
                        <ExclamationCircleOutlined style={{ color: '#d4b106', marginRight: 4 }} />
                        隐患描述（AI）
                      </FieldLabel>
                      <TextBlock style={{ background: '#fffbe6', border: '1px solid #ffe58f' }}>
                        {record.key_defect}
                      </TextBlock>
                    </div>
                  )}
                  {record.major_hazard_basis && (
                    <div style={{ marginTop: 12 }}>
                      <FieldLabel>隐患判定依据（AI）</FieldLabel>
                      <TextBlock>{record.major_hazard_basis}</TextBlock>
                    </div>
                  )}
                  {record.corrective_preventive_measures && (
                    <div style={{ marginTop: 16 }}>
                      <FieldLabel>
                        <ToolOutlined style={{ color: '#5645d4', marginRight: 4 }} />
                        整改建议（AI）
                      </FieldLabel>
                      <TextBlock style={{ background: '#f8f6ff', border: '1px solid #cdc4e8' }}>
                        {record.corrective_preventive_measures}
                      </TextBlock>
                    </div>
                  )}
                </>
              )}
            </StageCard>
          </div>
        </div>
      )}

      {/* ── ③ 整改回复 ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 28 }}>
          <StageDot num={3} active />
          <StageConnector />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <StageCard accentColor="#0075de">
            <StageHeader
              icon={<ToolOutlined />}
              title="整改回复"
              statusPill={stage3Pill}
              extra={<EditButton editing={editSection === 'rectification'} loading={saving} onEdit={() => handleEdit('rectification')} onCancel={handleCancelEdit} onSave={handleSave} />}
            />

            {editSection === 'rectification' ? (
              <>
                {/* 整改期限 — 只读，自动计算 */}
                <Row gutter={[16, 12]} style={{ marginBottom: 16 }}>
                  <Col span={12}>
                    <FieldLabel>整改期限</FieldLabel>
                    <FieldTile>
                      <Text style={{ fontSize: 14, fontWeight: 500 }}>
                        {record.deadline
                          ? fmtDate(record.deadline, 'YYYY-MM-DD')
                          : deadlineDefault}
                      </Text>
                    </FieldTile>
                  </Col>
                </Row>

                <Row gutter={[16, 12]}>
                  <Col span={12}>
                    <FieldEditor label="整改完成时间">
                      <DatePicker style={{ width: '100%' }}
                        value={fieldVal('actual_completion_date') ? dayjs(fieldVal('actual_completion_date')) : null}
                        onChange={(d) => setEdits((p) => ({ ...p, actual_completion_date: d?.toISOString() || '' }))} />
                    </FieldEditor>
                  </Col>
                </Row>

                <FieldEditor label="纠正预防措施">
                  <TextArea rows={5}
                    value={fieldVal('rectification_reply')}
                    onChange={(e) => setEdits((p) => ({ ...p, rectification_reply: e.target.value }))}
                    placeholder="请详细描述纠正预防措施，包括具体整改措施、实施过程、完成情况等" />
                </FieldEditor>

                {/* 整改照片上传 */}
                <div style={{ marginTop: 8 }}>
                  <FieldLabel><CameraOutlined style={{ marginRight: 4 }} />整改后照片</FieldLabel>
                  <Upload.Dragger
                    multiple
                    fileList={replyFiles}
                    beforeUpload={() => false}
                    accept="image/*"
                    listType="picture-card"
                    onChange={(info) => setReplyFiles(info.fileList)}
                    style={{ marginBottom: 8 }}
                  >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p className="ant-upload-text">点击或拖拽图片到此区域上传</p>
                    <p className="ant-upload-hint">支持多张整改后照片（提交时统一上传）</p>
                  </Upload.Dragger>
                </div>

                {/* 操作按钮 */}
                <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #ede9e4', display: 'flex', justifyContent: 'center', gap: 12 }}>
                  <Button size="middle" icon={<CloseOutlined />} onClick={handleCancelEdit}>取消</Button>
                  <Button
                    type="primary"
                    size="middle"
                    icon={<CheckCircleOutlined />}
                    loading={replySubmitting}
                    onClick={handleReplySubmit}
                    style={{ fontWeight: 600, borderRadius: 8 }}
                  >
                    提交整改
                  </Button>
                </div>
              </>
            ) : (
              <>
                <Row gutter={[16, 12]}>
                  <Col span={12}>
                    <FieldLabel>整改期限</FieldLabel>
                    <FieldTile>
                      {record.deadline ? (
                        <span>
                          <span style={{ fontSize: 14, color: dayjs(record.deadline).isBefore(dayjs()) ? '#e03131' : '#1a1a1a', fontWeight: dayjs(record.deadline).isBefore(dayjs()) ? 600 : 400 }}>
                            {fmtDate(record.deadline, 'YYYY-MM-DD')}
                          </span>
                          {dayjs(record.deadline).isBefore(dayjs()) && (
                            <StatusPill color="#e03131" bg="#fde0ec" icon={<ExclamationCircleOutlined />}>已逾期</StatusPill>
                          )}
                        </span>
                      ) : (
                        <Text style={{ fontSize: 14, color: '#5d5b54' }}>{deadlineDefault}</Text>
                      )}
                    </FieldTile>
                  </Col>
                  <Col span={12}>
                    <FieldLabel>整改完成时间</FieldLabel>
                    <FieldTile>
                      <Text style={{ fontSize: 14 }}>{fmtDate(record.actual_completion_date, 'YYYY-MM-DD')}</Text>
                    </FieldTile>
                  </Col>
                </Row>

                <div style={{ marginTop: 16 }}>
                  <FieldLabel><EditOutlined style={{ marginRight: 4 }} />纠正预防措施</FieldLabel>
                  <FieldTile>
                    <Text style={{ fontSize: 14 }}>{record.rectification_reply || '-'}</Text>
                  </FieldTile>
                </div>

                <div style={{ marginTop: 16 }}>
                  <FieldLabel><CameraOutlined style={{ marginRight: 4 }} />整改后照片</FieldLabel>
                  {photos.rectification.length > 0 ? (
                    <PhotoGallery photos={photos.rectification} />
                  ) : (
                    <FieldTile>
                      <Text style={{ fontSize: 14, color: '#a4a097' }}>暂无照片</Text>
                    </FieldTile>
                  )}
                </div>

                {/* 整改回复操作按钮（inline 编辑）*/}
                {(rStatus === 'pending' || rStatus === 'in_progress') && record.status === 'open' && (
                  <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #ede9e4', display: 'flex', justifyContent: 'center' }}>
                    <Button type="primary" icon={<EditOutlined />} size="middle"
                      onClick={() => handleEdit('rectification')}>
                      整改回复
                    </Button>
                  </div>
                )}
                {rStatus === 'rejected' && (
                  <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #ede9e4', display: 'flex', justifyContent: 'center' }}>
                    <Button danger icon={<EditOutlined />} size="middle"
                      onClick={() => handleEdit('rectification')}>
                      重新整改
                    </Button>
                  </div>
                )}
              </>
            )}
          </StageCard>
        </div>
      </div>

      {/* ── ④ 复核 ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 28 }}>
          <StageDot num={4} active />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <StageCard accentColor={rStatus === 'completed' || rStatus === 'closed' ? '#1aae39' : '#0075de'}>
            <StageHeader
              icon={<CheckCircleOutlined />}
              title="复核"
              statusPill={rectificationPill}
            />

            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              <Text style={{ fontSize: 13, color: '#5d5b54', marginRight: 8 }}>整改状态</Text>
              {rectificationPill}
            </div>

            <Flex gap={16} wrap="wrap" justify="center">
              {reviewCard(1, '部门负责人复核', v1, currentLevel === 1)}
              {!isGeneral && reviewCard(2, '分管领导复核', v2, currentLevel === 2)}
              {reviewCard(3, '检查人员复核', v3, currentLevel === 3)}
            </Flex>

            {currentLevel && renderVerifyAction() && (
              <div style={{ textAlign: 'center', marginTop: 24, paddingTop: 16, borderTop: '1px solid #ede9e4' }}>
                {renderVerifyAction()}
              </div>
            )}
            {!currentLevel && (rStatus === 'completed' || rStatus === 'closed') && (
              <div style={{ textAlign: 'center', marginTop: 20 }}>{pillSuccess('整改已关闭')}</div>
            )}
          </StageCard>
        </div>
      </div>

      {/* ═══════ Modals ═══════ */}
      <HazardVerifyModal
        open={verifyModalVisible}
        record={record}
        onClose={() => setVerifyModalVisible(false)}
        onSuccess={(updated) => { setRecord(updated); setVerifyModalVisible(false) }}
      />
    </div>
  )
}
