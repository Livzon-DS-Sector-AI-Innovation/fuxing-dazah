'use client'

// 右·卡一：连接配置（design.md §2.3）
// 以「注册表 kind 行」为行单位渲染（后端 GET /connections/{domain} 已含 missing/disabled 视图行）：
// 表类型（label + mono kind key）| app_token | table_id | 状态 | 备注 | 操作 [配置|编辑|测试]
// 停用行整行降透明（opacity 0.55）；kind 级状态 Tag 复用 schedulerConfigConstants.StatusTag

import { useMemo } from 'react'
import { Button, Empty, Skeleton, Space, Table, Tag, Tooltip } from 'antd'
import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import type { BitableConnection, BitableDomainOverview } from '@/types/safety'
import { CARD_STYLE, MONO_FONT, UI } from './bitableConfigConstants'
import { StatusTag } from './schedulerConfigConstants'

interface BitableConnectionCardProps {
  domain: BitableDomainOverview | null
  connections: BitableConnection[]
  loading: boolean
  onEdit: (record: BitableConnection) => void
  /** kind 缺省 = 页头「+新增」（抽屉内下拉选未配置 kind） */
  onAdd: (kind?: string) => void
  onTest: (record: BitableConnection) => void
}

const monoCellStyle: React.CSSProperties = {
  fontFamily: MONO_FONT,
  fontSize: 13,
  color: UI.ink,
  whiteSpace: 'nowrap',
}

function KindCell({ row, domain }: { row: BitableConnection; domain: BitableDomainOverview | null }) {
  const label = domain?.kinds.find((k) => k.kind === row.kind)?.label ?? row.kind
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: UI.ink }}>{label}</span>
      <span style={{ fontSize: 12, color: UI.steel, fontFamily: MONO_FONT }}>{row.kind}</span>
    </div>
  )
}

function TokenCell({ value }: { value: string }) {
  if (!value) {
    return <span style={{ fontSize: 13, color: UI.muted }}>未配置</span>
  }
  return (
    <Tooltip title={value}>
      <span style={monoCellStyle}>{value}</span>
    </Tooltip>
  )
}

function StatusCell({ row }: { row: BitableConnection }) {
  // 无 DB 行且无默认值 → 「未配置」；否则按启用态渲染（启用绿 / 停用灰）
  if (!row.app_token && !row.table_id) {
    return (
      <Tag style={{ borderRadius: 6, fontWeight: 600, color: UI.muted, borderColor: UI.hairline }}>
        未配置
      </Tag>
    )
  }
  return <StatusTag enabled={row.enabled} />
}

export default function BitableConnectionCard({
  domain,
  connections,
  loading,
  onEdit,
  onAdd,
  onTest,
}: BitableConnectionCardProps) {
  const columns: ColumnsType<BitableConnection> = useMemo(
    () => [
      {
        title: '表类型',
        key: 'kind',
        width: 190,
        render: (_, r) => <KindCell row={r} domain={domain} />,
      },
      {
        title: 'app_token',
        dataIndex: 'app_token',
        key: 'app_token',
        width: 170,
        render: (v: string) => <TokenCell value={v} />,
      },
      {
        title: 'table_id',
        dataIndex: 'table_id',
        key: 'table_id',
        width: 160,
        render: (v: string) => <TokenCell value={v} />,
      },
      {
        title: '状态',
        key: 'status',
        width: 90,
        render: (_, r) => <StatusCell row={r} />,
      },
      {
        title: '备注',
        dataIndex: 'note',
        key: 'note',
        width: 180,
        render: (v: string | null | undefined) =>
          v ? (
            <Tooltip title={v}>
              <span
                style={{
                  fontSize: 13,
                  color: UI.slate,
                  display: 'block',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: 180,
                }}
              >
                {v}
              </span>
            </Tooltip>
          ) : (
            <span style={{ fontSize: 13, color: UI.muted }}>—</span>
          ),
      },
      {
        title: '操作',
        key: 'action',
        width: 190,
        render: (_, r) => {
          const isMissing = !r.app_token && !r.table_id
          if (isMissing) {
            return (
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => onAdd(r.kind)}>
                配置
              </Button>
            )
          }
          return (
            <Space size={6}>
              <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(r)}>
                编辑
              </Button>
              <Button size="small" onClick={() => onTest(r)}>
                测试连接
              </Button>
            </Space>
          )
        },
      },
    ],
    [domain, onAdd, onEdit, onTest],
  )

  const disabledCount = connections.filter((c) => !c.enabled).length

  return (
    <div style={{ ...CARD_STYLE, padding: 16, marginBottom: 16 }}>
      {/* 卡头 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <div>
          <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>连接配置</span>
          <span style={{ fontSize: 12, color: UI.steel, marginLeft: 8 }}>
            {(domain?.kinds.length ?? 0) > 0
              ? `注册表 ${domain?.kinds.length} 个表类型${disabledCount > 0 ? ` · ${disabledCount} 个停用` : ''}`
              : ''}
          </span>
        </div>
        <Button size="small" icon={<PlusOutlined />} onClick={() => onAdd()}>
          新增
        </Button>
      </div>

      {/* 表格 */}
      {loading && connections.length === 0 ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : connections.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该域暂无可配置表类型" />
      ) : (
        <Table<BitableConnection>
          rowKey="kind"
          size="middle"
          loading={loading}
          columns={columns}
          dataSource={connections}
          pagination={false}
          scroll={{ x: 960 }}
          onRow={(r) => ({
            style: { opacity: r.enabled ? 1 : 0.55 },
          })}
        />
      )}

      {/* 域级说明（后端 note，如中央报警 15 表白名单） */}
      {domain?.note && (
        <div style={{ fontSize: 12, color: UI.muted, marginTop: 10 }}>{domain.note}</div>
      )}
    </div>
  )
}
