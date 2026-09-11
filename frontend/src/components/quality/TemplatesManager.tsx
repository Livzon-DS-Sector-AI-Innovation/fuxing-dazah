'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Table, Button, Space, App, Modal, Select, Upload, Input, Popconfirm, Tag, Typography,
} from 'antd'
import {
  UploadOutlined, FolderAddOutlined, DownloadOutlined, DeleteOutlined,
} from '@ant-design/icons'
import {
  fetchTemplates, uploadTemplate, createTemplateFolder, deleteTemplateFolder, deleteTemplateFile,
  bindTemplate, unbindTemplate, fetchStandardDocuments,
} from '@/actions/quality'

const { Text } = Typography
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface FlatTemplate {
  path: string
  folder: string
  filename: string
  size_kb: number
  placeholder_count: number
  modified: number
  matched: { doc_id: string; file_no: string; product_code: string } | null
  binding: { sop_no: string | null; doc_id: string | null; description: string | null } | null
}

function flattenTree(items: any[], prefix = ''): FlatTemplate[] {
  const out: FlatTemplate[] = []
  for (const it of items || []) {
    if (it.type === 'template') {
      out.push({
        path: prefix ? `${prefix}/${it.filename}` : it.filename,
        folder: prefix,
        filename: it.filename,
        size_kb: it.size_kb ?? 0,
        placeholder_count: it.placeholder_count ?? 0,
        modified: it.modified ?? 0,
        matched: it.matched ?? null,
        binding: it.binding ?? null,
      })
    } else if (it.children) {
      out.push(...flattenTree(it.children, prefix ? `${prefix}/${it.name}` : it.name))
    }
  }
  return out
}

