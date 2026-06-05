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
  Divider,
  Spin,
  Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  UploadOutlined,
  FileTextOutlined,
  RobotOutlined,
  AimOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getRegulations,
  createRegulation,
  updateRegulation,
  deleteRegulation,
  uploadRegulationDocument,
  getRevisions,
  createRevision,
  deleteRevision,
  manualRevisionComplete,
  aiRevisionGenerate,
  aiRevisionConfirm,
  identifyRevisionScope,
} from '@/actions/safety'
import type {
  OperationRegulation,
  OperationRegulationFormData,
  RegulationRevision,
  RegulationRevisionFormData,
} from '@/types/safety'
import {
  RevisionType,
  REVISION_TYPE_OPTIONS,
  REVISION_SCOPE_OPTIONS,
  REVIEW_OPINION_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

export default function RegulationPage() {
  const [activeTab, setActiveTab] = useState('regulations')

  // ========== Regulation States ==========
  const [regForm] = Form.useForm()
  const [regEditForm] = Form.useForm()
  const [regLoading, setRegLoading] = useState(false)
  const [regModalVisible, setRegModalVisible] = useState(false)
  const [editingRegulation, setEditingRegulation] = useState<OperationRegulation | null>(null)
  const [regSearchText, setRegSearchText] = useState('')
  const [positionFilter, setPositionFilter] = useState<string | undefined>()

  // ========== Revision States ==========
  const [revForm] = Form.useForm()
  const [revLoading, setRevLoading] = useState(false)
  const [revModalVisible, setRevModalVisible] = useState(false)
  const [revSearchText, setRevSearchText] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [scopeFilter, setScopeFilter] = useState<string | undefined>()
  const [opinionFilter, setOpinionFilter] = useState<string | undefined>()

  // AI revision states
  const [aiModalVisible, setAiModalVisible] = useState(false)
  const [aiGenerating, setAiGenerating] = useState(false)
  const [aiContent, setAiContent] = useState('')
  const [aiDocumentName, setAiDocumentName] = useState('')
  const [aiRevisionId, setAiRevisionId] = useState<string | null>(null)
  const [aiConfirming, setAiConfirming] = useState(false)
  const [scopeLoading, setScopeLoading] = useState<string | null>(null)

  // Regulations cache for revision create form
  const [regulationsForSelect, setRegulationsForSelect] = useState<OperationRegulation[]>([])

  // ========== Store ==========
  const {
    regulations,
    regulationTotal,
    regulationQueryParams,
    setRegulations,
    setRegulationTotal,
    setRegulationQueryParams,
    addRegulation,
    updateRegulation: updateRegulationInStore,
    removeRegulation,

    revisions,
    revisionTotal,
    revisionQueryParams,
    setRevisions,
    setRevisionTotal,
    setRevisionQueryParams,
    addRevision,
    updateRevision: updateRevisionInStore,
    removeRevision,
  } = useSafetyStore()

  // ========== Regulation Handlers ==========

  const loadRegulations = async () => {
    setRegLoading(true)
    try {
      const response = await getRegulations({
        ...regulationQueryParams,
        keyword: regSearchText || undefined,
        position: positionFilter,
      })
      if (response.code === 200) {
        setRegulations(response.data)
        setRegulationTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载操规列表失败')
    } finally {
      setRegLoading(false)
    }
  }

  const loadRevisions = async () => {
    setRevLoading(true)
    try {
      const response = await getRevisions({
        ...revisionQueryParams,
        revision_type: typeFilter,
        revision_scope: scopeFilter,
        review_opinion: opinionFilter,
      })
      if (response.code === 200) {
        setRevisions(response.data)
        setRevisionTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载修订记录失败')
    } finally {
      setRevLoading(false)
    }
  }

  const loadRegulationsForSelect = async () => {
    try {
      const response = await getRegulations({ page: 1, page_size: 500 })
      if (response.code === 200) {
        setRegulationsForSelect(response.data)
      }
    } catch {
      // silent
    }
  }

  useEffect(() => {
    if (activeTab === 'regulations') loadRegulations()
  }, [regulationQueryParams.page, regulationQueryParams.page_size, positionFilter, activeTab])

  useEffect(() => {
    if (activeTab === 'revisions') loadRevisions()
  }, [revisionQueryParams.page, revisionQueryParams.page_size, typeFilter, scopeFilter, opinionFilter, activeTab])

  useEffect(() => {
    loadRegulationsForSelect()
  }, [])

  // ---- Regulation CRUD ----

  const handleRegSearch = () => {
    setRegulationQueryParams({ page: 1 })
    loadRegulations()
  }

  const handleAddRegulation = () => {
    setEditingRegulation(null)
    regForm.resetFields()
    setRegModalVisible(true)
  }

  const handleEditRegulation = (record: OperationRegulation) => {
    setEditingRegulation(record)
    regEditForm.setFieldsValue(record)
    setRegModalVisible(true)
  }

  const handleDeleteRegulation = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个操规文档吗？',
      onOk: async () => {
        try {
          const response = await deleteRegulation(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeRegulation(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleRegSubmit = async () => {
    try {
      const values = editingRegulation
        ? await regEditForm.validateFields()
        : await regForm.validateFields()

      if (editingRegulation) {
        const response = await updateRegulation(editingRegulation.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateRegulationInStore(editingRegulation.id, response.data)
          setRegModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createRegulation(values as OperationRegulationFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addRegulation(response.data)
          setRegModalVisible(false)
          regForm.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleUploadDoc = async (id: string, file: File) => {
    try {
      const response = await uploadRegulationDocument(id, file)
      if (response.code === 200) {
        message.success('文档上传成功')
        loadRegulations()
      } else {
        message.error(response.message || '上传失败')
      }
    } catch {
      message.error('上传失败')
    }
  }

  const regulationUploadProps = (id: string): UploadProps => ({
    showUploadList: false,
    beforeUpload: async (file) => {
      await handleUploadDoc(id, file)
      return false
    },
  })

  // ---- Revision Handlers ----

  const handleRevSearch = () => {
    setRevisionQueryParams({ page: 1 })
    loadRevisions()
  }

  const handleAddRevision = () => {
    revForm.resetFields()
    setRevModalVisible(true)
  }

  const handleRevSubmit = async () => {
    try {
      const values = await revForm.validateFields()
      const response = await createRevision(values as RegulationRevisionFormData)
      if (response.code === 200) {
        message.success('创建修订记录成功')
        addRevision(response.data)
        setRevModalVisible(false)
        revForm.resetFields()
      } else {
        message.error(response.message || '创建失败')
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleDeleteRevision = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个修订记录吗？',
      onOk: async () => {
        try {
          const response = await deleteRevision(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeRevision(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  // Manual revision upload
  const handleManualUpload = async (revisionId: string, file: File) => {
    try {
      const response = await manualRevisionComplete(revisionId, file)
      if (response.code === 200) {
        message.success('人工修订完成，已自动审核通过')
        loadRevisions()
        loadRegulations() // refresh regulation list to reflect new document
      } else {
        message.error(response.message || '修订失败')
      }
    } catch {
      message.error('修订失败')
    }
  }

  const manualUploadProps = (revisionId: string): UploadProps => ({
    showUploadList: false,
    beforeUpload: async (file) => {
      await handleManualUpload(revisionId, file)
      return false
    },
  })

  // AI revision generate
  const handleAIGenerate = async (revisionId: string) => {
    setAiRevisionId(revisionId)
    setAiModalVisible(true)
    setAiGenerating(true)
    setAiContent('')
    setAiDocumentName(`修订稿_${dayjs().format('YYYYMMDDHHmmss')}.docx`)
    try {
      const response = await aiRevisionGenerate(revisionId)
      if (response.code === 200) {
        setAiContent(response.data.generated_content)
      } else {
        message.error(response.message || 'AI生成失败')
        setAiModalVisible(false)
      }
    } catch {
      message.error('AI生成失败')
      setAiModalVisible(false)
    } finally {
      setAiGenerating(false)
    }
  }

  const handleAIConfirm = async () => {
    if (!aiRevisionId || !aiContent) return
    setAiConfirming(true)
    try {
      const response = await aiRevisionConfirm(aiRevisionId, aiContent, aiDocumentName || undefined)
      if (response.code === 200) {
        message.success('AI修订确认成功')
        setAiModalVisible(false)
        setAiContent('')
        setAiRevisionId(null)
        loadRevisions()
        loadRegulations()
      } else {
        message.error(response.message || '确认失败')
      }
    } catch {
      message.error('确认失败')
    } finally {
      setAiConfirming(false)
    }
  }

  // Scope identification
  const handleIdentifyScope = async (revisionId: string) => {
    setScopeLoading(revisionId)
    try {
      const response = await identifyRevisionScope(revisionId)
      if (response.code === 200) {
        message.success('修订范围识别完成')
        loadRevisions()
      } else {
        message.error(response.message || '识别失败')
      }
    } catch {
      message.error('识别失败')
    } finally {
      setScopeLoading(null)
    }
  }

  const getOpinionColor = (opinion: string) => {
    const opt = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
    return opt?.color || 'default'
  }

  const getOpinionLabel = (opinion: string) => {
    const opt = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
    return opt?.label || opinion
  }

  // ========== Table Columns ==========

  const regulationColumns: ColumnsType<OperationRegulation> = [
    {
      title: '操规编号',
      dataIndex: 'regulation_no',
      key: 'regulation_no',
      width: 140,
    },
    {
      title: '操规名称',
      dataIndex: 'regulation_name',
      key: 'regulation_name',
      width: 200,
      ellipsis: true,
    },
    {
      title: '所属岗位',
      dataIndex: 'position',
      key: 'position',
      width: 110,
      render: (pos: string) => pos || '-',
    },
    {
      title: '文档',
      dataIndex: 'document_path',
      key: 'document_path',
      width: 180,
      ellipsis: true,
      render: (path: string, record) =>
        path ? (
          <Space size="small">
            <FileTextOutlined className="text-blue-500" />
            <Text ellipsis style={{ maxWidth: 100 }}>
              {record.document_original_name || path}
            </Text>
          </Space>
        ) : (
          <Tag color="default">未上传</Tag>
        ),
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 140,
      ellipsis: true,
      render: (notes: string) => notes || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 110,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 260,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          <Upload {...regulationUploadProps(record.id)}>
            <Button type="link" size="small" icon={<UploadOutlined />}>
              上传
            </Button>
          </Upload>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEditRegulation(record)}
          >
            编辑
          </Button>
          <Tooltip title="查看/新建修订记录">
            <Button
              type="link"
              size="small"
              icon={<AimOutlined />}
              onClick={() => {
                setActiveTab('revisions')
                setRevisionQueryParams({ page: 1 })
              }}
            >
              修订
            </Button>
          </Tooltip>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDeleteRegulation(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const revisionColumns: ColumnsType<RegulationRevision> = [
    {
      title: '修订编号',
      dataIndex: 'revision_no',
      key: 'revision_no',
      width: 140,
    },
    {
      title: '操规名称',
      dataIndex: 'regulation_name',
      key: 'regulation_name',
      width: 180,
      ellipsis: true,
    },
    {
      title: '修订类型',
      dataIndex: 'revision_type',
      key: 'revision_type',
      width: 95,
      render: (type: RevisionType) => {
        const opt = REVISION_TYPE_OPTIONS.find((o) => o.value === type)
        return (
          <Tag color={type === RevisionType.AI ? 'purple' : 'blue'}>{opt?.label || type}</Tag>
        )
      },
    },
    {
      title: '修订人',
      dataIndex: 'reviser_name',
      key: 'reviser_name',
      width: 90,
      render: (name: string) => name || '-',
    },
    {
      title: '时间',
      dataIndex: 'revision_time',
      key: 'revision_time',
      width: 105,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '修订范围',
      dataIndex: 'revision_scope',
      key: 'revision_scope',
      width: 105,
      render: (scope: string) => {
        const opt = REVISION_SCOPE_OPTIONS.find((o) => o.value === scope)
        return scope ? (
          <Tag color={scope === 'process' ? 'orange' : 'green'}>{opt?.label || scope}</Tag>
        ) : (
          <Tag color="default">未识别</Tag>
        )
      },
    },
    {
      title: '审核',
      dataIndex: 'review_opinion',
      key: 'review_opinion',
      width: 80,
      render: (opinion: string) => (
        <Tag color={getOpinionColor(opinion)}>{getOpinionLabel(opinion)}</Tag>
      ),
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 130,
      ellipsis: true,
      render: (notes: string) => notes || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 320,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {record.revision_type === RevisionType.MANUAL && !record.new_document_path && (
            <Upload {...manualUploadProps(record.id)}>
              <Button type="link" size="small" icon={<UploadOutlined />}>
                上传修订稿
              </Button>
            </Upload>
          )}

          {record.revision_type === RevisionType.AI && !record.new_document_path && (
            <Button
              type="link"
              size="small"
              icon={<RobotOutlined />}
              onClick={() => handleAIGenerate(record.id)}
              style={{ color: '#722ed1' }}
            >
              AI生成
            </Button>
          )}

          {!record.revision_scope && (
            <Button
              type="link"
              size="small"
              icon={<AimOutlined />}
              loading={scopeLoading === record.id}
              onClick={() => handleIdentifyScope(record.id)}
            >
              识别范围
            </Button>
          )}

          {record.new_document_path && (
            <Button type="link" size="small" icon={<EyeOutlined />}>
              查看文档
            </Button>
          )}

          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDeleteRevision(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  // ========== Tab Items ==========

  const tabItems = [
    {
      key: 'regulations',
      label: '操规列表',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={5}>
              <Input
                placeholder="搜索编号/名称"
                prefix={<SearchOutlined />}
                value={regSearchText}
                onChange={(e) => setRegSearchText(e.target.value)}
                onPressEnter={handleRegSearch}
              />
            </Col>
            <Col span={4}>
              <Select
                placeholder="所属岗位"
                allowClear
                value={positionFilter}
                onChange={(v) => {
                  setPositionFilter(v)
                  setRegulationQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={[
                  { value: '操作工', label: '操作工' },
                  { value: '班组长', label: '班组长' },
                  { value: '技术员', label: '技术员' },
                  { value: '安全员', label: '安全员' },
                ]}
              />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleRegSearch}>
                查询
              </Button>
            </Col>
          </Row>

          <Table
            columns={regulationColumns}
            dataSource={regulations}
            rowKey="id"
            loading={regLoading}
            scroll={{ x: 1100 }}
            pagination={{
              current: regulationQueryParams.page,
              pageSize: regulationQueryParams.page_size,
              total: regulationTotal,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (page, pageSize) => setRegulationQueryParams({ page, page_size: pageSize }),
            }}
          />
        </>
      ),
    },
    {
      key: 'revisions',
      label: '修订记录',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={5}>
              <Input
                placeholder="搜索修订编号/操规名称"
                prefix={<SearchOutlined />}
                value={revSearchText}
                onChange={(e) => setRevSearchText(e.target.value)}
                onPressEnter={handleRevSearch}
              />
            </Col>
            <Col span={3}>
              <Select
                placeholder="修订类型"
                allowClear
                value={typeFilter}
                onChange={(v) => {
                  setTypeFilter(v)
                  setRevisionQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={REVISION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Col>
            <Col span={3}>
              <Select
                placeholder="修订范围"
                allowClear
                value={scopeFilter}
                onChange={(v) => {
                  setScopeFilter(v)
                  setRevisionQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={REVISION_SCOPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Col>
            <Col span={3}>
              <Select
                placeholder="审核状态"
                allowClear
                value={opinionFilter}
                onChange={(v) => {
                  setOpinionFilter(v)
                  setRevisionQueryParams({ page: 1 })
                }}
                style={{ width: '100%' }}
                options={REVIEW_OPINION_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleRevSearch}>
                查询
              </Button>
            </Col>
          </Row>

          <Table
            columns={revisionColumns}
            dataSource={revisions}
            rowKey="id"
            loading={revLoading}
            scroll={{ x: 1350 }}
            pagination={{
              current: revisionQueryParams.page,
              pageSize: revisionQueryParams.page_size,
              total: revisionTotal,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (page, pageSize) => setRevisionQueryParams({ page, page_size: pageSize }),
            }}
          />
        </>
      ),
    },
  ]

  // ========== Render ==========

  return (
    <div className="p-6">
      <Card
        title="安全操规管理"
        extra={
          activeTab === 'regulations' ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddRegulation}>
              新建操规
            </Button>
          ) : (
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddRevision}>
              新建修订
            </Button>
          )
        }
      >
        <Tabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} items={tabItems} />
      </Card>

      {/* Regulation Modal */}
      <Modal
        title={editingRegulation ? '编辑操规' : '新建操规'}
        open={regModalVisible}
        onOk={handleRegSubmit}
        onCancel={() => setRegModalVisible(false)}
        width={600}
        okText="确认"
        cancelText="取消"
      >
        <Form
          form={editingRegulation ? regEditForm : regForm}
          layout="vertical"
          initialValues={editingRegulation || undefined}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="regulation_no"
                label="操规编号"
                rules={[{ required: true, message: '请输入操规编号' }]}
              >
                <Input placeholder="请输入操规编号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="regulation_name"
                label="操规名称"
                rules={[{ required: true, message: '请输入操规名称' }]}
              >
                <Input placeholder="请输入操规名称" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="position" label="所属岗位">
            <Input placeholder="请输入所属岗位" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Revision Create Modal */}
      <Modal
        title="新建修订记录"
        open={revModalVisible}
        onOk={handleRevSubmit}
        onCancel={() => setRevModalVisible(false)}
        width={600}
        okText="确认"
        cancelText="取消"
      >
        <Form form={revForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="revision_no"
                label="修订编号"
                rules={[{ required: true, message: '请输入修订编号' }]}
              >
                <Input placeholder="请输入修订编号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="revision_type"
                label="修订类型"
                rules={[{ required: true, message: '请选择修订类型' }]}
              >
                <Select
                  options={REVISION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  placeholder="人工修订 / AI修订"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="regulation_id"
            label="关联操规"
            rules={[{ required: true, message: '请选择关联操规' }]}
          >
            <Select
              showSearch
              placeholder="请选择操规"
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
              options={regulationsForSelect.map((r) => ({
                value: r.id,
                label: `${r.regulation_no} - ${r.regulation_name}`,
              }))}
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="reviser" label="修订人ID">
                <Input placeholder="请输入修订人ID" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="reviser_name" label="修订人姓名">
                <Input placeholder="请输入修订人姓名" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="revision_opinion" label="修订意见">
            <Input.TextArea rows={4} placeholder="描述修订意见，AI修订模式将基于此意见生成修订稿" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* AI Generation Result Modal */}
      <Modal
        title="AI 修订生成结果"
        open={aiModalVisible}
        onOk={handleAIConfirm}
        onCancel={() => {
          setAiModalVisible(false)
          setAiContent('')
          setAiRevisionId(null)
        }}
        width={800}
        okText="确认保存"
        cancelText="取消"
        confirmLoading={aiConfirming}
        okButtonProps={{ disabled: !aiContent || aiGenerating }}
      >
        {aiGenerating ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Spin size="large" />
            <Text className="mt-4 text-gray-500">AI 正在生成修订稿...</Text>
          </div>
        ) : aiContent ? (
          <>
            <div className="text-sm font-medium mb-2">文档名称：</div>
            <Input
              value={aiDocumentName}
              onChange={(e) => setAiDocumentName(e.target.value)}
              placeholder="修订稿文件名"
              className="mb-4"
            />
            <Divider />
            <div className="text-sm font-medium mb-2">生成内容预览：</div>
            <div
              className="bg-gray-50 p-4 rounded-lg max-h-96 overflow-auto whitespace-pre-wrap text-sm"
              style={{ border: '1px solid #f0f0f0' }}
            >
              {aiContent}
            </div>
          </>
        ) : null}
      </Modal>
    </div>
  )
}
