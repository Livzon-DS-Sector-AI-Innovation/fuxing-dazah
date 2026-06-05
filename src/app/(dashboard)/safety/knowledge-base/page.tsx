'use client'

import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  DatePicker,
  message,
  Tag,
  Card,
  Row,
  Col,
  Typography,
  Descriptions,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  SendOutlined,
  InboxOutlined,
  FileTextOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getKnowledgeArticles,
  getKnowledgeArticle,
  createKnowledgeArticle,
  updateKnowledgeArticle,
  deleteKnowledgeArticle,
  publishKnowledgeArticle,
  archiveKnowledgeArticle,
} from '@/actions/safety'
import type {
  SafetyKnowledgeArticle,
  SafetyKnowledgeArticleFormData,
} from '@/types/safety'
import {
  KNOWLEDGE_CATEGORY_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

export default function KnowledgeBasePage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SafetyKnowledgeArticle | null>(null)
  const [detailRecord, setDetailRecord] = useState<SafetyKnowledgeArticle | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()

  const {
    articles,
    articleTotal,
    articleQueryParams,
    setArticles,
    setArticleTotal,
    setArticleQueryParams,
    addArticle,
    updateArticle: updateArticleInStore,
    removeArticle,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getKnowledgeArticles({
        ...articleQueryParams,
        status: statusFilter,
        category: categoryFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setArticles(response.data)
        setArticleTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载知识库列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [articleQueryParams.page, articleQueryParams.page_size, statusFilter, categoryFilter])

  const handleSearch = () => {
    setArticleQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: SafetyKnowledgeArticle) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      publish_date: record.publish_date ? dayjs(record.publish_date) : undefined,
    })
    setModalVisible(true)
  }

  const handleViewDetail = async (record: SafetyKnowledgeArticle) => {
    try {
      const response = await getKnowledgeArticle(record.id)
      if (response.code === 200) {
        setDetailRecord(response.data)
        setDetailVisible(true)
        updateArticleInStore(record.id, response.data)
      }
    } catch {
      message.error('获取详情失败')
    }
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该知识文档吗？',
      onOk: async () => {
        const response = await deleteKnowledgeArticle(id)
        if (response.code === 200) { message.success('删除成功'); removeArticle(id) }
        else { message.error(response.message || '删除失败') }
      },
    })
  }

  const handleSubmit = async () => {
    try {
      const values = editingRecord ? await editForm.validateFields() : await form.validateFields()
      const formattedValues = {
        ...values,
        publish_date: values.publish_date ? values.publish_date.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateKnowledgeArticle(editingRecord.id, formattedValues)
        if (response.code === 200) { message.success('更新成功'); updateArticleInStore(editingRecord.id, response.data); setModalVisible(false) }
        else { message.error(response.message || '更新失败') }
      } else {
        const response = await createKnowledgeArticle(formattedValues as SafetyKnowledgeArticleFormData)
        if (response.code === 200) { message.success('创建成功'); addArticle(response.data); setModalVisible(false); form.resetFields() }
        else { message.error(response.message || '创建失败') }
      }
    } catch { console.error('表单验证失败') }
  }

  const handlePublish = async (id: string) => {
    const response = await publishKnowledgeArticle(id)
    if (response.code === 200) { message.success('发布成功'); updateArticleInStore(id, response.data) }
    else { message.error(response.message || '发布失败') }
  }

  const handleArchive = async (id: string) => {
    const response = await archiveKnowledgeArticle(id)
    if (response.code === 200) { message.success('已归档'); updateArticleInStore(id, response.data) }
    else { message.error(response.message || '归档失败') }
  }

  const columns: ColumnsType<SafetyKnowledgeArticle> = [
    { title: '编号', dataIndex: 'article_no', key: 'article_no', width: 130 },
    { title: '标题', dataIndex: 'title', key: 'title', width: 250, ellipsis: true },
    {
      title: '分类', dataIndex: 'category', key: 'category', width: 120,
      render: (c: string) => { const opt = KNOWLEDGE_CATEGORY_OPTIONS.find(o => o.value === c); return <Tag>{opt?.label || c}</Tag> },
    },
    { title: '来源', dataIndex: 'source', key: 'source', width: 150, ellipsis: true },
    { title: '作者', dataIndex: 'author', key: 'author', width: 100 },
    {
      title: '发布日期', dataIndex: 'publish_date', key: 'publish_date', width: 110,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    {
      title: '浏览', dataIndex: 'view_count', key: 'view_count', width: 70,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const colors: Record<string, string> = { draft: 'default', published: 'green', archived: 'default' }
        const labels: Record<string, string> = { draft: '草稿', published: '已发布', archived: '已归档' }
        return <Tag color={colors[s]}>{labels[s] || s}</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 240, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(record)}>查看</Button>
          {record.status === 'draft' && (
            <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handlePublish(record.id)}>发布</Button>
          )}
          {record.status === 'published' && (
            <Button type="link" size="small" icon={<InboxOutlined />} onClick={() => handleArchive(record.id)}>归档</Button>
          )}
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const formContent = (
    <>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="article_no" label="文档编号" rules={[{ required: true }]}>
            <Input placeholder="自动生成或手动输入" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="category" label="知识分类" rules={[{ required: true }]}>
            <Select options={KNOWLEDGE_CATEGORY_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="请选择分类" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="title" label="文档标题" rules={[{ required: true }]}>
        <Input placeholder="请输入文档标题" />
      </Form.Item>
      <Form.Item name="summary" label="摘要">
        <Input.TextArea rows={2} placeholder="请输入摘要" />
      </Form.Item>
      <Form.Item name="content" label="正文内容">
        <Input.TextArea rows={6} placeholder="请输入正文内容" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="tags" label="标签">
            <Input placeholder="多个以逗号分隔" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="publish_date" label="发布日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="source" label="来源">
            <Input placeholder="请输入来源/出处" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="author" label="作者">
            <Input placeholder="请输入作者/发布单位" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="notes" label="备注">
        <Input.TextArea rows={2} placeholder="请输入备注" />
      </Form.Item>
    </>
  )

  return (
    <div className="p-6">
      <Card
        title="安全知识库"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建文档
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={6}>
            <Input placeholder="搜索标题/内容/标签" prefix={<SearchOutlined />}
              value={searchText} onChange={e => setSearchText(e.target.value)} onPressEnter={handleSearch} />
          </Col>
          <Col span={5}>
            <Select placeholder="知识分类" allowClear value={categoryFilter}
              onChange={v => { setCategoryFilter(v); setArticleQueryParams({ page: 1 }) }}
              style={{ width: '100%' }}
              options={KNOWLEDGE_CATEGORY_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
          </Col>
          <Col span={5}>
            <Select placeholder="状态" allowClear value={statusFilter}
              onChange={v => { setStatusFilter(v); setArticleQueryParams({ page: 1 }) }}
              style={{ width: '100%' }}
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'published', label: '已发布' },
                { value: 'archived', label: '已归档' },
              ]} />
          </Col>
          <Col span={3}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
          </Col>
        </Row>

        <Table columns={columns} dataSource={articles} rowKey="id" loading={loading} scroll={{ x: 1300 }}
          pagination={{
            current: articleQueryParams.page, pageSize: articleQueryParams.page_size, total: articleTotal,
            showSizeChanger: true, showTotal: t => `共 ${t} 条`,
            onChange: (page, pageSize) => setArticleQueryParams({ page, page_size: pageSize }),
          }} />
      </Card>

      <Modal title={editingRecord ? '编辑文档' : '新建文档'} open={modalVisible}
        onOk={handleSubmit} onCancel={() => setModalVisible(false)} width={800} okText="确认" cancelText="取消">
        <Form form={editingRecord ? editForm : form} layout="vertical">
          {formContent}
        </Form>
      </Modal>

      <Modal title="文档详情" open={detailVisible} width={800}
        onCancel={() => { setDetailVisible(false); setDetailRecord(null) }}
        footer={<Button onClick={() => { setDetailVisible(false); setDetailRecord(null) }}>关闭</Button>}>
        {detailRecord && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="编号">{detailRecord.article_no}</Descriptions.Item>
            <Descriptions.Item label="分类">
              <Tag>{KNOWLEDGE_CATEGORY_OPTIONS.find(o => o.value === detailRecord.category)?.label}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="标题" span={2}>{detailRecord.title}</Descriptions.Item>
            <Descriptions.Item label="摘要" span={2}>{detailRecord.summary || '-'}</Descriptions.Item>
            <Descriptions.Item label="来源">{detailRecord.source || '-'}</Descriptions.Item>
            <Descriptions.Item label="作者">{detailRecord.author || '-'}</Descriptions.Item>
            <Descriptions.Item label="发布日期">
              {detailRecord.publish_date ? dayjs(detailRecord.publish_date).format('YYYY-MM-DD') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="浏览次数">{detailRecord.view_count}</Descriptions.Item>
            <Descriptions.Item label="标签" span={2}>{detailRecord.tags || '-'}</Descriptions.Item>
            <Descriptions.Item label="正文内容" span={2}>
              <div className="whitespace-pre-wrap">{detailRecord.content || '-'}</div>
            </Descriptions.Item>
            <Descriptions.Item label="附件">
              {detailRecord.attachment_original_name || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={{ draft: 'default', published: 'green', archived: 'default' }[detailRecord.status]}>
                {{ draft: '草稿', published: '已发布', archived: '已归档' }[detailRecord.status]}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}