export default function TemplatesManager() {
  const { message } = App.useApp()
  const [tree, setTree] = useState<any[]>([])
  const [files, setFiles] = useState<FlatTemplate[]>([])
  const [folders, setFolders] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')

  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFolder, setUploadFolder] = useState('')
  const [newFolderName, setNewFolderName] = useState('')

  const [bindOpen, setBindOpen] = useState(false)
  const [bindPath, setBindPath] = useState('')
  const [bindDocId, setBindDocId] = useState<string | undefined>()
  const [docOptions, setDocOptions] = useState<{ label: string; value: string }[]>([])

  const openBindModal = async (path: string) => {
    setBindPath(path)
    setBindDocId(undefined)
    setBindOpen(true)
    try {
      const res = await fetchStandardDocuments()
      setDocOptions((res.data || []).map((d) => ({ label: `${d.product_code || '-'} ${d.file_no}（${d.product_name.slice(0, 12)}）`, value: d.id })))
    } catch { /* 选项加载失败不阻塞 */ }
  }

  const handleBind = async () => {
    if (!bindDocId) {
      message.warning('请选择要绑定的标准文档（SOP）')
      return
    }
    try {
      await bindTemplate(bindPath, bindDocId)
      message.success('模板已绑定')
      setBindOpen(false)
      load()
    } catch (err: any) {
      message.error(err.message || '绑定失败')
    }
  }

  const handleUnbind = async (path: string) => {
    try {
      await unbindTemplate(path)
      message.success('已解绑')
      load()
    } catch (err: any) {
      message.error(err.message || '解绑失败')
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const t = await fetchTemplates()
      setTree(t)
      setFiles(flattenTree(t))
      setFolders((t || []).filter((x: any) => x.type === 'folder').map((x: any) => x.name))
    } catch (err: any) {
      message.error(err.message || '加载模板失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { load() }, [load])

  const handleUpload = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await uploadTemplate(uploadFolder, fd)
      if (res.bound && res.matched) {
        message.success(`模板已上传，并自动绑定 SOP：${res.matched.file_no}（${res.matched.product_code}）`)
      } else if (res.matched) {
        message.warning(`模板已上传，匹配到多个/冲突 SOP 未自动绑定，请在产品标准页手动绑定`)
      } else {
        message.warning('模板已上传，但未匹配到编号相同的 SOP（列表中已标「未匹配」）')
      }
      setUploadOpen(false)
      load()
    } catch (err: any) {
      message.error(err.message || '上传失败')
    }
    return false
  }

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return
    try {
      await createTemplateFolder(newFolderName.trim())
      message.success('文件夹已创建')
      setNewFolderName('')
      load()
    } catch (err: any) {
      message.error(err.message || '创建失败')
    }
  }

  const handleDeleteFolder = async (name: string) => {
    try {
      await deleteTemplateFolder(name)
      message.success('已删除')
      load()
    } catch (err: any) {
      message.error(err.message || '删除失败（文件夹须为空）')
    }
  }

  const handleDeleteFile = async (path: string) => {
    try {
      await deleteTemplateFile(path)
      message.success('已删除')
      load()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const filtered = files.filter((f) =>
    !search.trim() ||
    f.path.toLowerCase().includes(search.trim().toLowerCase()) ||
    f.filename.toLowerCase().includes(search.trim().toLowerCase()),
  )

  const columns = [
    { title: '模板路径', dataIndex: 'path', key: 'path', ellipsis: true },
    {
      title: '绑定 SOP', dataIndex: 'binding', key: 'binding', width: 180,
      render: (v: FlatTemplate['binding'], r: FlatTemplate) => v?.sop_no ? (
        <Tag color="green">{v.sop_no}</Tag>
      ) : (
        <Tag color="orange">⚠ 未绑定SOP</Tag>
      ),
    },
    { title: '文件夹', dataIndex: 'folder', key: 'folder', width: 160, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    { title: '占位符数', dataIndex: 'placeholder_count', key: 'placeholder_count', width: 90 },
    { title: '大小', dataIndex: 'size_kb', key: 'size_kb', width: 90, render: (v: number) => v ? `${v} KB` : '-' },
    {
      title: '修改时间', dataIndex: 'modified', key: 'modified', width: 170,
      render: (v: number) => v ? new Date(v * 1000).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 220,
      render: (_: any, r: FlatTemplate) => (
        <Space>
          {r.binding?.sop_no ? (
            <Button size="small" onClick={() => openBindModal(r.path)}>换绑</Button>
          ) : (
            <Button size="small" type="primary" onClick={() => openBindModal(r.path)}>绑定SOP</Button>
          )}
          {r.binding?.sop_no && (
            <Popconfirm title="确认解绑?" onConfirm={() => handleUnbind(r.path)}>
              <Button size="small">解绑</Button>
            </Popconfirm>
          )}
          <Button size="small" icon={<DownloadOutlined />}
            onClick={() => window.open(`${API_BASE_URL}/api/v1/quality/templates/${encodeURI(r.path)}/download`, '_blank')}>
            下载
          </Button>
          <Popconfirm title="确认删除该模板文件?" onConfirm={() => handleDeleteFile(r.path)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <Space wrap>
        <Input.Search
          placeholder="搜索模板（按文件名/路径）"
          allowClear
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 260 }}
        />
        <Input
          placeholder="新文件夹名（按产品名，如 妥布霉素）"
          value={newFolderName}
          onChange={(e) => setNewFolderName(e.target.value)}
          onPressEnter={handleCreateFolder}
          style={{ width: 240 }}
        />
        <Button icon={<FolderAddOutlined />} onClick={handleCreateFolder}>新建文件夹</Button>
        <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>上传模板</Button>
      </Space>

      <Space wrap size={4}>
        <Text type="secondary">文件夹：</Text>
        {folders.length === 0 && <Text type="secondary">（无，模板将存根目录）</Text>}
        {folders.map((f) => (
          <Tag key={f} closable onClose={(e) => { e.preventDefault(); handleDeleteFolder(f) }} color="blue">{f}</Tag>
        ))}
      </Space>

      <Table
        rowKey="path"
        size="small"
        columns={columns}
        dataSource={filtered}
        loading={loading}
        pagination={false}
      />

      <Modal
        title={`绑定 SOP —— ${bindPath}`}
        open={bindOpen}
        onCancel={() => setBindOpen(false)}
        onOk={handleBind}
        okText="绑定"
        width={520}
      >
        <div className="mt-4 space-y-2">
          <Text type="secondary">一份 COA 模板唯一绑定一份 SOP；一份 SOP 可绑定多份 COA 模板。</Text>
          <Select
            showSearch
            optionFilterProp="label"
            style={{ width: '100%' }}
            placeholder="选择标准文档（SOP）"
            value={bindDocId}
            onChange={setBindDocId}
            options={docOptions}
          />
        </div>
      </Modal>

      <Modal
        title="上传报告模板（.docx）"
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        footer={null}
        width={440}
      >
        <div className="mt-4 space-y-3">
          <Select
            style={{ width: '100%' }}
            placeholder="选择存放文件夹（缺省为根目录）"
            allowClear
            value={uploadFolder || undefined}
            onChange={(v) => setUploadFolder(v || '')}
            options={folders.map((f) => ({ label: f, value: f }))}
          />
          <Upload.Dragger accept=".docx" showUploadList={false} beforeUpload={handleUpload}>
            <p className="ant-upload-drag-icon"><UploadOutlined /></p>
            <p className="ant-upload-text">点击或拖拽 .docx 模板到此处上传</p>
            <p className="ant-upload-hint">模板文件名建议与 SOP 号码保持一致（如 3205.docx）</p>
          </Upload.Dragger>
        </div>
      </Modal>
    </div>
  )
}
