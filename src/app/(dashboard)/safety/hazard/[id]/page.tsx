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
  Tag,
  Radio,
  Timeline,
} from 'antd'

const { Paragraph } = Typography
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
  SendOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { getHazard, updateHazard, replyRectification, uploadRectificationPhoto, getDepartmentLeader, notifyReviewer, notifyRectification, triggerRectificationReview, verifyLevel } from '@/actions/safety'
import type { HazardReport } from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
  INSPECTION_CATEGORY_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
  INSPECTOR_DEPARTMENT_OPTIONS,
  VERIFY_LEVEL_OPTIONS,
  VERIFY_LEVEL_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography
const { TextArea } = Input

import { fileProxyUrl } from '@/lib/file-url'

// ── 解析照片 JSON 数组 → 完整 URL ──
// 兼容两种格式：
//   A) 本地路径或 object_key（通过后端代理访问） → 调用 fileProxyUrl
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
      // 本地路径或 MinIO object_key
      if (typeof item === 'string') {
        if (item.startsWith('http')) return item
        return fileProxyUrl(item)
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
const pillProcessing = (text: string) => (
  <StatusPill color="#0075de" bg="#dcecfa" icon={<SyncOutlined spin />}>{text}</StatusPill>
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
  const [notifyLoading, setNotifyLoading] = useState(false)
  const [aiReviewTriggering, setAiReviewTriggering] = useState(false)
  const [notifyRectLoading, setNotifyRectLoading] = useState(false)

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
  const v1 = record.verify_level_1_status
  const v2 = record.verify_level_2_status
  const v3 = record.verify_level_3_status
  const v1Done = v1 === 'approved' || v1 === 'rejected'
  const v2Done = v2 === 'approved' || v2 === 'rejected'
  const v3Done = v3 === 'approved' || v3 === 'rejected'

  // 当前待复核级别：仅当整改状态为「已回复」或某级已通过时，尚未复核的
  // 最低级别才是当前可操作级别。rejected / ai_reviewing 等状态下不应出现复核入口。
  const currentLevel = (() => {
    if (!rStatus || rStatus === 'pending' || rStatus === 'in_progress' || rStatus === 'rejected' || rStatus === 'ai_reviewing') return null
    if (!v1Done) return 1
    if (!v2Done) return 2
    if (!v3Done) return 3
    return null
  })()

  // ── 复核操作（equipment 风格 modal.confirm）──
  const handleVerify = (level: number) => {
    const levelLabel = VERIFY_LEVEL_OPTIONS.find((o) => o.value === level)?.label || `第${level}级复核`
    const refs = { action: 'approved' as string, opinion: '' }

    modal.confirm({
      title: `${levelLabel}复核`,
      icon: null,
      width: 560,
      content: (
        <div style={{ marginTop: 16 }}>
          {/* 隐患摘要 */}
          <div style={{
            background: '#faf9f7', padding: 12, borderRadius: 8,
            marginBottom: 16, fontSize: 13, lineHeight: 1.8,
          }}>
            <div><strong>隐患编号：</strong>{record!.hazard_no}</div>
            <div><strong>隐患描述：</strong>{record!.description}</div>
            <div><strong>整改回复：</strong>{record!.rectification_reply || '-'}</div>
          </div>

          {/* 三级复核进度 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              {[1, 2, 3].map((l) => {
                const s = [v1, v2, v3][l - 1]
                const label = VERIFY_LEVEL_OPTIONS.find((o) => o.value === l)?.label
                const statusOpt = VERIFY_LEVEL_STATUS_OPTIONS.find((o) => o.value === (s || 'pending'))
                return (
                  <Tag key={l} color={statusOpt?.color}>{label}: {statusOpt?.label}</Tag>
                )
              })}
            </div>
          </div>

          {/* 复核结论 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 12 }}>
              <Text strong>复核结论</Text>
            </div>
            <Radio.Group defaultValue="approved" onChange={(e) => { refs.action = e.target.value }}>
              <Radio value="approved">✅ 通过</Radio>
              <Radio value="rejected">❌ 驳回</Radio>
            </Radio.Group>
          </div>

          {/* 复核意见 */}
          <div>
            <div style={{ marginBottom: 12 }}>
              <Text strong>复核意见（可选）</Text>
            </div>
            <TextArea rows={3} placeholder="请填写复核意见" onChange={(e) => { refs.opinion = e.target.value }} />
          </div>
        </div>
      ),
      okText: '提交复核',
      cancelText: '取消',
      onOk: async () => {
        const res = await verifyLevel(record!.id, {
          level,
          action: refs.action as 'approved' | 'rejected',
          opinion: refs.opinion || undefined,
        })
        if (res.code === 200) {
          message.success(`${levelLabel}复核${refs.action === 'approved' ? '通过' : '驳回'}`)
          setRecord(res.data!)
        } else {
          message.error(res.message || '复核失败')
          throw new Error(res.message) // 阻止弹窗关闭
        }
      },
    })
  }

  // ── 飞书通知状态标识 ──
  const renderNotifyStatus = (
    notifyStatus: string | null | undefined,
    notifiedAt: string | null | undefined,
    notifyError: string | null | undefined,
  ) => {
    if (notifyStatus === 'success' && notifiedAt) {
      return (
        <span style={{ color: '#1aae39', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <CheckCircleOutlined style={{ fontSize: 12 }} />
          已通知 {fmtDate(notifiedAt, 'YYYY-MM-DD HH:mm')}
        </span>
      )
    }
    if (notifyStatus === 'failed') {
      return (
        <span style={{ color: '#e03131', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <ExclamationCircleOutlined style={{ fontSize: 12 }} />
          通知失败{notifyError ? `：${notifyError}` : ''}
        </span>
      )
    }
    // 从未发送过通知
    return (
      <span style={{ color: '#999', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <ExclamationCircleOutlined style={{ fontSize: 12 }} />
        未通知
      </span>
    )
  }

  // ── AI 初审状态渲染 ──
  const renderAIReviewStatus = () => {
    const aiStatus = record?.ai_review_status || 'pending'
    const aiResult = record?.ai_review_result

    if (aiStatus === 'pending') {
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#8c8c8c', fontSize: 13 }}>
          <RobotOutlined style={{ fontSize: 14 }} />
          AI 初审待处理
        </span>
      )
    }
    if (aiStatus === 'processing') {
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#0075de', fontSize: 13 }}>
          <Spin size="small" />
          AI 初审中...
        </span>
      )
    }
    if (aiStatus === 'failed') {
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            background: '#fde0ec', color: '#e03131', fontSize: 12,
            padding: '2px 10px', borderRadius: 999,
          }}>
            <ExclamationCircleOutlined style={{ fontSize: 12 }} />
            AI 初审失败
          </span>
          {record?.ai_error_message && (
            <Text type="danger" style={{ fontSize: 12 }}>{record.ai_error_message}</Text>
          )}
        </span>
      )
    }
    if (aiStatus === 'completed' && aiResult) {
      const conclusion = aiResult.review_conclusion
      if (conclusion === '通过') {
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            background: '#e6f9ee', color: '#1aae39', fontSize: 12,
            padding: '2px 10px', borderRadius: 999,
          }}>
            <CheckCircleOutlined style={{ fontSize: 12 }} />
            AI 初审通过
          </span>
        )
      }
      if (conclusion === '不通过') {
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            background: '#fde0ec', color: '#e03131', fontSize: 12,
            padding: '2px 10px', borderRadius: 999,
          }}>
            <CloseCircleOutlined style={{ fontSize: 12 }} />
            AI 初审不通过（需重新整改）
          </span>
        )
      }
    }
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        background: '#f0f0f0', color: '#8c8c8c', fontSize: 12,
        padding: '2px 10px', borderRadius: 999,
      }}>
        <RobotOutlined style={{ fontSize: 12 }} />
        AI 初审
      </span>
    )
  }

  const renderAIReviewDetail = () => {
    const aiResult = record?.ai_review_result
    if (!aiResult || record?.ai_review_status !== 'completed') return null

    const levelLabelMap: Record<string, Record<string, string>> = {
      photo_match_level: { matched: '匹配', partial_match: '部分匹配', unmatched: '不匹配', no_photos: '无照片' },
      measure_quality_level: { adequate: '合格', basic: '基本合格', inadequate: '不合格' },
      completeness_level: { full: '完整', partial: '部分', insufficient: '不足' },
      standard_compliance_level: { compliant: '合规', basically_compliant: '基本合规', non_compliant: '不合规' },
    }

    const levelColorMap: Record<string, string> = {
      matched: 'success', adequate: 'success', full: 'success', compliant: 'success',
      partial_match: 'warning', basic: 'warning', partial: 'warning', basically_compliant: 'warning',
      unmatched: 'error', no_photos: 'error', inadequate: 'error', insufficient: 'error', non_compliant: 'error',
    }

    // 维度定义：key → label、icon、及对应的描述文本字段
    const dims = [
      { key: 'photo_match_level' as const, descKey: 'photo_match_analysis', label: '图片比对', icon: <CameraOutlined /> },
      { key: 'measure_quality_level' as const, descKey: 'measure_quality_assessment', label: '措施质量', icon: <ToolOutlined /> },
      { key: 'completeness_level' as const, descKey: 'completeness_check', label: '完整性', icon: <CheckCircleOutlined /> },
      { key: 'standard_compliance_level' as const, descKey: 'standard_compliance', label: '标准合规', icon: <FileTextOutlined /> },
    ]

    return (
      <div style={{ marginTop: 12 }}>
        {/* 各维度判定：等级 pill + 详细描述 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {dims.map(dim => {
            const level = aiResult[dim.key] as string
            const label = levelLabelMap[dim.key]?.[level] || level || '—'
            const color = levelColorMap[level] || 'default'
            const description = (aiResult as Record<string, unknown>)[dim.descKey] as string | undefined

            return (
              <div key={dim.key} style={{
                padding: '8px 12px',
                borderRadius: 8,
                background: '#fafaf9',
                border: '1px solid #ede9e4',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: description ? 6 : 0 }}>
                  {dim.icon}
                  <Text style={{ fontSize: 13, fontWeight: 600, color: '#3b3833' }}>{dim.label}</Text>
                  <Tag style={{ margin: 0, fontSize: 11, lineHeight: '18px' }} color={color}>{label}</Tag>
                </div>
                {description && (
                  <Text style={{ fontSize: 12, color: '#5d5b54', lineHeight: 1.7, display: 'block' }}>
                    {description}
                  </Text>
                )}
              </div>
            )
          })}
        </div>

        {aiResult.confidence != null && (
          <div style={{ marginTop: 10, textAlign: 'center' }}>
            <Text style={{ fontSize: 12, color: '#8c8c8c' }}>AI 置信度 </Text>
            <Text style={{ fontSize: 13, fontWeight: 600 }}>
              {Math.round(aiResult.confidence * 100)}%
            </Text>
          </div>
        )}
      </div>
    )
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
    if (rStatus === 'ai_reviewing') return pillProcessing(label)
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

  // ── 复核流程 Timeline ──
  // 参照 equipment 模块 WorkOrderDetailDrawer 的 Timeline 交互模式
  const buildReviewTimelineItems = () => {
    const items: Array<{ color: string; icon: React.ReactNode; content: React.ReactNode }> = []

    // ── AI 初审 ──
    const aiStatus = record.ai_review_status || 'pending'
    const aiResult = record.ai_review_result
    let aiColor = '#c8c4be'
    let aiIcon: React.ReactNode = <RobotOutlined style={{ fontSize: 14 }} />

    if (aiStatus === 'completed' && aiResult?.review_conclusion === '通过') {
      aiColor = '#1aae39'
      aiIcon = <CheckCircleOutlined style={{ fontSize: 14 }} />
    } else if (aiStatus === 'completed' && aiResult?.review_conclusion === '不通过') {
      aiColor = '#e03131'
      aiIcon = <CloseCircleOutlined style={{ fontSize: 14 }} />
    } else if (aiStatus === 'processing') {
      aiColor = '#0075de'
      aiIcon = <SyncOutlined spin style={{ fontSize: 14 }} />
    } else if (aiStatus === 'failed') {
      aiColor = '#e03131'
      aiIcon = <ExclamationCircleOutlined style={{ fontSize: 14 }} />
    }

    items.push({
      color: aiColor,
      icon: aiIcon,
      content: (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text strong style={{ fontSize: 14 }}>AI 初审</Text>
              {renderAIReviewStatus()}
            </div>
            {(aiStatus === 'failed') && (
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={aiReviewTriggering}
                onClick={async () => {
                  setAiReviewTriggering(true)
                  try {
                    const res = await triggerRectificationReview(id)
                    if (res.code === 200) {
                      message.success(res.message || 'AI 初审已触发')
                      const updated = await getHazard(id)
                      if (updated?.data) setRecord(updated.data)
                    } else {
                      message.error(res.message || '触发失败')
                    }
                  } catch {
                    message.error('触发 AI 初审失败')
                  } finally {
                    setAiReviewTriggering(false)
                  }
                }}
              >
                重试
              </Button>
            )}
          </div>
          {renderAIReviewDetail()}
        </div>
      ),
    })

    // ── 三级人工复核 ──
    const levelConfigs = [
      { level: 1, label: '部门负责人复核', status: v1 },
      { level: 2, label: '分管领导复核', status: v2 },
      { level: 3, label: '检查人员复核', status: v3 },
    ]

    levelConfigs.forEach(({ level, label, status }) => {
      const isCurrent = currentLevel === level
      const isApproved = status === 'approved'
      const isRejected = status === 'rejected'

      let color = '#c8c4be'
      let icon: React.ReactNode = (
        <span style={{
          display: 'inline-flex', width: 24, height: 24, borderRadius: '50%',
          background: '#f0eeec', color: '#787671',
          alignItems: 'center', justifyContent: 'center',
          fontSize: 12, fontWeight: 700,
        }}>
          {level}
        </span>
      )

      if (isApproved) {
        color = '#1aae39'
        icon = <CheckCircleOutlined style={{ fontSize: 16 }} />
      } else if (isRejected) {
        color = '#e03131'
        icon = <CloseCircleOutlined style={{ fontSize: 16 }} />
      } else if (isCurrent) {
        color = '#1677ff'
        icon = <ClockCircleOutlined style={{ fontSize: 16 }} />
      }

      let statusTag: React.ReactNode = <StatusPill color="#787671" bg="#f0eeec">待开始</StatusPill>
      if (isApproved) statusTag = pillSuccess('已通过')
      else if (isRejected) statusTag = pillError('已驳回')
      else if (isCurrent) statusTag = pillInfo('待复核')

      items.push({
        color,
        icon,
        content: (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text strong style={{ fontSize: 14 }}>{label}</Text>
              {statusTag}
            </div>
            {isCurrent && (
              <Button
                type="primary"
                size="small"
                icon={<CheckCircleOutlined />}
                onClick={() => handleVerify(level)}
              >
                复核
              </Button>
            )}
          </div>
        ),
      })
    })

    return items
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
              extra={
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {renderNotifyStatus(record.rectification_notify_status, record.rectification_notified_at, record.rectification_notify_error)}
                  <Button
                    icon={<SendOutlined />}
                    size="small"
                    loading={notifyRectLoading}
                    onClick={async () => {
                      setNotifyRectLoading(true)
                      try {
                        const res = await notifyRectification(id)
                        if (res.code === 200) {
                          message.success(res.message || '飞书通知已发送')
                          // 刷新数据以展示通知状态
                          const updated = await getHazard(id)
                          if (updated?.data) setRecord(updated.data)
                        } else {
                          message.error(res.message || '发送失败')
                        }
                      } catch {
                        message.error('发送失败，请稍后重试')
                      } finally {
                        setNotifyRectLoading(false)
                      }
                    }}
                  >
                    飞书通知
                  </Button>
                  <EditButton editing={editSection === 'rectification'} loading={saving} onEdit={() => handleEdit('rectification')} onCancel={handleCancelEdit} onSave={handleSave} />
                </div>
              }
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
                  <>
                    {/* AI 初审驳回原因：展示具体不通过的维度，帮助责任人了解需改进方向 */}
                    {record?.ai_review_status === 'completed' && record?.ai_review_result?.review_conclusion === '不通过' && (
                      <div style={{
                        marginTop: 16, padding: 12,
                        background: '#fff2f0', borderRadius: 8,
                        border: '1px solid #ffccc7',
                      }}>
                        <Text style={{ fontSize: 13, fontWeight: 600, color: '#e03131' }}>
                          <RobotOutlined style={{ marginRight: 4 }} />
                          AI 初审驳回（不通过）
                        </Text>
                        <div style={{ marginTop: 8, fontSize: 13, color: '#5d5b54' }}>
                          {(() => {
                            const ar = record.ai_review_result
                            // 每一项包含：问题描述 + 改进指导
                            const items: { problem: string; guidance: string }[] = []
                            if (ar?.photo_match_level === 'no_photos') {
                              items.push({
                                problem: '未提供整改后照片',
                                guidance: '请拍摄整改后的现场照片（同一角度、同一位置），清晰展示缺陷已修复',
                              })
                            }
                            if (ar?.photo_match_level === 'unmatched') {
                              items.push({
                                problem: '整改后图片与原始缺陷不符',
                                guidance: '请确保照片拍摄角度与原始缺陷照片一致，完整覆盖整改区域',
                              })
                            }
                            if (ar?.measure_quality_level === 'inadequate') {
                              items.push({
                                problem: '整改措施不合格（空泛/不可操作）',
                                guidance: '请补充具体的整改措施，包含量化标准、时间节点、责任主体，避免使用「已整改」「已处理」等笼统描述',
                              })
                            }
                            if (ar?.completeness_level === 'insufficient') {
                              items.push({
                                problem: '核心问题未得到处理',
                                guidance: '请对照 AI 识别的关键缺陷逐条回复，确保每项问题都有对应的整改措施',
                              })
                            }
                            if (ar?.standard_compliance_level === 'non_compliant') {
                              items.push({
                                problem: '整改措施不符合标准要求',
                                guidance: '请参照相关法规标准要求，确保整改措施符合规范（可参考上方 AI 审核详情中的法规依据）',
                              })
                            }
                            return items.length > 0 ? items.map((item, i) => (
                              <div key={i} style={{ marginTop: i > 0 ? 10 : 0 }}>
                                <div style={{ fontWeight: 600, color: '#3b3833' }}>
                                  • {item.problem}
                                </div>
                                <div style={{
                                  marginTop: 2, marginLeft: 12, paddingLeft: 8,
                                  borderLeft: '2px solid #e8c55a',
                                  color: '#5d5b54', fontSize: 12, lineHeight: 1.7,
                                }}>
                                  {item.guidance}
                                </div>
                              </div>
                            )) : <Text style={{ color: '#a4a097' }}>详见上方各维度分析</Text>
                          })()}
                        </div>
                      </div>
                    )}
                    <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #ede9e4', display: 'flex', justifyContent: 'center' }}>
                      <Button danger icon={<EditOutlined />} size="middle"
                        onClick={() => handleEdit('rectification')}>
                        重新整改
                      </Button>
                    </div>
                  </>
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
              extra={
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {renderNotifyStatus(record.review_notify_status, record.review_notified_at, record.review_notify_error)}
                  {currentLevel && (
                    <Button
                      icon={<SendOutlined />}
                      size="small"
                      loading={notifyLoading}
                      onClick={async () => {
                        setNotifyLoading(true)
                        try {
                          const res = await notifyReviewer(id)
                          if (res.code === 200) {
                            message.success(res.message || '飞书通知已发送')
                            const updated = await getHazard(id)
                            if (updated?.data) setRecord(updated.data)
                          } else {
                            message.error(res.message || '发送失败')
                          }
                        } catch {
                          message.error('发送失败，请稍后重试')
                        } finally {
                          setNotifyLoading(false)
                        }
                      }}
                    >
                      飞书通知
                    </Button>
                  )}
                </div>
              }
            />

            {/* ── 四级复核 Timeline（参照 equipment 模块 WorkOrderDetailDrawer）── */}
            <Timeline
              items={buildReviewTimelineItems()}
              style={{ marginTop: 4 }}
            />

            {/* 已关闭状态 */}
            {!currentLevel && (rStatus === 'completed' || rStatus === 'closed') && (
              <div style={{ textAlign: 'center', marginTop: 20, paddingTop: 16, borderTop: '1px solid #ede9e4' }}>
                {pillSuccess('整改已关闭')}
              </div>
            )}
          </StageCard>
        </div>
      </div>
    </div>
  )
}
