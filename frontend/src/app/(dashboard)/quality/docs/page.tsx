'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Button, Modal, Form, Input, Space, App,
  List, Upload, Popconfirm, Tag, Breadcrumb,
} from 'antd'
import {
  FolderOutlined, FileOutlined, PlusOutlined, UploadOutlined,
  DeleteOutlined, FolderAddOutlined, DownloadOutlined,
} from '@ant-design/icons'

const { Title, Paragraph, Text } = Typography
const API = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Category { id: string; product_name: string; category_name: string }
interface DocFile { id: string; original_filename: string; file_size: number | null; created_at: string | null }

export default function DocsPage() {
  const { message } = App.useApp()
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedCat, setSelectedCat] = useState<Category | null>(null)
  const [files, setFiles] = useState<DocFile[]>([])
  const [loading, setLoading] = useState(false)
  const [catModalOpen, setCatModalOpen] = useState(false)
  const [catForm] = Form.useForm()
  const [upLoading, setUpLoading] = useState(false)

  const loadCats = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/api/v1/quality/docs/categories`)
      const json = await res.json()
      setCategories(json.data || [])
    } catch { message.error('加载大类失败') }
    finally { setLoading(false) }
  }, [message])

  const loadFiles = useCallback(async (catId: string) => {
    try {
      const res = await fetch(`${API}/api/v1/quality/docs/categories/${catId}/files`)
      const json = await res.json()
      setFiles(json.data || [])
    } catch { message.error('加载文件失败') }
  }, [message])

  useEffect(() => { loadCats() }, [loadCats])

  const handleCreateCat = async () => {
    const vals = await catForm.validateFields()
    try {
      await fetch(`${API}/api/v1/quality/docs/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(vals),
      })
      message.success('大类已创建')
      setCatModalOpen(false)
      catForm.resetFields()
      loadCats()
    } catch { message.error('创建失败') }
  }

  const handleDeleteCat = async (id: string) => {
    try {
      await fetch(`${API}/api/v1/quality/docs/categories/${id}`, { method: 'DELETE' })
      message.success('已删除')
      if (selectedCat?.id === id) { setSelectedCat(null); setFiles([]) }
      loadCats()
    } catch { message.error('删除失败') }
  }

  const handleUpload = async (file: File) => {
    if (!selectedCat) { message.warning('请先选择一个大类'); return false }
    setUpLoading(true)
    const fd = new FormData()
    fd.append('file', file)
    fd.append('category_id', selectedCat.id)
    fd.append('product_name', selectedCat.product_name)
    try {
      const res = await fetch(`${API}/api/v1/quality/docs/upload`, {
        method: 'POST', body: fd,
      })
      if (!res.ok) throw new Error('')
      message.success(`已上传：${file.name}`)
      loadFiles(selectedCat.id)
    } catch { message.error('上传失败') }
    finally { setUpLoading(false) }
    return false
  }

  const handleDownload = (docId: string) => {
    window.open(`${API}/api/v1/quality/docs/${docId}/download`, '_blank')
  }

  const handleDeleteDoc = async (docId: string) => {
    try {
      await fetch(`${API}/api/v1/quality/docs/${docId}`, { method: 'DELETE' })
      message.success('已删除')
      if (selectedCat) loadFiles(selectedCat.id)
    } catch { message.error('删除失败') }
  }

  const groupedCats = categories.reduce((acc: Record<string, Category[]>, c) => {
    (acc[c.product_name] ??= []).push(c); return acc
  }, {})

  return (
    <div>
      <Title level={3}><FolderOutlined /> 标准文件库</Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        按产品→大类管理标准文档，支持批量上传和下载。
      </Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Button icon={<FolderAddOutlined />} onClick={() => setCatModalOpen(true)}>新建大类</Button>
      </Space>

      <div style={{ display: 'flex', gap: 16 }}>
        {/* 左侧：产品→大类树 */}
        <Card size="small" title="产品 / 大类" style={{ width: 300, maxHeight: '70vh', overflow: 'auto' }}>
          {Object.entries(groupedCats).map(([product, cats]) => (
            <div key={product} style={{ marginBottom: 12 }}>
              <Text strong style={{ fontSize: 13 }}>{product}</Text>
              <List size="small" dataSource={cats}
                renderItem={(cat: Category) => (
                  <List.Item
                    style={{ cursor: 'pointer', padding: '4px 8px',
                      background: selectedCat?.id === cat.id ? '#e6f4ff' : undefined }}
                    onClick={() => { setSelectedCat(cat); loadFiles(cat.id) }}
                    actions={[
                      <Popconfirm key="del" title="确认删除?" onConfirm={() => handleDeleteCat(cat.id)}>
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    ]}
                  >
                    <FolderOutlined style={{ marginRight: 6 }} />{cat.category_name}
                  </List.Item>
                )}
              />
            </div>
          ))}
          {categories.length === 0 && <Text type="secondary">暂无大类，请新建</Text>}
        </Card>

        {/* 右侧：文件列表 */}
        <Card size="small" title={selectedCat
          ? <Breadcrumb items={[
              { title: selectedCat.product_name },
              { title: selectedCat.category_name },
            ]} />
          : '请选择左侧大类'}
          extra={selectedCat && <Upload beforeUpload={handleUpload} showUploadList={false}
            accept=".pdf,.doc,.docx,.xlsx">
            <Button icon={<UploadOutlined />} loading={upLoading}>上传文件</Button>
          </Upload>}
          style={{ flex: 1, minHeight: 400 }}
        >
          {selectedCat && (
            <List dataSource={files}
              renderItem={(f: DocFile) => (
                <List.Item actions={[
                  <Button key="dl" size="small" icon={<DownloadOutlined />}
                    onClick={() => handleDownload(f.id)}>下载</Button>,
                  <Popconfirm key="del" title="确认删除?" onConfirm={() => handleDeleteDoc(f.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>,
                ]}>
                  <FileOutlined style={{ marginRight: 8 }} />
                  <Text>{f.original_filename}</Text>
                  <Text type="secondary" style={{ marginLeft: 12 }}>
                    {f.file_size ? `${(f.file_size / 1024).toFixed(1)}KB` : ''}
                  </Text>
                </List.Item>
              )}
              locale={{ emptyText: '暂无文件，点击上方按钮上传' }}
            />
          )}
        </Card>
      </div>

      <Modal title="新建大类" open={catModalOpen}
        onOk={handleCreateCat} onCancel={() => setCatModalOpen(false)}>
        <Form form={catForm} layout="vertical">
          <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
            <Input placeholder="如 盐酸万古霉素" />
          </Form.Item>
          <Form.Item name="category_name" label="大类名称" rules={[{ required: true }]}>
            <Input placeholder="如 含量、有关物质、微生物限度" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
