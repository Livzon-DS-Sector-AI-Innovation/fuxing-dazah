'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import {
  Button,
  Descriptions,
  Tag,
  Spin,
  Select,
  Input,
  message,
} from 'antd'
import { ArrowLeftOutlined, ArrowUpOutlined, ArrowDownOutlined, EditOutlined, SaveOutlined, CloseOutlined, SyncOutlined } from '@ant-design/icons'
import { Candidate } from '@/types/hr'
import { updateCandidateAction, updateCandidateRecommendationLevelAction, syncCandidateToFeishuAction } from '@/actions/hr'

const AIReportPanel = dynamic(
  () => import('./AIReportPanel'),
  { ssr: false }
)

interface CandidateDetailClientProps {
  candidate: Candidate
}

export default function CandidateDetailClient({
  candidate,
}: CandidateDetailClientProps) {
  const router = useRouter()
  const [pdfLoading, setPdfLoading] = useState(true)
  const [pdfError, setPdfError] = useState(false)
  const [recommendationLevel, setRecommendationLevel] = useState(
    candidate.recommendation_level || ''
  )
  const [updating, setUpdating] = useState(false)
  const [navContext, setNavContext] = useState<{
    ids: string[]
    currentIndex: number
  } | null>(null)

  const [isEditing, setIsEditing] = useState(false)
  const [formData, setFormData] = useState({
    position: candidate.position,
    gender: candidate.gender || '',
    school: candidate.school || '',
    education: candidate.education || '',
    major: candidate.major || '',
  })
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    const raw = sessionStorage.getItem('candidate_list_context')
    if (raw) {
      try {
        const parsed = JSON.parse(raw)
        if (parsed.ids && parsed.ids.includes(candidate.id)) {
          setNavContext(parsed)
        }
      } catch {
        // ignore invalid sessionStorage data
      }
    }
  }, [candidate.id])

  const handlePrev = () => {
    if (!navContext) return
    const prevIndex = navContext.currentIndex - 1
    const prevId = navContext.ids[prevIndex]
    if (prevId) {
      const updated = { ...navContext, currentIndex: prevIndex }
      sessionStorage.setItem('candidate_list_context', JSON.stringify(updated))
      router.push(`/hr/recruitment/${prevId}`)
    }
  }

  const handleNext = () => {
    if (!navContext) return
    const nextIndex = navContext.currentIndex + 1
    const nextId = navContext.ids[nextIndex]
    if (nextId) {
      const updated = { ...navContext, currentIndex: nextIndex }
      sessionStorage.setItem('candidate_list_context', JSON.stringify(updated))
      router.push(`/hr/recruitment/${nextId}`)
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => {
      if (pdfLoading) {
        setPdfError(true)
        setPdfLoading(false)
      }
    }, 30000)
    return () => clearTimeout(timer)
  }, [pdfLoading])

  const handleUpdateRecommendation = async (value: string) => {
    if (!value || value === candidate.recommendation_level) return
    setUpdating(true)
    try {
      await updateCandidateRecommendationLevelAction(candidate.id, value)
      setRecommendationLevel(value)
      message.success('推荐等级更新成功')
    } catch (err: any) {
      message.error(err.message || '更新失败')
    } finally {
      setUpdating(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateCandidateAction(candidate.id, {
        position: formData.position,
        gender: formData.gender || undefined,
        school: formData.school || undefined,
        education: formData.education || undefined,
        major: formData.major || undefined,
      })
      message.success('保存成功')
      setIsEditing(false)
      router.refresh()
    } catch (err: any) {
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleCancel = () => {
    setFormData({
      position: candidate.position,
      gender: candidate.gender || '',
      school: candidate.school || '',
      education: candidate.education || '',
      major: candidate.major || '',
    })
    setIsEditing(false)
  }

  const handleSyncToFeishu = async () => {
    setSyncing(true)
    try {
      await syncCandidateToFeishuAction(candidate.id)
      message.success('已成功同步到飞书')
      router.refresh()
    } catch (err: any) {
      message.error(err.message || '同步到飞书失败')
    } finally {
      setSyncing(false)
    }
  }

  const recommendationOptions = [
    { value: '强烈推荐', label: '强烈推荐' },
    { value: '推荐', label: '推荐' },
    { value: '待定', label: '待定' },
    { value: '不推荐', label: '不推荐' },
  ]

  const recommendationColors: Record<string, string> = {
    '强烈推荐': 'green',
    '推荐': 'blue',
    '待定': 'orange',
    '不推荐': 'red',
  }

  const tagPalette: Record<string, string> = {
    blue: 'background:#e6f4ff;color:#0958d9',
    yellow: 'background:#fffbe6;color:#d48806',
    red: 'background:#fff2f0;color:#cf1322',
    green: 'background:#f6ffed;color:#389e0d',
    orange: 'background:#fff7e6;color:#d46b08',
    purple: 'background:#f9f0ff;color:#531dab',
  }

  const processedReport = (candidate.match_report || '暂无报告').replace(
    /<text_tag\s+color=['"]([^'"]+)['"]\s*>([\s\S]*?)<\/text_tag>/g,
    (_, color, content) => {
      const style = tagPalette[color] || `background:${color}20;color:${color}`
      return `<span style="display:inline-block;padding:1px 8px;border-radius:4px;font-size:12px;${style}">${content}</span>`
    }
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/hr/recruitment')}>
          返回列表
        </Button>
        {navContext && (
          <>
            <Button
              icon={<ArrowUpOutlined />}
              onClick={handlePrev}
              disabled={navContext.currentIndex <= 0}
            >
              上一条
            </Button>
            <Button
              icon={<ArrowDownOutlined />}
              onClick={handleNext}
              disabled={navContext.currentIndex >= navContext.ids.length - 1}
            >
              下一条
            </Button>
          </>
        )}
      </div>

      <div className="flex gap-4" style={{ height: 'calc(100vh - 100px)' }}>
        {/* 左侧：PDF 预览 */}
        <div className="flex-[3] bg-white rounded-xl border border-[#e5e3df] overflow-hidden relative">
          <Spin
            spinning={pdfLoading}
            className="absolute inset-0 z-10 flex items-center justify-center"
          />
          {pdfError && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-white">
              <p className="text-gray-500 mb-4">简历加载失败，请尝试重新同步</p>
              <Button onClick={() => window.location.reload()}>
                刷新页面
              </Button>
            </div>
          )}
          <iframe
            src={`/api/v1/hr/candidates/${candidate.id}/resume-preview`}
            className="w-full h-full border-0"
            onLoad={() => setPdfLoading(false)}
            title="简历预览"
          />
        </div>

        {/* 右侧：候选人信息 */}
        <div className="flex-[2] bg-white rounded-xl border border-[#e5e3df] p-6 overflow-auto">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold">{candidate.name}</h2>
              {recommendationLevel && (
                <Tag color={recommendationColors[recommendationLevel] || 'default'}>
                  {recommendationLevel}
                </Tag>
              )}
            </div>
            <div className="flex gap-2">
              {isEditing ? (
                <>
                  <Button
                    icon={<SaveOutlined />}
                    type="primary"
                    loading={saving}
                    onClick={handleSave}
                  >
                    保存修改
                  </Button>
                  <Button
                    icon={<CloseOutlined />}
                    onClick={handleCancel}
                    disabled={saving}
                  >
                    取消
                  </Button>
                </>
              ) : (
                <Button icon={<EditOutlined />} onClick={() => setIsEditing(true)}>
                  编辑
                </Button>
              )}
            </div>
          </div>

          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="飞书同步状态">
              <div className="flex items-center gap-2">
                {candidate.feishu_sync_status === 'synced' ? (
                  <Tag color="success">已同步</Tag>
                ) : candidate.feishu_sync_status === 'failed' ? (
                  <Tag color="error">同步失败</Tag>
                ) : (
                  <Tag>未同步</Tag>
                )}
                {candidate.feishu_sync_status !== 'synced' && (
                  <Button
                    size="small"
                    icon={<SyncOutlined spin={syncing} />}
                    loading={syncing}
                    onClick={handleSyncToFeishu}
                  >
                    {candidate.feishu_sync_status === 'failed' ? '重新同步' : '同步到飞书'}
                  </Button>
                )}
              </div>
              {candidate.feishu_sync_error && (
                <div className="text-xs text-red-500 mt-1">{candidate.feishu_sync_error}</div>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="应聘职位">
              {isEditing ? (
                <Input
                  value={formData.position}
                  onChange={(e) =>
                    setFormData({ ...formData, position: e.target.value })
                  }
                />
              ) : (
                candidate.position
              )}
            </Descriptions.Item>
            <Descriptions.Item label="性别">
              {isEditing ? (
                <Input
                  value={formData.gender}
                  onChange={(e) =>
                    setFormData({ ...formData, gender: e.target.value })
                  }
                  placeholder="请输入性别"
                />
              ) : (
                candidate.gender || '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="学校">
              {isEditing ? (
                <Input
                  value={formData.school}
                  onChange={(e) =>
                    setFormData({ ...formData, school: e.target.value })
                  }
                  placeholder="请输入学校"
                />
              ) : (
                candidate.school || '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="学历">
              {isEditing ? (
                <Input
                  value={formData.education}
                  onChange={(e) =>
                    setFormData({ ...formData, education: e.target.value })
                  }
                  placeholder="请输入学历"
                />
              ) : (
                <Tag color="blue">{candidate.education || '-'}</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="专业">
              {isEditing ? (
                <Input
                  value={formData.major}
                  onChange={(e) =>
                    setFormData({ ...formData, major: e.target.value })
                  }
                  placeholder="请输入专业"
                />
              ) : (
                candidate.major || '-'
              )}
            </Descriptions.Item>
          </Descriptions>

          <div className="mt-6">
            <h3 className="text-lg font-medium mb-3">AI 匹配度报告</h3>
            <AIReportPanel content={processedReport} />
          </div>

          <div className="mt-6 pt-6 border-t border-gray-100">
            <h3 className="text-lg font-medium mb-3">标记候选人情况</h3>
            <Select
              style={{ width: '100%' }}
              placeholder="选择推荐等级"
              value={recommendationLevel || undefined}
              onChange={handleUpdateRecommendation}
              options={recommendationOptions}
              loading={updating}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
