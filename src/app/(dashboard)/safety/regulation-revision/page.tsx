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
  Divider,
  Spin,
  Descriptions,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  DeleteOutlined,
  UploadOutlined,
  RobotOutlined,
  CheckCircleOutlined,
  AimOutlined,
  EyeOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getRevisions,
  createRevision,
  updateRevision,
  deleteRevision,
  manualRevisionComplete,
  aiRevisionGenerate,
  aiRevisionConfirm,
  identifyRevisionScope,
  getRegulations,
} from '@/actions/safety'
import type {
  RegulationRevision,
  RegulationRevisionFormData,
  OperationRegulation,
} from '@/types/safety'
import {
  RevisionType,
  REVISION_TYPE_OPTIONS,
  REVISION_SCOPE_OPTIONS,
  REVIEW_OPINION_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text, Paragraph } = Typography

export default function RegulationRevisionPage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [searchText, setSearchText] = useState('')
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

  // Scope identification state
  const [scopeLoading, setScopeLoading] = useState<string | null>(null)

  // Regulations list for create form
  const [regulations, setRegulations] = useState<OperationRegulation[]>([])

  const {
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

  const loadData = async () => {
    setLoading(true)
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
      setLoading(false)
    }
  }

  const loadRegulations = async () => {
    try {
      const response = await getRegulations({ page: 1, page_size: 500 })
      if (response.code === 200) {
        setRegulations(response.data)
      }
    } catch {
      // silent
    }
  }

  useEffect(() => {
    loadData()
  }, [
    revisionQueryParams.page,
    revisionQueryParams.page_size,
    typeFilter,
    scopeFilter,
    opinionFilter,
  ])

  useEffect(() => {
    loadRegulations()
  }, [])

  const handleSearch = () => {
    setRevisionQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    form.resetFields()
    setModalVisible(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const response = await createRevision(values as RegulationRevisionFormData)
      if (response.code === 200) {
        message.success('创建修订记录成功')
        addRevision(response.data)
        setModalVisible(false)
        form.resetFields()
      } else {
        message.error(response.message || '创建失败')
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleDelete = (id: string) => {
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

  // Manual revision: upload document to complete
  const handleManualUpload = async (revisionId: string, file: File) => {
    try {
      const response = await manualRevisionComplete(revisionId, file)
      if (response.code === 200) {
        message.success('人工修订完成，已自动审核通过')
        loadData()
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

  // AI revision: generate
  const handleAIGenerate = async (revisionId: string) => {
    setAiRevisionId(revisionId)
    setAiModalVisible(true)
    setAiGenerating(true)
    setAiContent('')
    setAiDocumentName('')
    try {
      const response = await aiRevisionGenerate(revisionId)
      if (response.code === 200) {
        setAiContent(response.data.generated_content)
        setAiDocumentName(`修订稿_${dayjs().format('YYYYMMDDHHmmss')}.docx`)
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

  // AI revision: confirm
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
        loadData()
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
        loadData()
      } else {
        message.error(response.message || '识别失败')
      }
    } catch {
      message.error('识别失败')
    } finally {
      setScopeLoading(null)
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

  const columns: ColumnsType<RegulationRevision> = [
    {
      title: '修订编号',
      dataIndex: 'revision_no',
      key: 'revision_no',
      width: 150,
    },
    {
      title: '操规名称',
      dataIndex: 'regulation_name',
      key: 'regulation_name',
      width: 200,
      ellipsis: true,
    },
    {
      title: '修订类型',
      dataIndex: 'revision_type',
      key: 'revision_type',
      width: 100,
      render: (type: RevisionType) => {
        const option = REVISION_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag color={type === RevisionType.AI ? 'purple' : 'blue'}>{option?.label || type}</Tag>
      },
    },
    {
      title: '修订人',
      dataIndex: 'reviser_name',
      key: 'reviser_name',
      width: 100,
      render: (name: string) => name || '-',
    },
    {
      title: '修订时间',
      dataIndex: 'revision_time',
      key: 'revision_time',
      width: 120,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '修订范围',
      dataIndex: 'revision_scope',
      key: 'revision_scope',
      width: 120,
      render: (scope: string) => {
        const option = REVISION_SCOPE_OPTIONS.find((o) => o.value === scope)
        return scope ? (
          <Tag color={scope === 'process' ? 'orange' : 'green'}>{option?.label || scope}</Tag>
        ) : (
          <Tag color="default">未识别</Tag>
        )
      },
    },
    {
      title: '审核状态',
      dataIndex: 'review_opinion',
      key: 'review_opinion',
      width: 100,
      render: (opinion: string) => (
        <Tag color={getReviewOpinionColor(opinion)}>{getReviewOpinionLabel(opinion)}</Tag>
      ),
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
      width: 340,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {/* Manual revision: upload to complete */}
          {record.revision_type === RevisionType.MANUAL && !record.new_document_path && (
            <Upload {...manualUploadProps(record.id)}>
              <Button type="link" size="small" icon={<UploadOutlined />}>
                上传修订稿
              </Button>
            </Upload>
          )}

          {/* AI revision: generate + confirm */}
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

          {/* Scope identification */}
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

          {/* View document if exists */}
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
            onClick={() => handleDelete(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="p-6">
      <Card
        title="操规修订管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建修订
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索修订编号/操规名称"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="修订类型"
              allowClear
              value={typeFilter}
              onChange={(value) => {
                setTypeFilter(value)
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
              onChange={(value) => {
                setScopeFilter(value)
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
              onChange={(value) => {
                setOpinionFilter(value)
                setRevisionQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={REVIEW_OPINION_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={3}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
              查询
            </Button>
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={revisions}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: revisionQueryParams.page,
            pageSize: revisionQueryParams.page_size,
            total: revisionTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setRevisionQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      {/* Create Revision Modal */}
      <Modal
        title="新建修订记录"
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText="确认"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
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
                  placeholder="人工修订 或 AI修订"
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
              options={regulations.map((r) => ({
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
            <Input.TextArea rows={4} placeholder="请输入修订意见，AI修订模式将基于此意见生成修订稿" />
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
            <Descriptions column={1} size="small" className="mb-4">
              <Descriptions.Item label="文档名称">
                <Input
                  value={aiDocumentName}
                  onChange={(e) => setAiDocumentName(e.target.value)}
                  placeholder="修订稿文件名"
                />
              </Descriptions.Item>
            </Descriptions>
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
