'use client'

// AI 模型段（三期从 AiConfigPanel 拆出）：五张可编辑模型卡（对话组 3 列 + RAG 组 2 列）
// 数据来自共享控制器（AiConfigProvider）；挂载时 ensure() 触发懒加载。
// GET 失败 → 整区 Alert + 重试（不发永久 Skeleton）；右上重载按钮 = 重拉配置（丢弃未保存草稿）。

import { useEffect } from 'react'
import { Alert, Button, Skeleton, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import type { AiConfigData, AiModelConfig, AiModelProfile } from '@/types/safety'
import AiConfigModelCard from '../AiConfigModelCard'
import { AI_PROFILE_UI, CARD_STYLE, UI } from '../schedulerConfigConstants'
import { useAiConfigController } from './AiConfigController'

/** 五卡分组（对话模型组 3 列 / RAG 检索模型组 2 列） */
const DIALOG_GROUP: AiModelProfile[] = ['text', 'text_backup', 'vision']
const RAG_GROUP: AiModelProfile[] = ['embedding', 'rerank']

/**
 * profile → 模型配置（text_backup 适配：后端维持嵌套时以 text_model.backup 回退构造；
 * backup 仅含 configured/model/api_key_masked，base_url/timeout/source 未知 → 空值/隐藏 tag）
 */
function getProfileModel(
  data: AiConfigData | null,
  profile: AiModelProfile,
): AiModelConfig | null | undefined {
  if (!data) return undefined
  switch (profile) {
    case 'text':
      return data.text_model ?? null
    case 'text_backup': {
      if (data.text_backup_model !== undefined && data.text_backup_model !== null) {
        return data.text_backup_model
      }
      const backup = data.text_model.backup
      if (!backup) return null
      return {
        configured: backup.configured,
        model: backup.model,
        base_url: backup.base_url ?? null,
        timeout: backup.timeout ?? null,
        temperature: null,
        api_key_masked: backup.api_key_masked,
        api_key_set: backup.api_key_set,
        source: backup.source,
        backup: null,
      }
    }
    case 'vision':
      return data.vision_model ?? null
    case 'embedding':
      return data.embedding_model ?? null
    case 'rerank':
      return data.rerank_model ?? null
  }
}

function CardGrid({ profiles }: { profiles: AiModelProfile[] }) {
  const { data, loading, savingProfile, handleSave, handleTest } = useAiConfigController()
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
        gap: 16,
        alignItems: 'stretch',
      }}
    >
      {profiles.map((profile) => (
        <AiConfigModelCard
          key={profile}
          profile={profile}
          color={AI_PROFILE_UI[profile].color}
          hint={AI_PROFILE_UI[profile].hint}
          config={getProfileModel(data, profile)}
          loading={loading && !data}
          saving={savingProfile === profile}
          onSave={handleSave}
          onTest={handleTest}
        />
      ))}
    </div>
  )
}

export default function AiModelsSection() {
  const { data, loading, loadError, load, ensure, savingScenarios } = useAiConfigController()

  useEffect(() => {
    ensure()
  }, [ensure])

  const sectionTitle = (text: string) => (
    <div style={{ fontSize: 13, fontWeight: 600, color: UI.slate, marginBottom: 8, marginTop: 20 }}>
      {text}
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
        <Tooltip title="重拉配置（未保存修改将被丢弃）">
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void load()}
            loading={loading}
            disabled={savingScenarios.size > 0}
            title="刷新"
          />
        </Tooltip>
      </div>

      {loading && !data ? (
        /* 区级 Skeleton（初始加载） */
        <div style={{ ...CARD_STYLE, padding: 16 }}>
          <Skeleton active paragraph={{ rows: 10 }} />
        </div>
      ) : loadError ? (
        /* GET 失败：整区 Alert + 重试 */
        <Alert
          type="error"
          showIcon
          style={{ ...CARD_STYLE, padding: 16 }}
          message={<span style={{ fontSize: 13, fontWeight: 600 }}>AI 配置加载失败</span>}
          description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : (
        <>
          {/* 对话模型组（文本 / 文本备用 / 视觉，3 列） */}
          {sectionTitle('对话模型')}
          <CardGrid profiles={DIALOG_GROUP} />

          {/* RAG 检索模型组（向量 / 重排，2 列） */}
          {sectionTitle('RAG 检索模型')}
          <CardGrid profiles={RAG_GROUP} />
        </>
      )}
    </div>
  )
}
