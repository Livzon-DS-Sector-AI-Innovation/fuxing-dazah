'use client'

import { useState, useEffect } from 'react'
import { Table, Typography, Button, Upload, Popconfirm, Space, Tag, message, Card, Input, Modal, Tabs, Empty } from 'antd'
import { UploadOutlined, DeleteOutlined, FolderOutlined, FileTextOutlined, ReloadOutlined, PlusOutlined } from '@ant-design/icons'

const { Title, Text } = Typography
const API = 'http://localhost:8000/api/v1/quality/templates'

interface TplItem {
  filename: string; size_kb: number; modified: number
  placeholder_count: number; folder: string
}

export default function TemplatesPage() {
  const [tree, setTree] = useState<any[]>([])
  const [activeTab, setActiveTab] = useState('')
  const [loading, setLoading] = useState(false)
  const [folderOpen, setFolderOpen] = useState(false)
  const [folderName, setFolderName] = useState('')

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const r = await fetch(API)
      if (r.ok) setTree(await r.json())
      else message.error('API error: ' + r.status)
    } catch (e: any) { message.error('无法连接后端: ' + (e.message || '')) }
    setLoading(false)
  }

  const allFolders: { name: string; path: string }[] = []
  function walkFolders(items: any[], path: string) {
    items.forEach(item => {
      if (item.type === 'folder') {
        allFolders.push({ name: item.name, path: path + item.name + '/' })
        walkFolders(item.children || [], path + item.name + '/')
      }
    })
  }
  walkFolders(tree, '')

  function getTemplates(folderPath: string): TplItem[] {
    const result: TplItem[] = []
    function walk(items: any[], fp: string) {
      items.forEach(item => {
        if (item.type === 'folder') walk(item.children || [], fp + item.name + '/')
        else if (!folderPath || fp.startsWith(folderPath)) result.push({ ...item, folder: fp })
      })
    }
    walk(tree, '')
    return result
  }

  const currentTemplates = getTemplates(activeTab)

  function folderTemplateCount(fp: string) { return getTemplates(fp).length }

  async function createFolder() {
    if (!folderName.trim()) return
    await fetch(API + '/folders', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: folderName.trim() }),
    })
    setFolderOpen(false); setFolderName(''); load(); message.success('已创建')
  }

  async function doUpload(file: File) {
    const fd = new FormData(); fd.append('file', file)
    if (activeTab) fd.append('folder', activeTab)
    const r = await fetch(API + '/upload', { method: 'POST', body: fd })
    if (r.ok) { message.success(file.name + ' 已上传'); load() }
    else { const e = await r.json().catch(() => ({})); throw new Error(e.detail || '失败') }
  }

  async function delTemplate(fp: string) {
    await fetch(API + '/' + encodeURIComponent(fp), { method: 'DELETE' }); load()
  }

  function handleUpload(file: File) {
    const exists = currentTemplates.some(t => t.filename === file.name)
    if (exists) {
      Modal.confirm({
        title: '覆盖确认', content: '模板「' + file.name + '」已存在，是否覆盖？',
        okText: '覆盖', okType: 'danger', cancelText: '取消',
        onOk: async () => { await doUpload(file) },
      })
    } else {
      doUpload(file)
    }
    return false
  }

  const columns = [
    { title: '文件名', dataIndex: 'filename',
      render: (v: string) => <Space><FileTextOutlined style={{ color: '#1a73e8' }} /><Text strong>{v}</Text></Space> },
    { title: '大小', dataIndex: 'size_kb', width: 70, render: (v: number) => <Text type="secondary">{v} KB</Text> },
    { title: '上传时间', dataIndex: 'modified', width: 150,
      render: (v: number) => <Text style={{ fontSize: 11 }}>{new Date(v * 1000).toLocaleString('zh-CN')}</Text> },
    { title: '占位符', dataIndex: 'placeholder_count', width: 80, render: (v: number) => <Tag color="blue">{v} 个</Tag> },
    { title: '操作', key: 'act', width: 80,
      render: (_: any, r: TplItem) => {
        const fp = (r.folder ? r.folder : '') + r.filename
        return (
          <Popconfirm title="删除？" onConfirm={() => delTemplate(fp)}>
            <Button type="link" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        )
      } },
  ]

  const tabItems = [
    { key: '', label: '全部', children: null },
    ...allFolders.map(f => ({
      key: f.path,
      label: <span><FolderOutlined style={{ color: '#faad14', marginRight: 2 }} />{f.name}
        <Popconfirm
          title={'删除文件夹「' + f.name + '」？'}
          description={folderTemplateCount(f.path) > 0 ? '内有 ' + folderTemplateCount(f.path) + ' 个模板，请先移走或删除' : '文件夹为空，删除后不可恢复'}
          okText="删除"
          okButtonProps={{ danger: true, disabled: folderTemplateCount(f.path) > 0 }}
          onConfirm={async () => {
            await fetch(API + '/folders', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: f.path }) })
            load(); setActiveTab('')
          }}
        >
          <Button type="link" danger size="small" style={{ fontSize: 9, padding: 0, marginLeft: 4, minWidth: 14 }}>x</Button>
        </Popconfirm>
      </span>,
      children: null,
    })),
    {
      key: '__add__',
      label: <Button type="text" size="small" icon={<PlusOutlined />} onClick={() => setFolderOpen(true)}
        style={{ color: '#1a73e8', padding: '0 8px', fontSize: 11 }}>新建</Button>,
      children: null, disabled: true,
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <FileTextOutlined style={{ fontSize: 20, color: '#1a73e8' }} />
          <Title level={4} style={{ margin: 0 }}>报告模板管理</Title>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Upload accept=".docx" showUploadList={false} maxCount={1}
            beforeUpload={(file) => { handleUpload(file); return false }}>
            <Button type="primary" icon={<UploadOutlined />}>
              上传模板{activeTab ? '到「' + (allFolders.find(f => f.path === activeTab)?.name || activeTab) + '」' : ''}
            </Button>
          </Upload>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 8 }}>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} size="small" type="card" />
      </Card>

      <Card size="small">
        {currentTemplates.length ? (
          <Table columns={columns} dataSource={currentTemplates.map((t, i) => ({ ...t, key: i }))}
            pagination={false} size="small" />
        ) : (
          <Empty description="此分类暂无模板，请上传" />
        )}
      </Card>

      <Modal title="新建分类文件夹" open={folderOpen} onOk={createFolder} onCancel={() => setFolderOpen(false)}>
        <Input placeholder="如：万古霉素、头孢" value={folderName} onChange={e => setFolderName(e.target.value)} />
      </Modal>
    </div>
  )
}
