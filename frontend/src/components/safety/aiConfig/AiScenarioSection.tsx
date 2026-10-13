'use client'

// AI 场景段（三期从 AiConfigPanel 拆出）：AI 调用功能表——场景启停 / 模型绑定行内可配置
// 筛选（搜索/模型类型/渠道/启停状态）为本段局部状态；数据与行内保存走共享控制器。
// 旧后端兼容：enabled 等三期字段缺省 → Switch disabled + 绑定「—」+ 来源「—」（只读降级，不误导 PUT）。

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Button, Empty, Input, Segmented, Select, Skeleton, Space, Switch, Table, Tag, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import type {
  AiConfigSource,
  AiFunctionItem,
  AiModelProfile,
} from '@/types/safety'
import { AI_PROFILE_UI, CARD_STYLE, MONO_FONT, UI, ModelTypeTag, SourceTag } from '../schedulerConfigConstants'
import { ChannelTag } from '../aiAuditConstants'
import { DEFAULT_BINDING, useAiConfigController } from './AiConfigController'

const MODEL_TYPE_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '文本', value: 'text' },
  { label: '视觉', value: 'vision' },
]

/** 启用状态筛选（enabled 未返回的行不参与特定态过滤） */
const ENABLED_STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '启用', value: 'enabled' },
  { label: '停用', value: 'disabled' },
]

/**
 * 绑定白名单：后端 allowed_profiles 为事实源；
 * 缺省/空时按 model_type/id 推导（text→[text,text_backup]、vision→[vision]、embedding/rerank→[自身]）。
 */
function getAllowedProfiles(f: AiFunctionItem): AiModelProfile[] {
  if (f.allowed_profiles && f.allowed_profiles.length > 0) return f.allowed_profiles
  if (f.model_type === 'vision') return ['vision']
  if (f.id === 'embedding') return ['embedding']
  if (f.id === 'rerank') return ['rerank']
  return ['text', 'text_backup']
}

