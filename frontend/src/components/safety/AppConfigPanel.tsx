'use client'

// 应用配置中心 — env→DB 迁移的统一管理页
// 生效优先级：进程 env（非空）> DB 活行（enabled 且 value 非空）> registry 代码默认
// 视觉严格对齐 dazah-frontend/DESIGN.md（Notion 设计系统 tokens）

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import { EditOutlined, FileTextOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { fetchAppConfig, fetchAppConfigAudits, updateAppConfig } from '@/actions/safety'
import type { AppConfigAuditItem, AppConfigItem } from '@/types/safety'
import { CARD_STYLE, MONO_FONT, UI } from './schedulerConfigConstants'

const SOURCE_UI: Record<string, { label: string; color: string; bg: string }> = {
  env: { label: 'env', color: '#072', bg: 'rgba(47,164,68,0.12)' },
  db: { label: 'DB', color: '#005bab', bg: UI.sky },
  default: { label: '默认', color: UI.steel, bg: UI.gray },
}

function SourceTag({ source }: { source: string }) {
  const ui = SOURCE_UI[source] ?? SOURCE_UI.default
  return (
    <span
      style={{
        background: ui.bg,
        color: ui.color,
        fontSize: 11,
        fontWeight: 600,
        lineHeight: '18px',
        padding: '0 6px',
        borderRadius: 4,
        whiteSpace: 'nowrap',
      }}
    >
      {ui.label}
    </span>
  )
}

function ValueCell({ item }: { item: AppConfigItem }) {
  const text = item.value === '' ? '（空）' : item.value
  const isBool = item.type === 'bool'
  const on = item.value === 'true'
  return (
    <Space size={6}>
      <span
        style={{
          fontFamily: MONO_FONT,
          fontSize: 12.5,
          color: item.secret ? UI.muted : isBool ? (on ? '#072' : UI.slate) : UI.ink,
        }}
      >
        {isBool ? (on ? 'true ✓' : 'false ✕') : text}
      </span>
      {item.env_overrides_db && (
        <Tooltip title="env 与 DB 同设且值不同：env 优先生效，DB 改动不生效。请清除 .env 中该键后重启。">
          <Tag color="warning" style={{ marginInlineEnd: 0 }}>
            env 遮蔽
          </Tag>
        </Tooltip>
      )}
    </Space>
  )
}

export default function AppConfigPanel() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [items, setItems] = useState<AppConfigItem[]>([])
  const [category, setCategory] = useState<string>('all')
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<AppConfigItem | null>(null)
  const [editValue, setEditValue] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [audits, setAudits] = useState<AppConfigAuditItem[]>([])
  const [auditsLoading, setAuditsLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchAppConfig()
      if (res.code >= 200 && res.code < 300) {
        setItems(res.data?.items ?? [])
      } else {
        message.error(res.message || '加载应用配置失败')
      }
    } catch (e) {
      message.error(`加载应用配置失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
  }, [load])

  const categories = useMemo(() => {
    const seen = new Map<string, string>()
    for (const item of items) seen.set(item.category, item.category_label)
    return [
      { value: 'all', label: '全部类别' },
      ...[...seen.entries()].map(([value, label]) => ({
        value,
        label: `${label}（${items.filter((i) => i.category === value).length}）`,
      })),
    ]
  }, [items])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return items.filter((item) => {
      if (category !== 'all' && item.category !== category) return false
      if (!kw) return true
      return (
        item.key.toLowerCase().includes(kw) ||
        item.description.toLowerCase().includes(kw) ||
        item.value.toLowerCase().includes(kw)
      )
    })
  }, [items, category, keyword])

  const conflictCount = useMemo(
    () => items.filter((i) => i.env_overrides_db).length,
    [items],
  )

  const openEdit = (item: AppConfigItem) => {
    setEditing(item)
    // secret 键不回显明文（后端本就脱敏，编辑从空开始=不改语义不存在，值必填）
    setEditValue(item.secret ? '' : item.value)
  }

  const save = async () => {
    if (!editing) return
    if (editing.secret && !editValue.trim() && editing.value !== '') {
      // secret 键留空提交视为清空覆盖——明确确认
      Modal.confirm({
        title: '清空敏感配置覆盖？',
        content: '值留空提交 = 清除 DB 覆盖，回落 env/代码默认。确认继续？',
        onOk: () => void doSave(),
      })
      return
    }
    await doSave()
  }

  const doSave = async () => {
    if (!editing) return
    setSaving(true)
    try {
      await updateAppConfig(editing.key, { value: editValue })
      message.success(`${editing.key} 已更新`)
      setEditing(null)
      await load()
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const openAudits = async () => {
    setAuditOpen(true)
    setAuditsLoading(true)
    try {
      const res = await fetchAppConfigAudits(undefined, 100)
      if (res.code >= 200 && res.code < 300) {
        setAudits(res.data ?? [])
      } else {
        message.error(res.message || '加载审计失败')
      }
    } catch (e) {
      message.error(`加载审计失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setAuditsLoading(false)
    }
  }

  const columns: ColumnsType<AppConfigItem> = [
    {
      title: '配置键',
      dataIndex: 'key',
      width: 340,
      render: (key: string, item) => (
        <Space size={6}>
          <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>{key}</span>
          {item.restart_required && (
            <Tooltip title="启动语义键：改动需重启后端生效（循环启动/模块导入时读取）">
              <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                需重启
              </Tag>
            </Tooltip>
          )}
          {item.secret && (
            <Tooltip title="敏感配置：展示与审计均脱敏">
              <Tag style={{ marginInlineEnd: 0 }}>敏感</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '类别',
      dataIndex: 'category_label',
      width: 100,
      render: (label: string) => (
        <span style={{ fontSize: 12.5, color: UI.steel }}>{label}</span>
      ),
    },
    {
      title: '当前生效值',
      dataIndex: 'value',
      width: 220,
      render: (_, item) => <ValueCell item={item} />,
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 72,
      render: (source: string) => <SourceTag source={source} />,
    },
    {
      title: '默认值',
      dataIndex: 'default',
      width: 150,
      ellipsis: true,
      render: (def: string) => (
        <Tooltip title={def}>
          <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.muted }}>
            {def === '' ? '—' : def}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
      render: (desc: string) => (
        <Tooltip title={desc}>
          <span style={{ fontSize: 12.5, color: UI.steel }}>{desc}</span>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'op',
      width: 64,
      render: (_, item) => (
        <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(item)}>
          编辑
        </Button>
      ),
    },
  ]

  const auditColumns: ColumnsType<AppConfigAuditItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => (
        <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>{v?.replace('T', ' ').slice(0, 19)}</span>
      ),
    },
    {
      title: '配置键',
      dataIndex: 'key',
      width: 300,
      render: (v: string) => <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>{v}</span>,
    },
    { title: '动作', dataIndex: 'action', width: 80 },
    {
      title: '变更',
      key: 'diff',
      ellipsis: true,
      render: (_, row) => {
        const before = row.before_json?.value
        const after = row.after_json?.value
        return (
          <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>
            {before == null ? '—' : String(before)} → {after == null ? '—' : String(after)}
          </span>
        )
      },
    },
    { title: '操作人', dataIndex: 'operator_name', width: 90 },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          ...CARD_STYLE,
          padding: 20,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 650, color: UI.ink }}>应用配置中心</div>
          <div style={{ fontSize: 12.5, color: UI.steel, marginTop: 4 }}>
            生效优先级：env（应急通道）&gt; DB（本页修改，30 秒内生效）&gt; 代码默认；飞书凭证与 AI
            Key 仍在 .env
          </div>
        </div>
        <Space>
          <Button icon={<FileTextOutlined />} onClick={() => void openAudits()}>
            变更审计
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {conflictCount > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${conflictCount} 个配置键同时存在 env 与 DB 值且不一致：env 优先生效，本页修改暂不生效`}
          description="这是 env→DB 迁移期的残留状态：请清除 .env 文件中对应键并重启后端，DB 值即接管生效。列表中以「env 遮蔽」标记。"
        />
      )}

      <div style={{ ...CARD_STYLE, padding: 16 }}>
        <Space style={{ marginBottom: 12 }}>
          <Select
            value={category}
            onChange={setCategory}
            options={categories}
            style={{ width: 180 }}
          />
          <Input.Search
            placeholder="搜索配置键 / 说明 / 值"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            allowClear
            style={{ width: 280 }}
          />
        </Space>

        {loading ? (
          <Skeleton active paragraph={{ rows: 10 }} />
        ) : filtered.length === 0 ? (
          <Empty description="无匹配配置" style={{ padding: 32 }} />
        ) : (
          <Table
            rowKey="key"
            size="middle"
            columns={columns}
            dataSource={filtered}
            pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 项` }}
          />
        )}
      </div>

      <Modal
        open={editing !== null}
        title={editing ? `编辑：${editing.key}` : ''}
        onCancel={() => setEditing(null)}
        onOk={() => void save()}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        destroyOnClose
      >
        {editing && (
          <Space direction="vertical" size={12} style={{ width: '100%', paddingTop: 8 }}>
            <div style={{ fontSize: 12.5, color: UI.steel }}>{editing.description}</div>
            {editing.restart_required && (
              <Alert
                type="warning"
                showIcon
                message="启动语义键：保存后需重启后端才生效"
              />
            )}
            {editing.type === 'bool' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Switch
                  checked={editValue === 'true'}
                  onChange={(v) => setEditValue(v ? 'true' : 'false')}
                />
                <span style={{ fontFamily: MONO_FONT, fontSize: 13 }}>{editValue}</span>
              </div>
            ) : editing.type === 'int' ? (
              <InputNumber
                value={editValue === '' ? null : Number(editValue)}
                onChange={(v) => setEditValue(v == null ? '' : String(v))}
                style={{ width: '100%' }}
                precision={0}
              />
            ) : (
              <Input.TextArea
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                rows={2}
                placeholder={
                  editing.secret
                    ? '敏感值不回显，输入新值覆盖；留空提交 = 清除覆盖回落 env/默认'
                    : editing.allow_off
                      ? 'oc_/ou_ 开头；置 off 停用'
                      : '字符串值；留空 = 清除覆盖回落 env/默认'
                }
              />
            )}
            <div style={{ fontSize: 12, color: UI.muted }}>
              当前生效：{editing.value === '' ? '（空）' : editing.value}（来源{' '}
              {SOURCE_UI[editing.source]?.label ?? editing.source}；默认{' '}
              {editing.default === '' ? '—' : editing.default}）
            </div>
          </Space>
        )}
      </Modal>

      <Drawer
        title="配置变更审计"
        open={auditOpen}
        onClose={() => setAuditOpen(false)}
        width={760}
      >
        {auditsLoading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : audits.length === 0 ? (
          <Empty description="暂无审计记录" />
        ) : (
          <Table
            rowKey={(row) => `${row.key}-${row.created_at}-${row.action}`}
            size="small"
            columns={auditColumns}
            dataSource={audits}
            pagination={{ pageSize: 15 }}
          />
        )}
      </Drawer>
    </div>
  )
}
