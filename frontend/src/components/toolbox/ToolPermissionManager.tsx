'use client'

// 使用权限管理：按工具配置「使用人员」与「配置人员」名单。
// 空名单语义：使用名单留空 = 所有登录用户可用；配置名单留空 = 仅超级管理员可修改配置。
// 配置名单成员自动获得使用权限（配置包含使用）。

import { useState } from 'react'
import { App, Button, Select, Tag } from 'antd'
import { KeyOutlined, SaveOutlined, UserOutlined } from '@ant-design/icons'

import { updateToolGrants } from '@/actions/toolbox'
import type { PersonnelOption, ToolGrantInfo, ToolInfo } from '@/types/toolbox'

interface Props {
  tools: ToolInfo[]
  initialGrants: ToolGrantInfo[]
  personnel: PersonnelOption[]
}

interface ToolDraft {
  useIds: string[]
  configIds: string[]
  dirty: boolean
  saving: boolean
}

function buildDrafts(tools: ToolInfo[], grants: ToolGrantInfo[]): Record<string, ToolDraft> {
  const drafts: Record<string, ToolDraft> = {}
  for (const tool of tools) {
    const grant = grants.find((g) => g.tool_id === tool.id)
    drafts[tool.id] = {
      useIds: (grant?.use_users ?? []).map((u) => u.user_id),
      configIds: (grant?.config_users ?? []).map((u) => u.user_id),
      dirty: false,
      saving: false,
    }
  }
  return drafts
}

function sameIdSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  return a.every((id) => b.includes(id))
}

// grants 中存在但已不在注册表的工具（改名/下线遗留的授权行）：照常渲染，可清空保存
function buildOrphanTools(tools: ToolInfo[], grants: ToolGrantInfo[]): ToolInfo[] {
  const known = new Set(tools.map((t) => t.id))
  return grants
    .filter((g) => !known.has(g.tool_id))
    .map((g) => ({
      id: g.tool_id,
      name: g.tool_name,
      description: '该工具已不在工具箱注册表中，清空名单并保存可解除残留授权',
      steps: [],
      config_schema: [],
      can_use: false,
      can_config: false,
    }))
}

export function ToolPermissionManager({ tools, initialGrants, personnel }: Props) {
  const { message } = App.useApp()
  const allTools = [...tools, ...buildOrphanTools(tools, initialGrants)]
  const [drafts, setDrafts] = useState<Record<string, ToolDraft>>(() =>
    buildDrafts(allTools, initialGrants),
  )

  const userOptions = personnel.map((p) => ({
    value: p.id,
    label: `${p.name}${p.employee_no ? ` · ${p.employee_no}` : ''}${p.department ? ` · ${p.department}` : ''}`,
  }))

  const setDraft = (toolId: string, patch: Partial<ToolDraft> & { dirty: true }) => {
    setDrafts((prev) => ({ ...prev, [toolId]: { ...prev[toolId], ...patch } }))
  }

  const handleSave = async (toolId: string) => {
    const draft = drafts[toolId]
    if (!draft || draft.saving) return
    const savedUseIds = [...draft.useIds]
    const savedConfigIds = [...draft.configIds]
    setDraft(toolId, { saving: true, dirty: true })
    try {
      await updateToolGrants(toolId, savedUseIds, savedConfigIds)
      message.success('使用权限保存成功')
      setDrafts((prev) => {
        const cur = prev[toolId]
        // 保存期间仍有新编辑时保持 dirty，避免未保存的选择被误标为已保存
        const changed =
          !sameIdSet(cur.useIds, savedUseIds) || !sameIdSet(cur.configIds, savedConfigIds)
        return { ...prev, [toolId]: { ...cur, saving: false, dirty: changed } }
      })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
      setDrafts((prev) => ({
        ...prev,
        [toolId]: { ...prev[toolId], saving: false },
      }))
    }
  }

  return (
    <div className="h-full flex flex-col gap-4 sm:gap-6 p-4 sm:p-6 overflow-hidden">
      {/* ═══ Header Card ═══ */}
      <div
        className="rounded-[16px] border p-5 sm:p-6"
        style={{
          backgroundColor: 'var(--color-canvas)',
          borderColor: 'var(--color-hairline)',
          borderTop: '3px solid var(--color-primary)',
        }}
      >
        <div className="flex items-center gap-3.5">
          <div
            className="w-10 h-10 rounded-[10px] flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            <KeyOutlined style={{ fontSize: 20, color: '#fff' }} />
          </div>
          <div>
            <h1 className="text-[20px] sm:text-[22px] font-semibold text-[var(--color-ink)] tracking-tight leading-tight">
              使用权限
            </h1>
            <p className="text-[13px] text-[var(--color-steel)] mt-0.5">
              配置每个工具的可用人员与可修改配置人员
            </p>
          </div>
        </div>
      </div>

      {/* ═══ Tool Cards ═══ */}
      <div className="flex-1 overflow-auto min-h-0 flex flex-col gap-4">
        {allTools.map((tool) => {
          const draft = drafts[tool.id]
          if (!draft) return null
          const hasConfig = tool.config_schema.length > 0
          return (
            <div
              key={tool.id}
              className="rounded-[16px] border p-5"
              style={{
                backgroundColor: 'var(--color-canvas)',
                borderColor: 'var(--color-hairline)',
              }}
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-[15px] font-semibold text-[var(--color-charcoal)]">
                      {tool.name}
                    </h3>
                    <code className="text-[11px] text-[var(--color-stone)]">{tool.id}</code>
                    {hasConfig && (
                      <Tag style={{ borderRadius: 6, fontSize: 11, margin: 0 }}>可配置</Tag>
                    )}
                  </div>
                  <p className="mt-1 text-[13px] text-[var(--color-slate)]">{tool.description}</p>
                </div>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  disabled={!draft.dirty}
                  loading={draft.saving}
                  onClick={() => handleSave(tool.id)}
                >
                  保存
                </Button>
              </div>

              <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* 使用人员 */}
                <div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <UserOutlined style={{ fontSize: 13, color: 'var(--color-steel)' }} />
                    <span className="text-[13px] font-medium text-[var(--color-charcoal)]">
                      使用人员
                    </span>
                  </div>
                  <Select
                    mode="multiple"
                    showSearch
                    optionFilterProp="label"
                    placeholder="选择可使用该工具的用户"
                    style={{ width: '100%' }}
                    value={draft.useIds}
                    options={userOptions}
                    onChange={(ids: string[]) => setDraft(tool.id, { useIds: ids, dirty: true })}
                  />
                  <p className="mt-1 text-[12px] text-[var(--color-stone)]">
                    留空 = 所有登录用户可用；配置人员自动获得使用权限
                  </p>
                </div>

                {/* 配置人员（仅可配置工具） */}
                {hasConfig && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <KeyOutlined style={{ fontSize: 13, color: 'var(--color-steel)' }} />
                      <span className="text-[13px] font-medium text-[var(--color-charcoal)]">
                        配置人员
                      </span>
                    </div>
                    <Select
                      mode="multiple"
                      showSearch
                      optionFilterProp="label"
                      placeholder="选择可修改该工具配置的用户"
                      style={{ width: '100%' }}
                      value={draft.configIds}
                      options={userOptions}
                      onChange={(ids: string[]) =>
                        setDraft(tool.id, { configIds: ids, dirty: true })
                      }
                    />
                    <p className="mt-1 text-[12px] text-[var(--color-stone)]">
                      留空 = 仅超级管理员可修改配置
                    </p>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