export default function AiScenarioSection() {
  const { data, loading, savingScenarios, handleChangeBinding, handleToggleScenario, load, ensure } =
    useAiConfigController()

  // 功能表筛选（本段局部状态）
  const [keyword, setKeyword] = useState('')
  const [modelType, setModelType] = useState<string>('all')
  const [channel, setChannel] = useState<string | undefined>()
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all')

  useEffect(() => {
    ensure()
  }, [ensure])

  // 前端筛选：搜索 + 模型类型 + 渠道 + 启用状态（enabled 未返回的行不参与特定态过滤）
  const filteredFunctions = useMemo(() => {
    const list = data?.functions ?? []
    const kw = keyword.trim().toLowerCase()
    return list.filter((f) => {
      if (modelType !== 'all' && f.model_type !== modelType) return false
      if (channel && f.channel !== channel) return false
      if (enabledFilter === 'enabled' && f.enabled !== true) return false
      if (enabledFilter === 'disabled' && f.enabled !== false) return false
      if (
        kw &&
        !(
          f.label.toLowerCase().includes(kw) ||
          f.id.toLowerCase().includes(kw) ||
          (f.description ?? '').toLowerCase().includes(kw)
        )
      )
        return false
      return true
    })
  }, [data, keyword, modelType, channel, enabledFilter])

  const channelOptions = useMemo(() => {
    const set = new Set(
      (data?.functions ?? []).map((f) => f.channel).filter((c): c is string => !!c),
    )
    return [...set].map((c) => ({ value: c, label: c }))
  }, [data])

  /** 启停计数（全量，非筛选后：计数摘要） */
  const enabledCount = useMemo(
    () => (data?.functions ?? []).filter((f) => f.enabled === true).length,
    [data],
  )
  const disabledCount = useMemo(
    () => (data?.functions ?? []).filter((f) => f.enabled === false).length,
    [data],
  )

  /** 模型绑定单元格：旧后端降级「—」/ 白名单 ≤1 只读「固定」/ 可编辑 Select */
  const renderBindingCell = (f: AiFunctionItem) => {
    if (f.enabled === undefined) {
      return <span style={{ fontSize: 12, color: UI.muted }}>—</span>
    }
    const allowed = getAllowedProfiles(f)
    if (allowed.length <= 1) {
      const effective = f.effective_profile ?? allowed[0]
      const label = effective ? AI_PROFILE_UI[effective]?.label ?? effective : null
      const cell = (
        <span style={{ whiteSpace: 'nowrap' }}>
          <span style={{ fontSize: 13, color: UI.slate }}>
            {effective && label ? `${label}（${effective}）` : '—'}
          </span>
          <Tag
            style={{
              marginLeft: 8,
              borderRadius: 6,
              background: UI.gray,
              color: UI.steel,
              borderColor: UI.hairline,
            }}
          >
            固定
          </Tag>
        </span>
      )
      const tip = effective ? `该场景仅可使用 ${effective}，绑定不可修改` : '该场景绑定不可修改'
      return <Tooltip title={tip}>{cell}</Tooltip>
    }
    const select = (
      <Select
        size="small"
        style={{ width: 184 }}
        value={f.model_profile ?? DEFAULT_BINDING}
        data-testid={`ai-scenario-binding-${f.id}`}
        disabled={savingScenarios.has(f.id)}
        options={[
          { value: DEFAULT_BINDING, label: '默认（按场景类型）' },
          ...allowed.map((p) => ({ value: p, label: `${AI_PROFILE_UI[p]?.label ?? p}（${p}）` })),
        ]}
        onChange={(v) => void handleChangeBinding(f, v)}
      />
    )
    // agent_chat 场景绑定不生效（Agent 模型模块级创建，重启生效），
    // 行级 Tooltip 明确标注，避免管理员误以为热切换；控件保留可编辑（后端允许）
    const editable: ReactNode =
      f.id === 'agent_chat' ? (
        <Tooltip title="该场景绑定不生效（Agent 模型模块级创建）">{select}</Tooltip>
      ) : (
        select
      )
    // status 非正常语义值（后端当前为 enabled/disabled）时提示已回退默认；后续语义未定前不做主列渲染
    const degraded =
      !!f.status && f.status !== 'ok' && f.status !== 'enabled' && f.status !== 'disabled'
    return degraded ? <Tooltip title="绑定与场景类型不匹配，已回退默认">{editable}</Tooltip> : editable
  }

  const columns: ColumnsType<AiFunctionItem> = [
    {
      title: '功能名称',
      dataIndex: 'label',
      width: 160,
      render: (v: string, f: AiFunctionItem) => (
        <span style={{ fontWeight: 600, color: UI.ink }}>
          {v || '—'}
          {f.deprecated === true && (
            <Tooltip title="已废弃场景，保留兼容可配置">
              <Tag
                style={{
                  marginLeft: 6,
                  borderRadius: 6,
                  fontSize: 10,
                  lineHeight: '16px',
                  padding: '0 4px',
                  background: UI.gray,
                  color: UI.steel,
                  borderColor: UI.hairline,
                }}
              >
                废弃
              </Tag>
            </Tooltip>
          )}
        </span>
      ),
    },
    {
      title: '场景值',
      dataIndex: 'id',
      width: 200,
      render: (v: string) => (
        <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>{v}</span>
      ),
    },
    {
      title: '启用',
      key: 'enabled',
      width: 80,
      render: (_, f) => {
        const readOnly = f.enabled === undefined
        const sw = (
          <Switch
            size="small"
            checked={!!f.enabled}
            loading={savingScenarios.has(f.id)}
            disabled={readOnly}
            data-testid={`ai-scenario-switch-${f.id}`}
            onChange={(v) => void handleToggleScenario(f, v)}
          />
        )
        return readOnly ? <Tooltip title="后端未返回场景配置">{sw}</Tooltip> : sw
      },
    },
    {
      title: '模型绑定',
      key: 'model_profile',
      width: 200,
      render: (_, f) => renderBindingCell(f),
    },
    {
      title: '生效来源',
      key: 'source',
      width: 100,
      render: (_, f) =>
        f.source ? (
          <SourceTag source={f.source as AiConfigSource} />
        ) : (
          <span style={{ fontSize: 12, color: UI.muted }}>—</span>
        ),
    },
    {
      title: '模型类型',
      dataIndex: 'model_type',
      width: 100,
      render: (v: string) => <ModelTypeTag type={v} />,
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 90,
      render: (v: string) => <ChannelTag channel={v} />,
    },
    {
      title: '描述',
      dataIndex: 'description',
      render: (v: string) => (
        <span style={{ fontSize: 13, color: UI.slate }}>{v || '—'}</span>
      ),
    },
  ]

  return (
    <div style={{ ...CARD_STYLE, padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 调用功能</div>
        <span style={{ fontSize: 12, color: UI.steel }}>
          共 {filteredFunctions.length} 项 · 已启用 {enabledCount} · 已停用 {disabledCount}
        </span>
      </div>

      <Space wrap style={{ margin: '12px 0' }}>
        <Input.Search
          placeholder="功能名称/场景值/描述"
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
        />
        <Segmented
          options={MODEL_TYPE_OPTIONS}
          value={modelType}
          onChange={(v) => setModelType(v as string)}
        />
        <Segmented
          options={ENABLED_STATUS_OPTIONS}
          value={enabledFilter}
          onChange={(v) => setEnabledFilter(v as 'all' | 'enabled' | 'disabled')}
        />
        <Select
          allowClear
          placeholder="渠道"
          style={{ width: 120 }}
          options={channelOptions}
          value={channel}
          onChange={(v) => setChannel(v || undefined)}
        />
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void load()}
          disabled={savingScenarios.size > 0}
          title="刷新"
        />
      </Space>

      {loading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <Table<AiFunctionItem>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filteredFunctions}
          scroll={{ x: 1160 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="当前无已注册场景"
              />
            ),
          }}
          pagination={
            filteredFunctions.length > 10
              ? { pageSize: 10, showSizeChanger: false }
              : false
          }
        />
      )}
    </div>
  )
}
