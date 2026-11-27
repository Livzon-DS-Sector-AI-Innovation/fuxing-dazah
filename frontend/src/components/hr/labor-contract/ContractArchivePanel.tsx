'use client'

// 合同扫描件归档区（电子档案库 P2）：归档状态 + 版本列表（当前版/历史版）+ 上传换版 +
// 原件预览/下载 + 调阅记录。合同详情抽屉、员工档案「合同」页签共用。
// canManage / canAccessFile 由后端按数据范围下发（HR 全部原件、员工本人仅本人、部门范围
// 只有基本信息），这里只控制入口显隐，把关在后端端点。

import { useEffect, useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Empty,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Tooltip,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import { DeleteOutlined, DownloadOutlined, EyeOutlined, UploadOutlined } from '@ant-design/icons'
import {
  deleteContractArchiveVersion,
  downloadContractArchiveFile,
  fetchContractAccessLogs,
  fetchContractArchiveVersions,
  previewContractArchiveFile,
  uploadContractArchive,
} from '@/actions/hr'
import { base64ToObjectUrl, downloadBase64File } from '@/lib/hr/download'
import { formatDateTime } from '@/lib/hr/format'
import type {
  ContractAccessLog,
  ContractArchiveStatus,
  ContractArchiveVersion,
  LaborContract,
} from '@/types/hr'

const SOURCE_LABELS: Record<ContractArchiveVersion['source'], string> = {
  single: '单个上传',
  batch: '批量挂接',
}

function fmtSize(size: number): string {
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  return `${Math.max(1, Math.round(size / 1024))}KB`
}

/** 后端返回的是带 +00:00 的 UTC 时间串：必须按本地时区格式化，不能直接截取 */
function fmtTime(iso?: string | null): string {
  return iso ? formatDateTime(iso) : '-'
}

interface Props {
  contractId: string
  /** 合同行上的归档快照（决定「上传」还是「换传新版本」与状态标签） */
  archiveStatus?: ContractArchiveStatus
  /** 上传 / 删除版本：仅 HR（后端最终把关） */
  canManage: boolean
  /** 原件预览 / 下载：HR 与员工本人 */
  canAccessFile: boolean
  /** 上传 / 删除后回调（父级刷新合同数据） */
  onChanged?: (contract: LaborContract) => void
}

export default function ContractArchivePanel({
  contractId, archiveStatus, canManage, canAccessFile, onChanged,
}: Props) {
  const { message, modal } = App.useApp()
  const [versions, setVersions] = useState<ContractArchiveVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [logsOpen, setLogsOpen] = useState(false)

  // 上传 / 换传新版本
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [remark, setRemark] = useState('')

  // 预览
  const [previewInfo, setPreviewInfo] = useState<{ url: string; type: string; name: string } | null>(null)

  const archived = archiveStatus === 'archived'

  // 版本列表加载（挂载 / 切换合同）：setState 全部在 await 之后，不在 effect 里同步触发级联渲染
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchContractArchiveVersions(contractId)
        if (!cancelled) setVersions(r.data || [])
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载扫描件失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId])

  useEffect(() => () => {
    if (previewInfo) window.URL.revokeObjectURL(previewInfo.url)
  }, [previewInfo])

  const handleUpload = async () => {
    const file = fileList[0]?.originFileObj as File | undefined
    if (!file) { message.warning('请选择合同扫描件（图片/PDF）'); return }
    setUploading(true)
    try {
      const r = await uploadContractArchive(contractId, file, remark)
      message.success(r.message || '已归档')
      setVersions(r.data.versions)
      setUploadOpen(false)
      setFileList([])
      setRemark('')
      onChanged?.(r.data.contract)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handlePreview = async (v: ContractArchiveVersion) => {
    try {
      const r = await previewContractArchiveFile(contractId, v.id)
      const type = v.content_type === 'application/pdf' ? 'application/pdf'
        : v.content_type.startsWith('image/') ? v.content_type : 'application/octet-stream'
      setPreviewInfo({ url: base64ToObjectUrl(r.base64, type), type, name: r.filename || v.file_name })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '获取原件失败')
    }
  }

  const handleDownload = async (v: ContractArchiveVersion) => {
    try {
      const r = await downloadContractArchiveFile(contractId, v.id)
      downloadBase64File(r.base64, r.filename || v.file_name)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '下载失败')
    }
  }

  const handleDelete = (v: ContractArchiveVersion) => {
    modal.confirm({
      title: `删除扫描件 v${v.version_no}？`,
      content: v.is_current
        ? '删除当前版后，最新历史版本自动顶替；没有剩余版本时合同回到「未归档」。'
        : '历史版本删除后不可在页面恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const r = await deleteContractArchiveVersion(contractId, v.id)
          message.success(r.message || '已删除')
          setVersions(r.data.versions)
          onChanged?.(r.data.contract)
        } catch (e) {
          message.error(e instanceof Error ? e.message : '删除失败')
        }
      },
    })
  }

  const current = versions.find((v) => v.is_current)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <Space size={8} wrap>
          <span className="text-[14px] font-medium">电子档案</span>
          <Tag color={archived ? 'green' : 'orange'}>{archived ? '已归档' : '未归档'}</Tag>
          {current && versions.length > 1 && (
            <span className="text-xs text-gray-500">当前 v{current.version_no} · 历史 {versions.length - 1} 版</span>
          )}
        </Space>
        {canManage && (
          <Button size="small" type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
            {archived ? '换传新版本' : '上传扫描件'}
          </Button>
        )}
      </div>

      {!archived && (
        <div className="text-xs text-gray-500">
          尚未归档：员工领取签字后，把逐页合并的扫描件（图片/PDF，≤20MB）上传到这里。
        </div>
      )}

      <Table<ContractArchiveVersion>
        rowKey="id"
        size="small"
        loading={loading}
        pagination={false}
        dataSource={versions}
        locale={{ emptyText: <Empty description="暂无扫描件" className="py-4" /> }}
        columns={[
          {
            title: '版本', width: 100,
            render: (_, v) => (
              <Space size={4}>
                <span>v{v.version_no}</span>
                {v.is_current && <Tag color="blue" style={{ marginInlineEnd: 0 }}>当前版</Tag>}
              </Space>
            ),
          },
          {
            title: '文件名', dataIndex: 'file_name', ellipsis: true,
            render: (name: string, v) => (
              <Tooltip title={`${name}（${fmtSize(v.size)}）${v.remark ? ` · ${v.remark}` : ''}`}>
                <span>{name}</span>
              </Tooltip>
            ),
          },
          {
            title: '来源', dataIndex: 'source', width: 92,
            render: (s: ContractArchiveVersion['source']) => SOURCE_LABELS[s] ?? s,
          },
          { title: '归档时间', dataIndex: 'uploaded_at', width: 144, render: fmtTime },
          {
            title: '操作', width: 168,
            render: (_, v) => (
              <Space size={0}>
                <Button size="small" type="text" icon={<EyeOutlined />} disabled={!canAccessFile}
                  onClick={() => void handlePreview(v)}>
                  查看
                </Button>
                <Button size="small" type="text" icon={<DownloadOutlined />} disabled={!canAccessFile}
                  onClick={() => void handleDownload(v)}>
                  下载
                </Button>
                {canManage && (
                  <Button size="small" type="text" danger icon={<DeleteOutlined />}
                    onClick={() => handleDelete(v)}>
                    删除
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Button size="small" type="link" className="!px-0" onClick={() => setLogsOpen((o) => !o)}>
        调阅记录{logsOpen ? '（收起）' : ''}
      </Button>
      {logsOpen && <AccessLogsTable contractId={contractId} />}

      <Modal
        title={archived ? '换传新版本' : '上传合同扫描件'}
        open={uploadOpen}
        okText="上传归档"
        confirmLoading={uploading}
        okButtonProps={{ disabled: fileList.length === 0 }}
        onCancel={() => setUploadOpen(false)}
        onOk={() => void handleUpload()}
      >
        <div className="space-y-3 pt-2">
          <div className="text-[13px] text-gray-500">
            一份合同一个合并文件（逐页扫描后合并）：图片或 PDF，单个 ≤20MB。
            {archived
              ? '上传后成为新版本，旧版本保留在历史版本中可查。'
              : '归档后文件名按「工号 + 姓名 + 签订次数 + 起止日期」自动生成。'}
          </div>
          <Upload
            accept=".jpg,.jpeg,.png,.webp,.bmp,.pdf"
            maxCount={1}
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: next }) => setFileList(next)}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <Input
            placeholder="备注（选填，如：补扫、清晰版替换）"
            maxLength={512}
            value={remark}
            onChange={(e) => setRemark(e.target.value)}
          />
        </div>
      </Modal>

      <Drawer
        title={previewInfo?.name || '合同扫描件'}
        size={620}
        open={!!previewInfo}
        onClose={() => setPreviewInfo(null)}
        extra={previewInfo && (
          <Button size="small" onClick={() => {
            const a = document.createElement('a')
            a.href = previewInfo.url
            a.download = previewInfo.name
            a.click()
          }}>另存为</Button>
        )}
      >
        {previewInfo && (
          previewInfo.type === 'application/pdf' ? (
            // 抽屉内容区不是定高容器，h-full 会塌成 iframe 默认的 150px；按视口高度撑满
            <iframe src={previewInfo.url} title="合同扫描件预览" className="w-full border-0"
              style={{ height: 'calc(100vh - 110px)' }} />
          ) : previewInfo.type.startsWith('image/') ? (
            // blob URL 预览图，不适用 next/image（无固定尺寸、运行时生成）
            // eslint-disable-next-line @next/next/no-img-element
            <img src={previewInfo.url} alt={previewInfo.name} className="w-full" />
          ) : (
            <Empty description="该文件类型不支持在线预览，请下载后查看" />
          )
        )}
      </Drawer>
    </div>
  )
}

/** 某份合同的调阅/下载记录（展开时才加载） */
function AccessLogsTable({ contractId }: { contractId: string }) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<ContractAccessLog[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchContractAccessLogs(contractId, { page_size: 50 })
        if (!cancelled) setRows(r.data || [])
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载调阅记录失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId])

  return (
    <Table<ContractAccessLog>
      rowKey="id"
      size="small"
      loading={loading}
      pagination={false}
      dataSource={rows}
      locale={{ emptyText: <Empty description="暂无调阅记录" className="py-4" /> }}
      columns={[
        { title: '调阅人', dataIndex: 'viewer_name', width: 120 },
        { title: '动作', width: 96, render: (_, r) => <Tag color={r.action === 'download' ? 'orange' : 'blue'}>{r.action_label}</Tag> },
        { title: '版本', width: 80, render: (_, r) => (r.version_no ? `v${r.version_no}` : '-') },
        { title: '时间', dataIndex: 'created_at', render: fmtTime },
      ]}
    />
  )
}
