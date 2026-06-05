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
  Upload,
  message,
  Tag,
  Card,
  Row,
  Col,
  Typography,
  Tabs,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  UploadOutlined,
  CheckCircleOutlined,
  LinkOutlined,
  FileTextOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getHazardRevisionRecords,
  createHazardRevisionRecord,
  updateHazardRevisionRecord,
  deleteHazardRevisionRecord,
  approveHazardRevision,
  uploadHazardRevisionDocument,
  linkRevisionToArchive,
  getHazardRevisionArchives,
  createHazardRevisionArchive,
  updateHazardRevisionArchive,
  deleteHazardRevisionArchive,
  getRevisions,
} from '@/actions/safety'
import type {
  HazardRevisionRecord,
  HazardRevisionRecordFormData,
  HazardRevisionArchive,
  HazardRevisionArchiveFormData,
  RegulationRevision,
} from '@/types/safety'
import {
  IdentificationType,
  IDENTIFICATION_TYPE_OPTIONS,
  REVIEW_OPINION_OPTIONS,
  ARCHIVE_STATUS_OPTIONS,
  IDENTIFICATION_SCOPE_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

export default function HazardRevisionPage() {
  const [activeTab, setActiveTab] = useState('records')

  // Record states
  const [recordForm] = Form.useForm()
  const [recordEditForm] = Form.useForm()
  const [recordLoading, setRecordLoading] = useState(false)
  const [recordModalVisible, setRecordModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<HazardRevisionRecord | null>(null)
  const [recordSearchText, setRecordSearchText] = useState('')
  const [recordTypeFilter, setRecordTypeFilter] = useState<string | undefined>()
  const [recordOpinionFilter, setRecordOpinionFilter] = useState<string | undefined>()

  // Archive states
  const [archiveForm] = Form.useForm()
  const [archiveEditForm] = Form.useForm()
  const [archiveLoading, setArchiveLoading] = useState(false)
  const [archiveModalVisible, setArchiveModalVisible] = useState(false)
  const [editingArchive, setEditingArchive] = useState<HazardRevisionArchive | null>(null)
  const [archiveSearchText, setArchiveSearchText] = useState('')
  const [archiveStatusFilter, setArchiveStatusFilter] = useState<string | undefined>()

  // Link modal
  const [linkModalVisible, setLinkModalVisible] = useState(false)
  const [linkingRecordId, setLinkingRecordId] = useState<string | null>(null)
  const [archives, setArchives] = useState<HazardRevisionArchive[]>([])

  // Revisions for create form
  const [revisions, setRevisions] = useState<RegulationRevision[]>([])

  const {
    hazardRevisionRecords,
    hazardRevisionRecordTotal,
    hazardRevisionRecordQueryParams,
    setHazardRevisionRecords,
    setHazardRevisionRecordTotal,
    setHazardRevisionRecordQueryParams,
    addHazardRevisionRecord,
    updateHazardRevisionRecord: updateRecordInStore,
    removeHazardRevisionRecord,

    hazardRevisionArchives,
    hazardRevisionArchiveTotal,
    hazardRevisionArchiveQueryParams,
    setHazardRevisionArchives,
    setHazardRevisionArchiveTotal,
    setHazardRevisionArchiveQueryParams,
    addHazardRevisionArchive,
    updateHazardRevisionArchive: updateArchiveInStore,
    removeHazardRevisionArchive,
  } = useSafetyStore()

  // ============ Record Handlers ============

  const loadRecords = async () => {
    setRecordLoading(true)
    try {
      const response = await getHazardRevisionRecords({
        ...hazardRevisionRecordQueryParams,
        keyword: recordSearchText || undefined,
        identification_type: recordTypeFilter,
        review_opinion: recordOpinionFilter,
      })
      if (response.code === 200) {
        setHazardRevisionRecords(response.data)
        setHazardRevisionRecordTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载危险源辨识记录失败')
    } finally {
      setRecordLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'records') loadRecords()
  }, [
    hazardRevisionRecordQueryParams.page,
    hazardRevisionRecordQueryParams.page_size,
    recordTypeFilter,
    recordOpinionFilter,
    activeTab,
  ])

  const loadRevisions = async () => {
    try {
      const response = await getRevisions({ page: 1, page_size: 500 })
      if (response.code === 200) {
        setRevisions(response.data)
      }
    } catch {
      // silent
    }
  }

  useEffect(() => {
    loadRevisions()
  }, [])

  const handleRecordSearch = () => {
    setHazardRevisionRecordQueryParams({ page: 1 })
    loadRecords()
  }

  const handleAddRecord = () => {
    setEditingRecord(null)
    recordForm.resetFields()
    setRecordModalVisible(true)
  }

  const handleEditRecord = (record: HazardRevisionRecord) => {
    setEditingRecord(record)
    recordEditForm.setFieldsValue(record)
    setRecordModalVisible(true)
  }

  const handleDeleteRecord = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个危险源辨识记录吗？',
      onOk: async () => {
        try {
          const response = await deleteHazardRevisionRecord(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeHazardRevisionRecord(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleRecordSubmit = async () => {
    try {
      const values = editingRecord
        ? await recordEditForm.validateFields()
        : await recordForm.validateFields()

      if (editingRecord) {
        const response = await updateHazardRevisionRecord(editingRecord.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateRecordInStore(editingRecord.id, response.data)
          setRecordModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createHazardRevisionRecord(values as HazardRevisionRecordFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addHazardRevisionRecord(response.data)
          setRecordModalVisible(false)
          recordForm.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleApproveRecord = async (id: string) => {
    Modal.confirm({
      title: '确认审核',
      content: '确定要审核通过这个危险源辨识记录吗？',
      onOk: async () => {
        try {
          const response = await approveHazardRevision(id)
          if (response.code === 200) {
            message.success('审核通过')
            loadRecords()
          } else {
            message.error(response.message || '审核失败')
          }
        } catch {
          message.error('审核失败')
        }
      },
    })
  }

  const handleUploadHazardDoc = async (recordId: string, file: File) => {
    try {
      const response = await uploadHazardRevisionDocument(recordId, file)
      if (response.code === 200) {
        message.success('文档上传成功')
        loadRecords()
      } else {
        message.error(response.message || '上传失败')
      }
    } catch {
      message.error('上传失败')
    }
  }

  const hazardUploadProps = (recordId: string): UploadProps => ({
    showUploadList: false,
    beforeUpload: async (file) => {
      await handleUploadHazardDoc(recordId, file)
      return false
    },
  })

  // Link to archive
  const handleOpenLink = async (recordId: string) => {
    setLinkingRecordId(recordId)
    setLinkModalVisible(true)
    // Load archives for selection
    try {
      const response = await getHazardRevisionArchives({ page: 1, page_size: 500 })
      if (response.code === 200) {
        setArchives(response.data)
      }
    } catch {
      // silent
    }
  }

  const handleLinkToArchive = async (archiveId: string) => {
    if (!linkingRecordId) return
    try {
      const response = await linkRevisionToArchive(linkingRecordId, archiveId)
      if (response.code === 200) {
        message.success('关联成功')
        setLinkModalVisible(false)
        setLinkingRecordId(null)
        loadRecords()
      } else {
        message.error(response.message || '关联失败')
      }
    } catch {
      message.error('关联失败')
    }
  }

  const getReviewOpinionColor = (opinion: string) => {
    const option = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
    return option?.color || 'default'
  }

  const getReviewOpinionLabel = (opinion: string) => {
    const option = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
    return option?.label || opinion
  }

  const recordColumns: ColumnsType<HazardRevisionRecord> = [
    {
      title: '辨识编号',
      dataIndex: 'hazard_revision_no',
      key: 'hazard_revision_no',
      width: 150,
    },
    {
      title: '操规名称',
      dataIndex: 'regulation_name',
      key: 'regulation_name',
      width: 180,
      ellipsis: true,
    },
    {
      title: '辨识类型',
      dataIndex: 'identification_type',
      key: 'identification_type',
      width: 100,
      render: (type: IdentificationType) => {
        const option = IDENTIFICATION_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag color={option?.color}>{option?.label || type}</Tag>
      },
    },
    {
      title: '辨识人',
      dataIndex: 'identifier_name',
      key: 'identifier_name',
      width: 100,
      render: (name: string) => name || '-',
    },
    {
      title: '辨识时间',
      dataIndex: 'identification_time',
      key: 'identification_time',
      width: 120,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '辨识范围',
      dataIndex: 'identification_scope',
      key: 'identification_scope',
      width: 120,
      render: (scope: string) => {
        if (!scope) return <Tag color="default">未分析</Tag>
        const scopes = scope.split(',').map((s) => s.trim())
        return (
          <Space size={2} wrap>
            {scopes.map((s) => (
              <Tag key={s} color="blue" style={{ fontSize: 11 }}>
                {s}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '审核状态',
      dataIndex: 'review_opinion',
      key: 'review_opinion',
      width: 90,
      render: (opinion: string) => (
        <Tag color={getReviewOpinionColor(opinion)}>{getReviewOpinionLabel(opinion)}</Tag>
      ),
    },
    {
      title: '关联存档',
      dataIndex: 'linked_hazard_archive_id',
      key: 'linked_hazard_archive_id',
      width: 100,
      render: (id: string) =>
        id ? <Tag color="success">已关联</Tag> : <Tag color="default">未关联</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 320,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {record.review_opinion === 'pending' && (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleApproveRecord(record.id)}
              style={{ color: '#52c41a' }}
            >
              审核
            </Button>
          )}
          <Upload {...hazardUploadProps(record.id)}>
            <Button type="link" size="small" icon={<UploadOutlined />}>
              上传
            </Button>
          </Upload>
          {!record.linked_hazard_archive_id && (
            <Button
              type="link"
              size="small"
              icon={<LinkOutlined />}
              onClick={() => handleOpenLink(record.id)}
            >
              关联存档
            </Button>
          )}
          {record.hazard_document_path && (
            <Button type="link" size="small" icon={<EyeOutlined />}>
              查看文档
            </Button>
          )}
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEditRecord(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDeleteRecord(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  // ============ Archive Handlers ============

  const loadArchives = async () => {
    setArchiveLoading(true)
    try {
      const response = await getHazardRevisionArchives({
        ...hazardRevisionArchiveQueryParams,
        keyword: archiveSearchText || undefined,
        status: archiveStatusFilter,
      })
      if (response.code === 200) {
        setHazardRevisionArchives(response.data)
        setHazardRevisionArchiveTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载存档列表失败')
    } finally {
      setArchiveLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'archives') loadArchives()
  }, [
    hazardRevisionArchiveQueryParams.page,
    hazardRevisionArchiveQueryParams.page_size,
    archiveStatusFilter,
    activeTab,
  ])

  const handleArchiveSearch = () => {
    setHazardRevisionArchiveQueryParams({ page: 1 })
    loadArchives()
  }

  const handleAddArchive = () => {
    setEditingArchive(null)
    archiveForm.resetFields()
    setArchiveModalVisible(true)
  }

  const handleEditArchive = (archive: HazardRevisionArchive) => {
    setEditingArchive(archive)
    archiveEditForm.setFieldsValue({
      ...archive,
      identification_date: archive.identification_date
        ? dayjs(archive.identification_date)
        : undefined,
    })
    setArchiveModalVisible(true)
  }

  const handleDeleteArchive = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个存档吗？',
      onOk: async () => {
        try {
          const response = await deleteHazardRevisionArchive(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeHazardRevisionArchive(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleArchiveSubmit = async () => {
    try {
      const values = editingArchive
        ? await archiveEditForm.validateFields()
        : await archiveForm.validateFields()

      const formattedValues = {
        ...values,
        identification_date: values.identification_date
          ? values.identification_date.toISOString()
          : undefined,
      }

      if (editingArchive) {
        const response = await updateHazardRevisionArchive(editingArchive.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          updateArchiveInStore(editingArchive.id, response.data)
          setArchiveModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createHazardRevisionArchive(
          formattedValues as unknown as HazardRevisionArchiveFormData
        )
        if (response.code === 200) {
          message.success('创建成功')
          addHazardRevisionArchive(response.data)
          setArchiveModalVisible(false)
          archiveForm.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const archiveColumns: ColumnsType<HazardRevisionArchive> = [
    {
      title: '操规名称',
      dataIndex: 'regulation_name',
      key: 'regulation_name',
      width: 200,
      ellipsis: true,
    },
    {
      title: '文档',
      dataIndex: 'hazard_document_path',
      key: 'hazard_document_path',
      width: 200,
      ellipsis: true,
      render: (path: string, record) =>
        path ? (
          <Space size="small">
            <FileTextOutlined className="text-blue-500" />
            <Text ellipsis style={{ maxWidth: 120 }}>
              {record.hazard_document_original_name || path}
            </Text>
          </Space>
        ) : (
          <Tag color="default">未上传</Tag>
        ),
    },
    {
      title: '辨识日期',
      dataIndex: 'identification_date',
      key: 'identification_date',
      width: 120,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => {
        const option = ARCHIVE_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status}</Tag>
      },
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 150,
      ellipsis: true,
      render: (notes: string) => notes || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEditArchive(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDeleteArchive(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  // ============ Render ============

  const tabItems = [
    {
      key: 'records',
      label: '辨识记录',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={5}>
              <Input
                placeholder="搜索辨识编号/操规名称"
                prefix={<SearchOutlined />}
                value={recordSearchText}
                onChange={(e) => setRecordSearchText(e.target.value)}
                onPressEnter={handleRecordSearch}
              />
            </Col>
            <Col span={3}>
              <Select
                placeholder="辨识类型"
                allowClear
                value={recordTypeFilter}
                onChange={(value) => {
                  setRecordTypeFilter(value)
                  setHazardRevisionRecordQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={IDENTIFICATION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Col>
            <Col span={3}>
              <Select
                placeholder="审核状态"
                allowClear
                value={recordOpinionFilter}
                onChange={(value) => {
                  setRecordOpinionFilter(value)
                  setHazardRevisionRecordQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={REVIEW_OPINION_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleRecordSearch}>
                查询
              </Button>
            </Col>
          </Row>

          <Table
            columns={recordColumns}
            dataSource={hazardRevisionRecords}
            rowKey="id"
            loading={recordLoading}
            scroll={{ x: 1300 }}
            pagination={{
              current: hazardRevisionRecordQueryParams.page,
              pageSize: hazardRevisionRecordQueryParams.page_size,
              total: hazardRevisionRecordTotal,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (page, pageSize) => {
                setHazardRevisionRecordQueryParams({ page, page_size: pageSize })
              },
            }}
          />
        </>
      ),
    },
    {
      key: 'archives',
      label: '辨识存档',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={5}>
              <Input
                placeholder="搜索操规名称"
                prefix={<SearchOutlined />}
                value={archiveSearchText}
                onChange={(e) => setArchiveSearchText(e.target.value)}
                onPressEnter={handleArchiveSearch}
              />
            </Col>
            <Col span={3}>
              <Select
                placeholder="状态"
                allowClear
                value={archiveStatusFilter}
                onChange={(value) => {
                  setArchiveStatusFilter(value)
                  setHazardRevisionArchiveQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={ARCHIVE_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleArchiveSearch}>
                查询
              </Button>
            </Col>
          </Row>

          <Table
            columns={archiveColumns}
            dataSource={hazardRevisionArchives}
            rowKey="id"
            loading={archiveLoading}
            scroll={{ x: 900 }}
            pagination={{
              current: hazardRevisionArchiveQueryParams.page,
              pageSize: hazardRevisionArchiveQueryParams.page_size,
              total: hazardRevisionArchiveTotal,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (page, pageSize) => {
                setHazardRevisionArchiveQueryParams({ page, page_size: pageSize })
              },
            }}
          />
        </>
      ),
    },
  ]

  return (
    <div className="p-6">
      <Card
        title="危险源辨识修订"
        extra={
          activeTab === 'records' ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddRecord}>
              新建辨识记录
            </Button>
          ) : (
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddArchive}>
              新建存档
            </Button>
          )
        }
      >
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key)}
          items={tabItems}
        />
      </Card>

      {/* Record Modal */}
      <Modal
        title={editingRecord ? '编辑辨识记录' : '新建辨识记录'}
        open={recordModalVisible}
        onOk={handleRecordSubmit}
        onCancel={() => setRecordModalVisible(false)}
        width={650}
        okText="确认"
        cancelText="取消"
      >
        <Form
          form={editingRecord ? recordEditForm : recordForm}
          layout="vertical"
          initialValues={editingRecord || undefined}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="hazard_revision_no"
                label="辨识编号"
                rules={[{ required: true, message: '请输入辨识编号' }]}
              >
                <Input placeholder="请输入辨识编号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="identification_type"
                label="辨识类型"
                rules={[{ required: true, message: '请选择辨识类型' }]}
              >
                <Select
                  options={IDENTIFICATION_TYPE_OPTIONS.map((o) => ({
                    value: o.value,
                    label: o.label,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="regulation_revision_id"
            label="关联修订记录"
          >
            <Select
              showSearch
              allowClear
              placeholder="选择关联修订记录（可选）"
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
              options={revisions.map((r) => ({
                value: r.id,
                label: `${r.revision_no} - ${r.regulation_name}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="regulation_name"
            label="操规名称"
            rules={[{ required: true, message: '请输入操规名称' }]}
          >
            <Input placeholder="请输入操规名称" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="identifier_id" label="辨识人ID">
                <Input placeholder="请输入辨识人ID" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="identifier_name" label="辨识人姓名">
                <Input placeholder="请输入辨识人姓名" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="process_change_content" label="工艺变更内容">
            <Input.TextArea rows={3} placeholder="描述工艺变更内容，用于辨识范围分析" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Archive Modal */}
      <Modal
        title={editingArchive ? '编辑存档' : '新建存档'}
        open={archiveModalVisible}
        onOk={handleArchiveSubmit}
        onCancel={() => setArchiveModalVisible(false)}
        width={550}
        okText="确认"
        cancelText="取消"
      >
        <Form
          form={editingArchive ? archiveEditForm : archiveForm}
          layout="vertical"
          initialValues={editingArchive || undefined}
        >
          <Form.Item
            name="regulation_name"
            label="操规名称"
            rules={[{ required: true, message: '请输入操规名称' }]}
          >
            <Input placeholder="请输入操规名称" />
          </Form.Item>
          <Form.Item name="hazard_document_original_name" label="文档原名">
            <Input placeholder="请输入原始文档名称" />
          </Form.Item>
          <Form.Item name="hazard_document_path" label="文档路径">
            <Input placeholder="文档存储路径" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Link to Archive Modal */}
      <Modal
        title="选择关联存档"
        open={linkModalVisible}
        onCancel={() => {
          setLinkModalVisible(false)
          setLinkingRecordId(null)
        }}
        footer={null}
        width={600}
      >
        <Table
          dataSource={archives}
          rowKey="id"
          size="small"
          pagination={false}
          columns={[
            {
              title: '操规名称',
              dataIndex: 'regulation_name',
              key: 'regulation_name',
              ellipsis: true,
            },
            {
              title: '文档',
              dataIndex: 'hazard_document_original_name',
              key: 'document',
              ellipsis: true,
              render: (name: string) => name || '-',
            },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              width: 80,
              render: (status: string) => {
                const option = ARCHIVE_STATUS_OPTIONS.find((o) => o.value === status)
                return <Tag color={option?.color}>{option?.label || status}</Tag>
              },
            },
            {
              title: '操作',
              key: 'action',
              width: 80,
              render: (_, archive) => (
                <Button
                  type="link"
                  size="small"
                  icon={<LinkOutlined />}
                  onClick={() => handleLinkToArchive(archive.id)}
                >
                  关联
                </Button>
              ),
            },
          ]}
        />
      </Modal>
    </div>
  )
}
