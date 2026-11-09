'use client'

// 劳保用品目录 Panel（OhLaborSupplyPanel）— labor_supply 直读域只读台账
// StatCard 统计行（检测报告/说明书/厂家/有效期四项覆盖率=治理信号）→
// 客户端过滤（protection_type/category/keyword）→ 详情 Drawer（全字段 +
// 附件代理下载）。数据量小（102 行）：page_size=200 全量拉取 + 客户端
// 过滤/分页；source 三态（bitable/degraded/not_enabled）降级提示。
// 数据缺口不在代码补数：厂家 76%/检测报告 84%/有效期 97% 未填（2026-11-09 基线）。

import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Drawer,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import {
  BookOutlined,
  DownloadOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { fetchLaborProducts, laborAttachmentUrl } from '@/lib/api/safety/labor-supply'
import type { LaborProduct } from '@/types/safety'
import { EmptyGuide, SectionCard, StatCard } from '@/components/ui-kit'
import { T, UI } from './ohConstants'

const MAX_FETCH = 200

const PROTECTION_COLORS: Record<string, string> = {
  呼吸防护: 'blue',
  足部防护: 'green',
  手部防护: 'orange',
  躯干防护: 'purple',
  高空坠落防护: 'cyan',
  面部防护: 'geekblue',
  眼部防护: 'gold',
  头部防护: 'magenta',
  听力防护: 'lime',
}

function pct(coverage: number): string {
  return `${Math.round(coverage * 100)}%`
}

export default function OhLaborSupplyPanel() {
  const [keyword, setKeyword] = useState('')
  const [protectionType, setProtectionType] = useState<string | undefined>()
  const [category, setCategory] = useState<string | undefined>()
  const [detail, setDetail] = useState<LaborProduct | null>(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['labor-supply-products'],
    queryFn: () => fetchLaborProducts({ page: 1, page_size: MAX_FETCH }),
  })

  const envelope = data
  const rows = useMemo(() => envelope?.items ?? [], [envelope])
  const stats = envelope?.stats

  const protectionOptions = useMemo(() => {
    const counts = stats?.protection_types ?? {}
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({ value, label: `${value}（${count}）` }))
  }, [stats])

  const categoryOptions = useMemo(() => {
    const seen = new Map<string, number>()
    rows.forEach((r) => {
      if (r.category) seen.set(r.category, (seen.get(r.category) ?? 0) + 1)
    })
    return Array.from(seen.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({ value, label: `${value}（${count}）` }))
  }, [rows])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return rows.filter((r) => {
      if (protectionType && r.protection_type !== protectionType) return false
      if (category && r.category !== category) return false
      if (!kw) return true
      return (
        r.name.toLowerCase().includes(kw) ||
        r.model.toLowerCase().includes(kw) ||
        r.vendor.toLowerCase().includes(kw)
      )
    })
  }, [rows, keyword, protectionType, category])

  const columns: ColumnsType<LaborProduct> = useMemo(
    () => [
      {
        title: '劳保用品名称',
        dataIndex: 'name',
        key: 'name',
        width: 170,
        render: (v: string) => <span style={{ fontWeight: 500, fontSize: 13 }}>{v}</span>,
      },
      {
        title: '型号',
        dataIndex: 'model',
        key: 'model',
        width: 210,
        ellipsis: true,
        render: (v: string) => (
          <span style={{ fontSize: 12, color: UI.muted }}>{v || '—'}</span>
        ),
      },
      {
        title: '防护类型',
        dataIndex: 'protection_type',
        key: 'protection_type',
        width: 130,
        render: (v: string) =>
          v ? (
            <Tag color={PROTECTION_COLORS[v] ?? 'default'} style={{ marginInlineEnd: 0 }}>
              {v}
            </Tag>
          ) : (
            <span style={{ color: UI.muted }}>—</span>
          ),
      },
      { title: '类别', dataIndex: 'category', key: 'category', width: 110 },
      {
        title: '厂家',
        dataIndex: 'vendor',
        key: 'vendor',
        width: 110,
        render: (v: string) => v || <span style={{ color: '#fa8c16', fontSize: 12 }}>未填</span>,
      },
      {
        title: '有效期',
        dataIndex: 'lifespan_years',
        key: 'lifespan_years',
        width: 80,
        render: (v: number | null) =>
          v != null ? `${v} 年` : <span style={{ color: '#fa8c16', fontSize: 12 }}>未填</span>,
      },
      { title: '单位', dataIndex: 'unit', key: 'unit', width: 60 },
      {
        title: '凭证',
        key: 'attachments',
        width: 110,
        render: (_: unknown, r: LaborProduct) => (
          <Space size={4}>
            <Tooltip title={r.report_attachments.length ? '检测报告' : '无检测报告'}>
              <FileTextOutlined
                style={{
                  color: r.report_attachments.length ? '#52c41a' : '#d9d9d9',
                  fontSize: 14,
                }}
              />
            </Tooltip>
            <Tooltip title={r.manual_attachments.length ? '说明书' : '无说明书'}>
              <BookOutlined
                style={{
                  color: r.manual_attachments.length ? '#52c41a' : '#d9d9d9',
                  fontSize: 14,
                }}
              />
            </Tooltip>
            {r.report_attachments.length + r.manual_attachments.length > 0 && (
              <Button
                size="small"
                type="text"
                style={{ padding: '0 4px', color: T.primary, fontSize: 12 }}
                onClick={() => setDetail(r)}
              >
                下载
              </Button>
            )}
          </Space>
        ),
      },
    ],
    [],
  )

  return (
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 统计行（四项覆盖率=治理信号，总项数在 SectionCard 描述行） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="检测报告覆盖"
          value={stats ? `${stats.report_filled}/${stats.total}` : '-'}
          sub={stats ? `覆盖率 ${pct(stats.report_coverage)}（待补录）` : ''}
        />
        <StatCard
          label="说明书覆盖"
          value={stats ? `${stats.manual_filled}/${stats.total}` : '-'}
          sub={stats ? `覆盖率 ${pct(stats.manual_coverage)}（待补录）` : ''}
        />
        <StatCard
          label="厂家覆盖"
          value={stats ? `${stats.vendor_filled}/${stats.total}` : '-'}
          sub={stats ? `覆盖率 ${pct(stats.vendor_coverage)}（待补录）` : ''}
        />
        <StatCard
          label="有效期覆盖"
          value={stats ? `${stats.lifespan_filled}/${stats.total}` : '-'}
          sub={stats ? `覆盖率 ${pct(stats.lifespan_coverage)}（待补录）` : ''}
        />
      </div>

      <SectionCard
        title="劳保用品目录"
        description={`飞书多维表格直读（共 ${envelope?.total ?? 0} 项），检测报告/说明书可下载`}
      >
        {envelope?.source === 'not_enabled' && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="劳保直读开关已关闭（SAFETY_LABOR_SUPPLY_DIRECT_ENABLED）"
            description="运维可在配置页重新开启；开启后此处自动恢复。"
          />
        )}
        {envelope?.source === 'degraded' && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="劳保用品表暂时不可达（直读降级）"
            description="稍后刷新重试；持续失败请检查 Bitable 连接与机器人权限。"
          />
        )}
        <div
          style={{
            display: 'flex',
            gap: 10,
            marginBottom: 16,
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <Input
            allowClear
            placeholder="名称/型号/厂家"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 220 }}
            prefix={<SearchOutlined style={{ color: UI.muted }} />}
          />
          <Select
            allowClear
            placeholder="防护类型"
            value={protectionType}
            onChange={setProtectionType}
            options={protectionOptions}
            style={{ width: 170 }}
          />
          <Select
            allowClear
            placeholder="类别"
            value={category}
            onChange={setCategory}
            options={categoryOptions}
            style={{ width: 170 }}
          />
          <Tooltip title="刷新">
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} size="small" />
          </Tooltip>
        </div>

        <Table<LaborProduct>
          columns={columns}
          dataSource={filtered}
          rowKey="record_id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 980 }}
          onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
          locale={{
            emptyText: (
              <EmptyGuide
                compact
                title="暂无劳保用品目录"
                description="目录由劳保用品汇总表直读，稍后刷新查看"
              />
            ),
          }}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 项`,
          }}
        />
      </SectionCard>

      {/* ── 详情 Drawer（全字段 + 附件下载） ── */}
      <Drawer
        title={detail?.name ?? ''}
        placement="right"
        width={440}
        open={detail != null}
        onClose={() => setDetail(null)}
      >
        {detail && <LaborProductDetail product={detail} />}
      </Drawer>
    </div>
  )
}

function LaborProductDetail({ product }: { product: LaborProduct }) {
  const fields: Array<[string, React.ReactNode]> = [
    ['型号', product.model || '—'],
    ['防护类型', product.protection_type || '—'],
    ['类别', product.category || '—'],
    ['厂家', product.vendor || <span style={{ color: '#fa8c16' }}>未填</span>],
    [
      '有效期',
      product.lifespan_years != null ? `${product.lifespan_years} 年` : <span style={{ color: '#fa8c16' }}>未填</span>,
    ],
    ['单位', product.unit || '—'],
  ]
  return (
    <div className="flex flex-col gap-4">
      {fields.map(([k, v]) => (
        <div key={k} style={{ display: 'flex', gap: 12, fontSize: 13 }}>
          <span style={{ width: 72, color: UI.muted, flexShrink: 0 }}>{k}</span>
          <span>{v}</span>
        </div>
      ))}
      <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12, marginTop: 4 }}>
        <div style={{ fontSize: 13, color: UI.muted, marginBottom: 8 }}>检测报告</div>
        {product.report_attachments.length ? (
          product.report_attachments.map((a) => (
            <AttachmentLink
              key={a.file_token}
              recordId={product.record_id}
              fieldName="检测报告"
              fileToken={a.file_token}
              name={a.name}
            />
          ))
        ) : (
          <span style={{ fontSize: 13, color: '#fa8c16' }}>未上传（待补录）</span>
        )}
        <div style={{ fontSize: 13, color: UI.muted, margin: '12px 0 8px' }}>说明书/产品介绍</div>
        {product.manual_attachments.length ? (
          product.manual_attachments.map((a) => (
            <AttachmentLink
              key={a.file_token}
              recordId={product.record_id}
              fieldName="说明书/产品介绍"
              fileToken={a.file_token}
              name={a.name}
            />
          ))
        ) : (
          <span style={{ fontSize: 13, color: '#fa8c16' }}>未上传（待补录）</span>
        )}
      </div>
    </div>
  )
}

function AttachmentLink({
  recordId,
  fieldName,
  fileToken,
  name,
}: {
  recordId: string
  fieldName: '检测报告' | '说明书/产品介绍'
  fileToken: string
  name: string
}) {
  return (
    <Button
      size="small"
      type="link"
      icon={<DownloadOutlined />}
      style={{ padding: 0, height: 'auto' }}
      onClick={() => window.open(laborAttachmentUrl(recordId, fieldName, fileToken), '_blank')}
    >
      {name || fileToken}
    </Button>
  )
}
