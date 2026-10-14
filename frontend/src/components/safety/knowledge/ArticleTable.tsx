'use client'

import { Badge, Dropdown, Empty, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EllipsisOutlined } from '@ant-design/icons'
import type { RagplusDocMapEntry, SafetyKnowledgeArticle } from '@/types/safety'
import { StatusTag } from '@/components/ui-kit'
import { getCategoryStyle } from '@/components/safety/knowledgeConstants'

interface Props {
  articles: SafetyKnowledgeArticle[]
  loading: boolean
  docMap: Record<string, RagplusDocMapEntry>
  selectedRowKeys: string[]
  onSelectRowKeys: (keys: string[]) => void
  onOpenDetail: (article: SafetyKnowledgeArticle) => void
  onEdit: (article: SafetyKnowledgeArticle) => void
  onGenerateCard: (id: string) => void
  onGeneratePpt: (id: string) => void
  onGenerateSummary: (id: string) => void
}

/** ragplus 引擎入库状态（参考 ragplus 文档表的状态列 + 失败原因提示） */
function EngineStatusCell({ entry }: { entry: RagplusDocMapEntry | undefined }) {
  if (!entry) {
    return (
      <Tooltip title="尚无 ragplus 入库映射（无附件或未跑入库脚本）">
        <Badge status="default" text="未入库" />
      </Tooltip>
    )
  }
  if (entry.status === 'active') {
    return (
      <Tooltip title={entry.synced_at ? `同步于 ${new Date(entry.synced_at).toLocaleString()} · v${entry.version}` : `v${entry.version}`}>
        <Badge status="success" text="已入引擎" />
      </Tooltip>
    )
  }
  if (entry.status === 'failed') {
    return (
      <Tooltip title={entry.last_error || '上传/解析失败，重跑入库脚本可补齐'}>
        <Badge status="error" text="入库失败" />
      </Tooltip>
    )
  }
  if (entry.status === 'archived') {
    return (
      <Tooltip title={`已移入「${entry.dataset_name}」归档库（检索隔离）`}>
        <Badge status="warning" text="已归档" />
      </Tooltip>
    )
  }
  return <Badge status="default" text="已删除" />
}

const STATUS_TEXT: Record<string, { label: string; tone: 'ok' | 'default' | 'warn' }> = {
  published: { label: '已发布', tone: 'ok' },
  draft: { label: '草稿', tone: 'default' },
  archived: { label: '已归档', tone: 'warn' },
}

const CATEGORY_LABEL: Record<string, string> = {
  laws_regulations: '法规',
  standards: '标准',
  management_systems: '制度',
  training_materials: '培训',
  emergency_plans: '预案',
  accident_cases: '案例',
  sds: 'MSDS',
  equipment_manuals: '设备手册',
  risk_assessment_standards: '风险评估',
  other: '其他',
}

/**
 * 文档表格（参考 ragplus 知识库文档列表：状态徽标 + 引擎入库列 + 操作菜单）。
 * 客户端分页/筛选由父层控制（与旧卡片网格同口径）。
 */
export default function ArticleTable({
  articles,
  loading,
  docMap,
  selectedRowKeys,
  onSelectRowKeys,
  onOpenDetail,
  onEdit,
  onGenerateCard,
  onGeneratePpt,
  onGenerateSummary,
}: Props) {
  const columns: ColumnsType<SafetyKnowledgeArticle> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (_, record) => (
        <div style={{ minWidth: 0 }}>
          <button
            type="button"
            onClick={() => onOpenDetail(record)}
            style={{
              border: 'none', background: 'none', padding: 0, cursor: 'pointer',
              fontSize: 14, fontWeight: 500, color: 'var(--color-charcoal, #2b2a27)',
              textAlign: 'left', display: 'block', maxWidth: '100%',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
            title={record.title}
          >
            {record.title}
          </button>
          {record.article_no && (
            <span style={{ fontSize: 12, color: 'var(--color-stone, #a4a097)' }}>{record.article_no}</span>
          )}
        </div>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 110,
      render: (category: string) => {
        const style = getCategoryStyle('', category)
        return (
          <span
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5, borderRadius: 999,
              padding: '2px 10px', fontSize: 12, fontWeight: 500,
              background: style.bg, color: style.color,
            }}
          >
            {style.emoji} {CATEGORY_LABEL[category] || category}
          </span>
        )
      },
    },
    {
      title: '台账状态',
      dataIndex: 'status',
      key: 'status',
      width: 96,
      render: (status: string) => {
        const s = STATUS_TEXT[status] || { label: status, tone: 'default' as const }
        return <StatusTag tone={s.tone} label={s.label} />
      },
    },
    {
      title: '引擎入库',
      key: 'ragplus',
      width: 110,
      render: (_, record) => <EngineStatusCell entry={record.feishu_record_id ? docMap[record.feishu_record_id] : undefined} />,
    },
    {
      title: '知识卡片',
      key: 'card',
      width: 90,
      render: (_, record) =>
        record.knowledge_card ? <Badge status="processing" text="已生成" /> : <span style={{ fontSize: 12, color: 'var(--color-stone, #a4a097)' }}>—</span>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 120,
      render: (v: string) => (
        <span style={{ fontSize: 12, color: 'var(--color-steel, #787671)' }}>
          {v ? new Date(v).toLocaleDateString() : '—'}
        </span>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 56,
      render: (_, record) => (
        <Dropdown
          menu={{
            items: [
              { key: 'detail', label: '查看详情', onClick: () => onOpenDetail(record) },
              { key: 'edit', label: '编辑', onClick: () => onEdit(record) },
              { key: 'card', label: '生成知识卡片', onClick: () => onGenerateCard(record.id) },
              { key: 'ppt', label: '生成培训 PPT', onClick: () => onGeneratePpt(record.id) },
              { key: 'summary', label: '生成摘要', onClick: () => onGenerateSummary(record.id) },
            ],
          }}
          trigger={['click']}
        >
          <button
            type="button"
            style={{ border: 'none', background: 'none', cursor: 'pointer', padding: '2px 6px', color: 'var(--color-steel, #787671)' }}
          >
            <EllipsisOutlined />
          </button>
        </Dropdown>
      ),
    },
  ]

  return (
    <Table<SafetyKnowledgeArticle>
      rowKey="id"
      columns={columns}
      dataSource={articles}
      loading={loading}
      size="middle"
      locale={{
        emptyText: (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无文档"
            style={{ padding: '48px 0' }}
          >
            <span style={{ fontSize: 12, color: 'var(--color-stone, #a4a097)' }}>
              请调整筛选条件，或通过「同步」从 Bitable 拉取文档数据
            </span>
          </Empty>
        ),
      }}
      pagination={false}
      rowSelection={{
        selectedRowKeys,
        onChange: (keys) => onSelectRowKeys(keys.map(String)),
      }}
    />
  )
}
