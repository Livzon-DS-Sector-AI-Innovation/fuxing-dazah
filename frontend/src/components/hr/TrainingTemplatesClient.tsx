'use client'

// 培训导出模板管理页：11 个 docx 模板的查看/换版/回滚/恢复默认。
// 后端 hr:training:template 权限把守（菜单同权限显隐）；上传缺必填 {标记} 会被后端拒绝并提示清单。
// 每次后端操作成功后重拉清单（无本地乐观更新，量小）。

import { useEffect, useState } from 'react'
import { App, Alert, Button, Card, Drawer, Empty, Popconfirm, Space, Spin, Table, Tag, Tooltip, Upload } from 'antd'
import { DownloadOutlined, HistoryOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import PageHeader from './PageHeader'
import { downloadBase64File } from '@/lib/hr'
import {
  activateTrainingExportTemplateVersion,
  downloadTrainingExportTemplate,
  listTrainingExportTemplateVersions,
  listTrainingExportTemplates,
  restoreTrainingExportTemplateDefault,
  uploadTrainingExportTemplate,
} from '@/actions/hr/training'
import type { TrainingTemplateDef, TrainingTemplateMarker, TrainingTemplateVersion } from '@/types/hr/trainingTemplates'

function formatSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${size} B`
}

function formatTime(value: string | null): string {
  // created_at 是 UTC ISO 串（+00:00 后缀），必须转本地时间再展示，不能直接 slice
  if (!value) return '—'
  return dayjs(value).format('YYYY-MM-DD HH:mm')
}

export default function TrainingTemplatesClient() {
  const { message } = App.useApp()
  const [templates, setTemplates] = useState<TrainingTemplateDef[]>([])
  const [loading, setLoading] = useState(true)
  const [uploadingKey, setUploadingKey] = useState<string | null>(null)
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())
  // 版本历史抽屉
  const [historyFor, setHistoryFor] = useState<TrainingTemplateDef | null>(null)
  const [versions, setVersions] = useState<TrainingTemplateVersion[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await listTrainingExportTemplates()
        if (!cancelled) setTemplates(r.data || [])
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '获取模板清单失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refresh = async () => {
    try {
      const r = await listTrainingExportTemplates()
      setTemplates(r.data || [])
    } catch (e) {
      message.error(e instanceof Error ? e.message : '刷新模板清单失败')
    }
  }

  const handleDownload = async (t: TrainingTemplateDef, opts: { versionId?: string; isDefault?: boolean } = {}) => {
    try {
      const r = await downloadTrainingExportTemplate(t.key, {
        ...opts,
        fallbackName: opts.isDefault ? t.default_file : `${t.name}.docx`,
      })
      downloadBase64File(r.base64, r.filename || '模板.docx')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '下载失败')
    }
  }

  const handleUpload = async (t: TrainingTemplateDef, file: File) => {
    setUploadingKey(t.key)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await uploadTrainingExportTemplate(t.key, fd)
      message.success(r.message || `已上传模板 v${r.data?.version_no}`)
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploadingKey(null)
    }
  }

  const handleRestoreDefault = async (t: TrainingTemplateDef) => {
    try {
      const r = await restoreTrainingExportTemplateDefault(t.key)
      message.success(r.message || '已恢复官方默认模板')
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '恢复默认失败')
    }
  }

  const openHistory = async (t: TrainingTemplateDef) => {
    setHistoryFor(t)
    setVersions([])
    setVersionsLoading(true)
    try {
      const r = await listTrainingExportTemplateVersions(t.key)
      setVersions(r.data || [])
    } catch (e) {
      message.error(e instanceof Error ? e.message : '获取版本历史失败')
    } finally {
      setVersionsLoading(false)
    }
  }

  const handleActivate = async (t: TrainingTemplateDef, v: TrainingTemplateVersion) => {
    try {
      const r = await activateTrainingExportTemplateVersion(t.key, v.id)
      message.success(r.message || `已切换到 v${v.version_no}`)
      await openHistory(t)
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '激活版本失败')
    }
  }

  const toggleExpanded = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const markerColumns = [
    {
      title: '标记',
      dataIndex: 'name',
      width: 220,
      render: (v: string, r: TrainingTemplateMarker) => (
        <code className={r.required ? '' : 'opacity-60'}>{v}</code>
      ),
    },
    { title: '说明', dataIndex: 'description' },
    {
      title: '必填',
      dataIndex: 'required',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="orange">必填</Tag> : <Tag>可选</Tag>),
    },
  ]

  const versionColumns = [
    {
      title: '版本',
      dataIndex: 'version_no',
      width: 90,
      render: (v: number, r: TrainingTemplateVersion) => (
        <Space size={6}>
          <span>v{v}</span>
          {r.is_current && <Tag color="green">使用中</Tag>}
        </Space>
      ),
    },
    { title: '文件名', dataIndex: 'file_name', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'size',
      width: 90,
      render: (v: number) => formatSize(v),
    },
    { title: '上传人', dataIndex: 'uploaded_by', width: 100, render: (v: string | null) => v || '—' },
    {
      title: '上传时间',
      dataIndex: 'uploaded_at',
      width: 130,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: '操作',
      width: 150,
      render: (_: unknown, r: TrainingTemplateVersion) => {
        const t = historyFor
        if (!t) return null
        return (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(t, { versionId: r.id })}
            >
              下载
            </Button>
            {!r.is_current && (
              <Popconfirm title={`切换到 v${r.version_no} 作为当前模板？`} onConfirm={() => handleActivate(t, r)}>
                <Button type="link" size="small">激活</Button>
              </Popconfirm>
            )}
          </Space>
        )
      },
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="导出模板"
        description="培训各类导出文档的 Word 模板自助维护：在 Word 里改样式文字后上传换版，导出即时生效"
      />

      <Alert
        type="info"
        showIcon
        title="自维护步骤与注意事项"
        description={
          <ul className="list-disc pl-5 m-0 text-[13px] leading-6">
            <li>先「下载当前模板」或「下载默认模板」，在 Word 中修改样式与文字（增删行列都安全）</li>
            <li>保留模板中的 <code>{'{标记}'}</code>，上传缺必填标记的模板会被拒绝并提示缺哪些</li>
            <li>上传即生成新版本并立即生效；历史版本可随时回滚，「恢复默认」切回系统官方模板</li>
          </ul>
        }
      />

      {loading ? (
        <div className="flex justify-center py-16"><Spin /></div>
      ) : templates.length === 0 ? (
        <Empty description="没有可管理的模板" />
      ) : (
        <div className="space-y-4">
          {templates.map((t) => {
            const expanded = expandedKeys.has(t.key)
            return (
              <Card
                key={t.key}
                title={
                  <Space size={8}>
                    <span>{t.name}</span>
                    {t.custom ? (
                      <Tooltip title={`${t.custom.file_name} · ${formatSize(t.custom.size)} · ${t.custom.uploaded_by || '—'} · ${formatTime(t.custom.uploaded_at)}`}>
                        <Tag color="blue">自定义 v{t.custom.version_no}</Tag>
                      </Tooltip>
                    ) : (
                      <Tag>官方默认</Tag>
                    )}
                    {t.version_count > 0 && (
                      <span className="text-[12px] text-[var(--color-steel)]">共 {t.version_count} 个版本</span>
                    )}
                  </Space>
                }
                extra={
                  <Space size={4} wrap>
                    <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(t)}>
                      下载当前
                    </Button>
                    <Tooltip title="官方默认模板，推荐以它为基础修改">
                      <Button size="small" onClick={() => handleDownload(t, { isDefault: true })}>
                        下载默认
                      </Button>
                    </Tooltip>
                    <Upload
                      accept=".docx"
                      showUploadList={false}
                      beforeUpload={(file) => {
                        void handleUpload(t, file)
                        return false
                      }}
                      disabled={uploadingKey === t.key}
                    >
                      <Button size="small" type="primary" ghost loading={uploadingKey === t.key} icon={<UploadOutlined />}>
                        上传新版本
                      </Button>
                    </Upload>
                    {t.version_count > 0 && (
                      <Button size="small" icon={<HistoryOutlined />} onClick={() => void openHistory(t)}>
                        历史
                      </Button>
                    )}
                    {t.custom && (
                      <Popconfirm
                        title="恢复官方默认模板？"
                        description="当前自定义版转为历史版本，可随时再激活"
                        onConfirm={() => void handleRestoreDefault(t)}
                      >
                        <Button size="small" danger>恢复默认</Button>
                      </Popconfirm>
                    )}
                  </Space>
                }
              >
                <p className="m-0 text-[13px] text-[var(--color-steel)]">{t.description}</p>
                <div className="mt-2">
                  <Button type="link" size="small" className="!px-0" onClick={() => toggleExpanded(t.key)}>
                    {expanded ? '收起占位符' : `可用占位符（${t.markers.length}）`}
                  </Button>
                  {expanded && (
                    <div className="mt-2 space-y-2">
                      <Table
                        size="small"
                        rowKey="name"
                        columns={markerColumns}
                        dataSource={t.markers}
                        pagination={false}
                      />
                      {t.notes.length > 0 && (
                        <Alert
                          type="warning"
                          showIcon
                          title="模板修改注意"
                          description={
                            <ul className="list-disc pl-5 m-0 text-[13px] leading-6">
                              {t.notes.map((n) => <li key={n}>{n}</li>)}
                            </ul>
                          }
                        />
                      )}
                    </div>
                  )}
                </div>
              </Card>
            )
          })}
        </div>
      )}

      <Drawer
        title={historyFor ? `版本历史 · ${historyFor.name}` : '版本历史'}
        open={historyFor !== null}
        onClose={() => setHistoryFor(null)}
        size="large"
      >
        {versionsLoading ? (
          <div className="flex justify-center py-16"><Spin /></div>
        ) : (
          <Table rowKey="id" columns={versionColumns} dataSource={versions} pagination={false} />
        )}
      </Drawer>
    </div>
  )
}
