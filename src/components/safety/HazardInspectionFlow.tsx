'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  Steps,
  Button,
  Space,
  Typography,
  App,
  Drawer,
  Empty,
  Spin,
  Result,
  Card,
  Divider,
} from 'antd'
import {
  CheckCircleOutlined,
  LoadingOutlined,
  RobotOutlined,
  EditOutlined,
  FileTextOutlined,
  InboxOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  BankOutlined,
  ClockCircleOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import HazardInspectionForm from './HazardInspectionForm'
import type { InspectionFormValues } from './HazardInspectionForm'
import HazardAIResultPanel from './HazardAIResultPanel'
import {
  createHazard,
  updateHazard,
  getHazards,
  runHazardAI,
  deleteHazard,
  uploadHazardPhoto,
} from '@/actions/safety'
import type { HazardReport } from '@/types/safety'
import dayjs from 'dayjs'

const { Text, Title } = Typography

type FlowStep = 'form' | 'analyzing' | 'review' | 'done'

interface Props {
  variant?: 'page' | 'drawer'
  onDone?: () => void
}

// ═══════════════════════════════════════════════════════════
// 视觉组件
// ═══════════════════════════════════════════════════════════

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
  children,
}: {
  accentColor: string
  children: React.ReactNode
}) {
  return (
    <div
      style={{
        position: 'relative',
        background: '#ffffff',
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

// ═══════════════════════════════════════════════════════════

export default function HazardInspectionFlow({ variant = 'page', onDone }: Props) {
  const router = useRouter()
  const { message } = App.useApp()

  // ── 流程状态 ──
  const [currentStep, setCurrentStep] = useState<FlowStep>('form')
  const [currentHazard, setCurrentHazard] = useState<HazardReport | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [aiProgress, setAiProgress] = useState<'idle' | 'script1' | 'script2' | 'done' | 'error'>('idle')

  // ── 草稿箱状态 ──
  const [draftDrawerOpen, setDraftDrawerOpen] = useState(false)
  const [drafts, setDrafts] = useState<HazardReport[]>([])
  const [draftsLoading, setDraftsLoading] = useState(false)
  const [draftFormValues, setDraftFormValues] = useState<InspectionFormValues | undefined>()

  // ── 已完成状态 ──
  const [completedHazardNo, setCompletedHazardNo] = useState('')

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

  // 加载草稿列表
  const loadDrafts = useCallback(async () => {
    setDraftsLoading(true)
    try {
      const res = await getHazards({
        overall_status: 'draft',
        page_size: 50,
      })
      if (res.code === 200) {
        setDrafts(res.data)
      }
    } catch {
      // 静默失败
    } finally {
      setDraftsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDrafts()
  }, [loadDrafts])

  // ── 提交隐患 → 创建/更新记录 + 上传图片 + 触发AI ──
  const handleSubmit = async (values: InspectionFormValues, files: File[]) => {
    setSubmitting(true)
    try {
      let hazard: HazardReport

      if (currentHazard) {
        const updateRes = await updateHazard(currentHazard.id, {
          inspection_category: values.inspection_category,
          discovered_by: values.discovered_by,
          discovered_by_name: values.discovered_by_name,
          inspector_department: values.inspector_department,
          department: values.department,
          discovered_at: values.discovered_at,
          description: values.description,
          overall_status: 'draft',
        } as any)
        if (updateRes.code !== 200) {
          message.error(updateRes.message || '更新失败')
          setSubmitting(false)
          return
        }
        hazard = updateRes.data as HazardReport
      } else {
        const createRes = await createHazard({
          hazard_no: '',
          inspection_category: values.inspection_category,
          discovered_by: values.discovered_by,
          discovered_by_name: values.discovered_by_name,
          inspector_department: values.inspector_department,
          department: values.department,
          discovered_at: values.discovered_at,
          description: values.description,
        } as any)
        if (createRes.code !== 200) {
          message.error(createRes.message || '创建失败')
          setSubmitting(false)
          return
        }
        hazard = createRes.data as HazardReport
      }

      setCurrentHazard(hazard)

      // 上传图片
      if (files.length > 0) {
        for (const file of files) {
          try {
            await uploadHazardPhoto(hazard.id, file as unknown as File)
          } catch {
            console.error('图片上传失败')
          }
        }
      }

      // 进入AI分析阶段
      setCurrentStep('analyzing')
      setAiProgress('script1')

      // 执行 AI Step 1
      const r1 = await runHazardAI(hazard.id, 1)
      if (r1.code !== 200) {
        message.warning('AI 识别失败：' + (r1.message || '未知错误'))
        setAiProgress('error')
        const updated = await refreshHazard(hazard.id)
        setCurrentHazard(updated)
        setCurrentStep('review')
        return
      }

      setAiProgress('script2')

      // 执行 AI Step 2
      const r2 = await runHazardAI(hazard.id, 2)
      if (r2.code !== 200) {
        message.warning('AI 整改建议生成失败：' + (r2.message || '未知错误'))
        setAiProgress('error')
      } else {
        setAiProgress('done')
      }

      const updated = await refreshHazard(hazard.id)
      setCurrentHazard(updated)
      setCurrentStep('review')
    } catch (err) {
      console.error('提交失败:', err)
      message.error('提交失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  // ── 保存草稿 ──
  const handleSaveDraft = async (values: InspectionFormValues, files: File[]) => {
    setSubmitting(true)
    try {
      let hazard: HazardReport

      if (currentHazard) {
        const updateRes = await updateHazard(currentHazard.id, {
          inspection_category: values.inspection_category,
          discovered_by: values.discovered_by,
          discovered_by_name: values.discovered_by_name,
          inspector_department: values.inspector_department,
          department: values.department,
          discovered_at: values.discovered_at,
          description: values.description,
          overall_status: 'draft',
        } as any)
        if (updateRes.code !== 200) {
          message.error(updateRes.message || '保存草稿失败')
          return
        }
        hazard = updateRes.data as HazardReport
      } else {
        const createRes = await createHazard({
          hazard_no: '',
          inspection_category: values.inspection_category,
          discovered_by: values.discovered_by,
          discovered_by_name: values.discovered_by_name,
          inspector_department: values.inspector_department,
          department: values.department,
          discovered_at: values.discovered_at,
          description: values.description,
          overall_status: 'draft',
        } as any)
        if (createRes.code !== 200) {
          message.error(createRes.message || '保存草稿失败')
          return
        }
        hazard = createRes.data as HazardReport
      }

      // 上传图片
      if (files.length > 0) {
        for (const file of files) {
          try {
            const formData = new FormData()
            formData.append('file', file)
            await fetch(`${API_BASE}/safety/hazards/${hazard.id}/upload-photo`, {
              method: 'POST',
              body: formData,
            })
          } catch {
            // 静默失败
          }
        }
      }

      message.success('草稿已保存')
      await loadDrafts()
      setCurrentStep('form')
      setCurrentHazard(null)
      setDraftFormValues(undefined)
    } catch {
      message.error('保存草稿失败')
    } finally {
      setSubmitting(false)
    }
  }

  // ── 确认入库 ──
  const handleConfirm = async (edits: Partial<Record<string, string>>) => {
    if (!currentHazard) return
    setConfirming(true)
    try {
      if (Object.keys(edits).length > 0) {
        const updateRes = await updateHazard(currentHazard.id, edits as any)
        if (updateRes.code !== 200) {
          message.error(updateRes.message || '更新失败')
          setConfirming(false)
          return
        }
      }

      message.success('隐患已确认入库！')
      setCompletedHazardNo(currentHazard.hazard_no)
      setCurrentStep('done')
    } catch {
      message.error('确认操作失败')
    } finally {
      setConfirming(false)
    }
  }

  // ── 重新AI分析 ──
  const handleRerun = async () => {
    if (!currentHazard) return
    setCurrentStep('analyzing')
    setAiProgress('script1')

    try {
      const r1 = await runHazardAI(currentHazard.id, 1)
      if (r1.code !== 200) {
        message.warning('AI 识别失败：' + (r1.message || ''))
        setAiProgress('error')
        const updated = await refreshHazard(currentHazard.id)
        setCurrentHazard(updated)
        setCurrentStep('review')
        return
      }

      setAiProgress('script2')
      const r2 = await runHazardAI(currentHazard.id, 2)
      if (r2.code !== 200) {
        message.warning('AI 整改建议生成失败：' + (r2.message || ''))
        setAiProgress('error')
      } else {
        setAiProgress('done')
      }

      const updated = await refreshHazard(currentHazard.id)
      setCurrentHazard(updated)
      setCurrentStep('review')
    } catch {
      message.error('AI 重新执行失败')
      setCurrentStep('review')
    }
  }

  // ── 刷新隐患数据 ──
  const refreshHazard = async (id: string): Promise<HazardReport | null> => {
    const res = await fetch(`${API_BASE}/safety/hazards/${id}`)
    if (res.ok) {
      const json = await res.json()
      return json.data || json
    }
    return null
  }

  // ── 从草稿继续登记 ──
  const handleContinueDraft = (draft: HazardReport) => {
    setDraftFormValues({
      inspection_category: draft.inspection_category,
      discovered_by: draft.discovered_by,
      discovered_by_name: draft.discovered_by_name,
      inspector_department: draft.inspector_department,
      department: draft.department,
      discovered_at: draft.discovered_at,
      description: draft.description,
    })
    setCurrentHazard(draft)
    setDraftDrawerOpen(false)
    setCurrentStep('form')
  }

  // ── 删除草稿 ──
  const handleDeleteDraft = async (id: string) => {
    try {
      const res = await deleteHazard(id)
      if (res.code === 200) {
        message.success('草稿已删除')
        await loadDrafts()
      } else {
        message.error(res.message || '删除失败')
      }
    } catch {
      message.error('删除失败')
    }
  }

  // ── 开始新登记 ──
  const handleNewInspection = () => {
    setCurrentStep('form')
    setCurrentHazard(null)
    setDraftFormValues(undefined)
    setCompletedHazardNo('')
    setAiProgress('idle')
  }

  const handleGoToLedger = () => {
    if (variant === 'drawer' && onDone) {
      onDone()
    } else {
      router.push('/safety/hazard-ledger')
    }
  }

  // ── 步骤条配置 ──
  const stepItems = [
    { title: '隐患登记', icon: <EditOutlined /> },
    { title: 'AI分析', icon: <RobotOutlined /> },
    { title: '确认结果', icon: <CheckCircleOutlined /> },
    { title: '完成', icon: <FileTextOutlined /> },
  ]

  const currentStepIndex =
    currentStep === 'form'
      ? 0
      : currentStep === 'analyzing'
        ? 1
        : currentStep === 'review'
          ? 2
          : 3

  const content = (
    <>
      {/* ── 步骤条 ── */}
      <Card style={{ borderRadius: 12, border: '1px solid #e5e3df', marginBottom: 24 }}>
        <Steps
          current={currentStepIndex}
          size="small"
          items={stepItems.map((item, i) => ({
            title: item.title,
            icon:
              currentStepIndex > i ? (
                <CheckCircleOutlined />
              ) : currentStepIndex === i && currentStep === 'analyzing' ? (
                <LoadingOutlined />
              ) : (
                item.icon
              ),
          }))}
        />
      </Card>

      {/* ── Step 1: 登记表单 ── */}
      {currentStep === 'form' && (
        <HazardInspectionForm
          key={currentHazard?.id || 'new'}
          initialValues={draftFormValues}
          loading={submitting}
          onSubmit={handleSubmit}
          onSaveDraft={handleSaveDraft}
        />
      )}

      {/* ── Step 2: AI 分析中 ── */}
      {currentStep === 'analyzing' && (
        <StageCard accentColor="#5645d4">
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <Spin size="large" />
            <div style={{ marginTop: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 16 }}>
                <RobotOutlined style={{ color: '#5645d4', fontSize: 20 }} />
                <Title level={4} style={{ margin: 0, color: '#1a1a1a' }}>
                  AI 正在分析中
                </Title>
              </div>
              <Space orientation="vertical" size="middle" style={{ marginTop: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {aiProgress === 'script1' ? (
                    <LoadingOutlined style={{ color: '#5645d4' }} />
                  ) : aiProgress === 'script2' || aiProgress === 'done' ? (
                    <CheckCircleOutlined style={{ color: '#1aae39' }} />
                  ) : aiProgress === 'error' ? (
                    <ExclamationCircleOutlined style={{ color: '#dd5b00' }} />
                  ) : null}
                  <Text style={{ fontSize: 14 }}>
                    {aiProgress === 'script1'
                      ? '正在识别隐患信息（Step 1）...'
                      : aiProgress === 'script2'
                        ? '正在生成整改建议（Step 2）...'
                        : aiProgress === 'done'
                          ? 'AI 分析完成'
                          : aiProgress === 'error'
                            ? 'AI 分析遇到问题'
                            : '准备中...'}
                  </Text>
                </div>
              </Space>
              {currentHazard && (
                <Text type="secondary" style={{ display: 'block', marginTop: 16 }}>
                  编号：{currentHazard.hazard_no}
                </Text>
              )}
            </div>
          </div>
        </StageCard>
      )}

      {/* ── Step 3: AI 结果确认 ── */}
      {currentStep === 'review' && currentHazard && (
        <HazardAIResultPanel
          hazard={currentHazard}
          confirming={confirming}
          onConfirm={handleConfirm}
          onRerun={handleRerun}
        />
      )}

      {/* ── Step 4: 完成 ── */}
      {currentStep === 'done' && (
        <StageCard accentColor="#1aae39">
          <Result
            status="success"
            title="隐患已确认入库！"
            subTitle={`编号：${completedHazardNo || currentHazard?.hazard_no || ''}`}
            extra={[
              <Button
                type="primary"
                key="ledger"
                onClick={handleGoToLedger}
              >
                前往台账查看
              </Button>,
              <Button key="new" onClick={handleNewInspection}>
                继续登记新隐患
              </Button>,
            ]}
          />
        </StageCard>
      )}

      {/* ── 草稿箱抽屉 ── */}
      <Drawer
        title={
          <Space>
            <InboxOutlined />
            <span>草稿箱</span>
            {drafts.length > 0 && (
              <StatusPill color="#0075de" bg="#dcecfa">{String(drafts.length)}</StatusPill>
            )}
          </Space>
        }
        open={draftDrawerOpen}
        onClose={() => setDraftDrawerOpen(false)}
        styles={{ body: { padding: '16px 24px' } }}
        size={420}
      >
        {draftsLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : drafts.length === 0 ? (
          <Empty description="暂无草稿记录" />
        ) : (
          <div>
            {drafts.map((draft, idx) => (
              <div key={draft.id}>
                {idx > 0 && <Divider style={{ margin: '8px 0' }} />}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    padding: '4px 0',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Space style={{ marginBottom: 4 }}>
                      <Text strong style={{ fontSize: 13 }}>
                        {draft.hazard_no || '未编号'}
                      </Text>
                      {draft.inspection_category && (
                        <StatusPill color="#5d5b54" bg="#f0eeec">{draft.inspection_category}</StatusPill>
                      )}
                    </Space>
                    <div style={{ fontSize: 12 }}>
                      {draft.department && (
                        <Text type="secondary" style={{ display: 'block' }}>
                          <BankOutlined style={{ marginRight: 4 }} />
                          {draft.department}
                        </Text>
                      )}
                      <Text type="secondary" style={{ display: 'block' }}>
                        <ClockCircleOutlined style={{ marginRight: 4 }} />
                        {draft.created_at
                          ? dayjs(draft.created_at).format('YYYY-MM-DD HH:mm')
                          : '-'}
                      </Text>
                    </div>
                  </div>
                  <Space style={{ flexShrink: 0, marginLeft: 12 }}>
                    <Button
                      type="link"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => handleContinueDraft(draft)}
                    >
                      继续登记
                    </Button>
                    <Button
                      type="link"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDeleteDraft(draft.id)}
                    />
                  </Space>
                </div>
              </div>
            ))}
          </div>
        )}
      </Drawer>
    </>
  )

  // ── Page variant: wrap with page container + header ──
  if (variant === 'page') {
    return (
      <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: '#1a1a1a' }}>
                隐患登记
              </h1>
              <Text style={{ color: '#5d5b54' }}>登记隐患信息并智能分析</Text>
            </div>
            <Space>
              <Button icon={<InboxOutlined />} onClick={() => { loadDrafts(); setDraftDrawerOpen(true) }}>
                草稿箱
                {drafts.length > 0 && (
                  <StatusPill color="#0075de" bg="#dcecfa">{String(drafts.length)}</StatusPill>
                )}
              </Button>
            </Space>
          </div>
        </div>
        {content}
      </div>
    )
  }

  // ── Drawer variant: minimal container (drawer provides padding) ──
  return (
    <div>
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <SearchOutlined style={{ color: '#5645d4', fontSize: 18 }} />
          <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>隐患登记</span>
        </div>
        <Button icon={<InboxOutlined />} onClick={() => { loadDrafts(); setDraftDrawerOpen(true) }}>
          草稿箱
          {drafts.length > 0 && (
            <StatusPill color="#0075de" bg="#dcecfa">{String(drafts.length)}</StatusPill>
          )}
        </Button>
      </div>
      {content}
    </div>
  )
}
