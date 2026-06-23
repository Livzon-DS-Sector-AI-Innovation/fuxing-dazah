'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  Upload,
  Drawer,
  message,
  Card,
  Typography,
  Tabs,
  Divider,
  Spin,
  Tooltip,
  App,
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
  ThunderboltOutlined,
  FileProtectOutlined,
  HistoryOutlined,
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
import SopGeneratorModal from '@/components/safety/SopGeneratorModal'
import {
  RevisionType,
  REVISION_TYPE_OPTIONS,
  REVISION_SCOPE_OPTIONS,
  REVIEW_OPINION_OPTIONS,
} from '@/types/safety'
import {
  actionLink,
  statusPill,
  pillSuccess,
  pillWarning,
  pillError,
  pillNeutral,
  pillInfo,
  pillPurple,
  pillDefault,
  T,
} from '@/components/safety/shared-styles'
import dayjs from 'dayjs'

const { Text } = Typography

// ── 操作链接预设 ──
const $link = actionLink('#0075de')
const $danger = actionLink('#e03131')
const $purple = actionLink('#5645d4')
const $muted = actionLink('#787671')

export default function RegulationPage() {
  const [activeTab, setActiveTab] = useState('regulations')
  const { modal } = App.useApp()

  // ========== Regulation States ==========
  const [regForm] = Form.useForm()
  const [regEditForm] = Form.useForm()
  const [regLoading, setRegLoading] = useState(false)
  const [regDrawerOpen, setRegDrawerOpen] = useState(false)
  const [editingRegulation, setEditingRegulation] = useState<OperationRegulation | null>(null)
  const [regSearchText, setRegSearchText] = useState('')
  const [positionFilter, setPositionFilter] = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<string | undefined>('reviewed,exported,draft')
  const [regSubmitting, setRegSubmitting] = useState(false)

  // ========== Revision States ==========
  const [revForm] = Form.useForm()
  const [revLoading, setRevLoading] = useState(false)
  const [revDrawerOpen, setRevDrawerOpen] = useState(false)
  const [revSearchText, setRevSearchText] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [scopeFilter, setScopeFilter] = useState<string | undefined>()
  const [opinionFilter, setOpinionFilter] = useState<string | undefined>()
  const [revSubmitting, setRevSubmitting] = useState(false)

  // AI revision states
  const [aiModalVisible, setAiModalVisible] = useState(false)
  const [aiGenerating, setAiGenerating] = useState(false)
  const [aiContent, setAiContent] = useState('')
  const [aiDocumentName, setAiDocumentName] = useState('')
  const [aiRevisionId, setAiRevisionId] = useState<string | null>(null)
  const [aiConfirming, setAiConfirming] = useState(false)
  const [scopeLoading, setScopeLoading] = useState<string | null>(null)

  const router = useRouter()

  // SOP Generator states
  const [generatorModalOpen, setGeneratorModalOpen] = useState(false)

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
        status: statusFilter,
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
  }, [regulationQueryParams.page, regulationQueryParams.page_size, positionFilter, statusFilter, activeTab])

  useEffect(() => {
    if (activeTab === 'revisions') loadRevisions()
  }, [revisionQueryParams.page, revisionQueryParams.page_size, typeFilter, scopeFilter, opinionFilter, activeTab])

  useEffect(() => {
    loadRegulationsForSelect()
  }, [])

  // ---- Regulation CRUD ----

  const handleAddRegulation = () => {
    setEditingRegulation(null)
    regForm.resetFields()
    setRegDrawerOpen(true)
  }

  const handleEditRegulation = (record: OperationRegulation) => {
    setEditingRegulation(record)
    regEditForm.setFieldsValue(record)
    setRegDrawerOpen(true)
  }

  const handleDeleteRegulation = (id: string) => {
    modal.confirm({
      title: '确认删除',
      content: '确定要删除这个操规文档吗？此操作不可撤销。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
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

  // ── SOP Generator Handlers ──

  const handleOpenGenerator = () => {
    setGeneratorModalOpen(true)
  }

  const handleSopGenerated = (result: {
    regulation_id: string
    meta: Record<string, string>
    content: string
  }) => {
    setGeneratorModalOpen(false)
    loadRegulations()
    router.push(`/safety/regulation/generator/${result.regulation_id}`)
  }

  const handleOpenEditor = (record: OperationRegulation) => {
    if (!record.content) {
      message.warning('该操规尚未生成标准化内容，请先上传旧版操规进行生成')
      return
    }
    router.push(`/safety/regulation/generator/${record.id}`)
  }

  const handleRegSubmit = async () => {
    try {
      const values = editingRegulation
        ? await regEditForm.validateFields()
        : await regForm.validateFields()
      setRegSubmitting(true)

      if (editingRegulation) {
        const response = await updateRegulation(editingRegulation.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateRegulationInStore(editingRegulation.id, response.data)
          setRegDrawerOpen(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createRegulation(values as OperationRegulationFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addRegulation(response.data)
          setRegDrawerOpen(false)
          regForm.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      // form validation error
    } finally {
      setRegSubmitting(false)
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

  const handleAddRevision = () => {
    revForm.resetFields()
    setRevDrawerOpen(true)
  }

  const handleRevSubmit = async () => {
    try {
      const values = await revForm.validateFields()
      setRevSubmitting(true)
      const response = await createRevision(values as RegulationRevisionFormData)
      if (response.code === 200) {
        message.success('创建修订记录成功')
        addRevision(response.data)
        setRevDrawerOpen(false)
        revForm.resetFields()
      } else {
        message.error(response.message || '创建失败')
      }
    } catch {
      // form validation error
    } finally {
      setRevSubmitting(false)
    }
  }

  const handleDeleteRevision = (id: string) => {
    modal.confirm({
      title: '确认删除',
      content: '确定要删除这个修订记录吗？此操作不可撤销。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
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
        loadRegulations()
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

  // ── Status rendering helpers ──

  const renderContentStatus = (status: string | undefined, content: string | undefined) => {
    if (content && status === 'reviewed') return <span style={pillPurple}>已审核</span>
    if (content && status === 'generated') return <span style={pillInfo}>已生成</span>
    if (content && status === 'exported') return <span style={pillSuccess}>已导出</span>
    if (content) return <span style={statusPill('#0891b2', '#cffafe')}>草稿</span>
    return <span style={pillDefault}>无内容</span>
  }

  const renderDocStatus = (path: string | undefined, name: string | undefined) => {
    if (path) {
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: T.slate }}>
          <FileTextOutlined style={{ color: '#0075de', fontSize: 14 }} />
          <Text ellipsis style={{ maxWidth: 120 }}>{name || path}</Text>
        </span>
      )
    }
    return <span style={pillDefault}>未上传</span>
  }

  // ========== Table Columns ==========

  const regulationColumns: ColumnsType<OperationRegulation> = [
    {
      title: '操规编号',
      dataIndex: 'regulation_no',
      key: 'regulation_no',
      width: 140,
      render: (no: string) => (
        <span style={{ fontFamily: '"JetBrains Mono", "SF Mono", monospace', fontSize: 13, color: T.slate }}>
          {no}
        </span>
      ),
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
      width: 100,
      render: (pos: string) => pos || '-',
    },
    {
      title: '文档',
      dataIndex: 'document_path',
      key: 'document_path',
      width: 170,
      ellipsis: true,
      render: (path: string, record: OperationRegulation) =>
        renderDocStatus(path, record.document_original_name),
    },
    {
      title: '内容状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string, record: OperationRegulation) =>
        renderContentStatus(status, record.content),
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 120,
      ellipsis: true,
      render: (notes: string) => notes || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 105,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 360,
      fixed: 'right',
      render: (_, record) => (
        <Space size={12}>
          <Upload {...regulationUploadProps(record.id)}>
            <span role="button" style={$muted}>
              <UploadOutlined />上传
            </span>
          </Upload>
          <span role="button" style={$link} onClick={() => handleEditRegulation(record)}>
            <EditOutlined />编辑
          </span>
          <Tooltip title="查看/新建修订记录">
            <span
              role="button"
              style={$link}
              onClick={() => {
                setActiveTab('revisions')
                setRevisionQueryParams({ page: 1 })
              }}
            >
              <AimOutlined />修订
            </span>
          </Tooltip>
          {record.content ? (
            <span role="button" style={$purple} onClick={() => handleOpenEditor(record)}>
              <EyeOutlined />查看内容
            </span>
          ) : (
            <span role="button" style={$purple} onClick={() => setGeneratorModalOpen(true)}>
              <ThunderboltOutlined />标准化生成
            </span>
          )}
          <span role="button" style={$danger} onClick={() => handleDeleteRegulation(record.id)}>
            <DeleteOutlined />删除
          </span>
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
      render: (no: string) => (
        <span style={{ fontFamily: '"JetBrains Mono", "SF Mono", monospace', fontSize: 13, color: T.slate }}>
          {no}
        </span>
      ),
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
      width: 90,
      render: (type: RevisionType) => {
        const opt = REVISION_TYPE_OPTIONS.find((o) => o.value === type)
        return (
          <span style={type === RevisionType.AI ? pillPurple : pillInfo}>
            {opt?.label || type}
          </span>
        )
      },
    },
    {
      title: '修订人',
      dataIndex: 'reviser_name',
      key: 'reviser_name',
      width: 80,
      render: (name: string) => name || '-',
    },
    {
      title: '时间',
      dataIndex: 'revision_time',
      key: 'revision_time',
      width: 100,
      render: (date: string) => (date ? dayjs(date).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '修订范围',
      dataIndex: 'revision_scope',
      key: 'revision_scope',
      width: 100,
      render: (scope: string) => {
        const opt = REVISION_SCOPE_OPTIONS.find((o) => o.value === scope)
        if (!scope) return <span style={pillDefault}>未识别</span>
        return (
          <span style={scope === 'process' ? pillWarning : pillSuccess}>
            {opt?.label || scope}
          </span>
        )
      },
    },
    {
      title: '审核',
      dataIndex: 'review_opinion',
      key: 'review_opinion',
      width: 75,
      render: (opinion: string) => {
        const opt = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
        if (!opinion) return <span style={pillDefault}>待审核</span>
        const color = opt?.color || '#787671'
        const bgMap: Record<string, string> = {
          '#52c41a': '#d9f3e1',
          '#faad14': '#ffe8d4',
          '#ff4d4f': '#fde0ec',
        }
        return <span style={statusPill(color, bgMap[color] || '#f0eeec')}>{opt?.label || opinion}</span>
      },
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 120,
      ellipsis: true,
      render: (notes: string) => notes || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      fixed: 'right',
      render: (_, record) => (
        <Space size={12}>
          {record.revision_type === RevisionType.MANUAL && !record.new_document_path && (
            <Upload {...manualUploadProps(record.id)}>
              <span role="button" style={$muted}>
                <UploadOutlined />上传修订稿
              </span>
            </Upload>
          )}

          {record.revision_type === RevisionType.AI && !record.new_document_path && (
            <span role="button" style={$purple} onClick={() => handleAIGenerate(record.id)}>
              <RobotOutlined />AI生成
            </span>
          )}

          {!record.revision_scope && (
            <span
              role="button"
              style={$link}
              onClick={() => handleIdentifyScope(record.id)}
            >
              <AimOutlined />
              {scopeLoading === record.id ? '识别中...' : '识别范围'}
            </span>
          )}

          {record.new_document_path && (
            <span role="button" style={$link}>
              <EyeOutlined />查看文档
            </span>
          )}

          <span role="button" style={$danger} onClick={() => handleDeleteRevision(record.id)}>
            <DeleteOutlined />删除
          </span>
        </Space>
      ),
    },
  ]

  // ========== Tab Items ==========

  const tabItems = [
    {
      key: 'regulations',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <FileProtectOutlined style={{ fontSize: 15 }} />
          操规列表
        </span>
      ),
      children: (
        <>
          {/* Search / Filter Bar */}
          <div
            style={{
              marginBottom: 16,
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              flexShrink: 0,
            }}
          >
            <Select
              placeholder="所属岗位"
              allowClear
              style={{ width: 130 }}
              value={positionFilter}
              onChange={(v) => {
                setPositionFilter(v)
                setRegulationQueryParams({ page: 1 })
              }}
              options={[
                { value: '操作工', label: '操作工' },
                { value: '班组长', label: '班组长' },
                { value: '技术员', label: '技术员' },
                { value: '安全员', label: '安全员' },
              ]}
            />
            <Select
              placeholder="内容状态"
              allowClear
              style={{ width: 150 }}
              value={statusFilter}
              onChange={(v) => {
                setStatusFilter(v)
                setRegulationQueryParams({ page: 1 })
              }}
              options={[
                { value: 'reviewed,exported,draft', label: '全部台账' },
                { value: 'reviewed', label: '已审核' },
                { value: 'exported', label: '已导出' },
                { value: 'draft', label: '草稿' },
                { value: 'generated', label: '已生成（未审核）' },
              ]}
            />
            <Input
              placeholder="搜索操规编号或名称"
              prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
              style={{ width: 240 }}
              value={regSearchText}
              onChange={(e) => setRegSearchText(e.target.value)}
              onPressEnter={loadRegulations}
              allowClear
            />
            <div style={{ flex: 1 }} />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddRegulation}
              style={{
                borderRadius: 8,
                height: 36,
                background: '#5645d4',
                borderColor: '#5645d4',
                fontWeight: 600,
                fontSize: 13,
                boxShadow: 'none',
              }}
            >
              新建操规
            </Button>
          </div>

          <Table
            columns={regulationColumns}
            dataSource={regulations}
            rowKey="id"
            size="small"
            loading={regLoading}
            scroll={{ x: 1160 }}
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
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <HistoryOutlined style={{ fontSize: 15 }} />
          修订记录
        </span>
      ),
      children: (
        <>
          {/* Search / Filter Bar */}
          <div
            style={{
              marginBottom: 16,
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              flexShrink: 0,
            }}
          >
            <Select
              placeholder="修订类型"
              allowClear
              style={{ width: 120 }}
              value={typeFilter}
              onChange={(v) => {
                setTypeFilter(v)
                setRevisionQueryParams({ page: 1 })
              }}
              options={REVISION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
            <Select
              placeholder="修订范围"
              allowClear
              style={{ width: 120 }}
              value={scopeFilter}
              onChange={(v) => {
                setScopeFilter(v)
                setRevisionQueryParams({ page: 1 })
              }}
              options={REVISION_SCOPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
            <Select
              placeholder="审核状态"
              allowClear
              style={{ width: 120 }}
              value={opinionFilter}
              onChange={(v) => {
                setOpinionFilter(v)
                setRevisionQueryParams({ page: 1 })
              }}
              options={REVIEW_OPINION_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
            <Input
              placeholder="搜索修订编号或操规名称"
              prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
              style={{ width: 240 }}
              value={revSearchText}
              onChange={(e) => setRevSearchText(e.target.value)}
              onPressEnter={loadRevisions}
              allowClear
            />
            <div style={{ flex: 1 }} />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddRevision}
              style={{
                borderRadius: 8,
                height: 36,
                background: '#5645d4',
                borderColor: '#5645d4',
                fontWeight: 600,
                fontSize: 13,
                boxShadow: 'none',
              }}
            >
              新建修订
            </Button>
          </div>

          <Table
            columns={revisionColumns}
            dataSource={revisions}
            rowKey="id"
            size="small"
            loading={revLoading}
            scroll={{ x: 1280 }}
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
    <div style={{ padding: '24px 28px' }}>
      {/* Page Title Header */}
      <div style={{ marginBottom: 24 }}>
        <h2
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: '#1a1a1a',
            margin: 0,
            marginBottom: 4,
            lineHeight: 1.3,
          }}
        >
          安全操规管理
        </h2>
        <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
          管理已审核的安全操作规程 · 版本修订 · AI标准化生成入口
        </p>
      </div>

      {/* Content Card */}
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          border: '1px solid #e5e3df',
          padding: '4px 24px 24px',
        }}
      >
        <Tabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} items={tabItems} />
      </div>

      {/* ═══ Regulation Drawer ═══ */}
      <Drawer
        title={editingRegulation ? '编辑操规' : '新建操规'}
        open={regDrawerOpen}
        onClose={() => setRegDrawerOpen(false)}
        width={480}
        destroyOnHidden
        extra={
          <Space>
            <Button onClick={() => setRegDrawerOpen(false)}>取消</Button>
            <Button
              type="primary"
              loading={regSubmitting}
              onClick={handleRegSubmit}
              style={{
                borderRadius: 8,
                background: '#5645d4',
                borderColor: '#5645d4',
                fontWeight: 600,
                boxShadow: 'none',
              }}
            >
              保存
            </Button>
          </Space>
        }
      >
        <Form
          form={editingRegulation ? regEditForm : regForm}
          layout="vertical"
          requiredMark="optional"
        >
          <Form.Item
            name="regulation_no"
            label="操规编号"
            rules={[{ required: true, message: '请输入操规编号' }]}
          >
            <Input placeholder="请输入操规编号" />
          </Form.Item>
          <Form.Item
            name="regulation_name"
            label="操规名称"
            rules={[{ required: true, message: '请输入操规名称' }]}
          >
            <Input placeholder="请输入操规名称" />
          </Form.Item>
          <Form.Item name="position" label="所属岗位">
            <Input placeholder="请输入所属岗位" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Drawer>

      {/* ═══ Revision Drawer ═══ */}
      <Drawer
        title="新建修订记录"
        open={revDrawerOpen}
        onClose={() => setRevDrawerOpen(false)}
        width={480}
        destroyOnHidden
        extra={
          <Space>
            <Button onClick={() => setRevDrawerOpen(false)}>取消</Button>
            <Button
              type="primary"
              loading={revSubmitting}
              onClick={handleRevSubmit}
              style={{
                borderRadius: 8,
                background: '#5645d4',
                borderColor: '#5645d4',
                fontWeight: 600,
                boxShadow: 'none',
              }}
            >
              保存
            </Button>
          </Space>
        }
      >
        <Form form={revForm} layout="vertical" requiredMark="optional">
          <Form.Item
            name="revision_no"
            label="修订编号"
            rules={[{ required: true, message: '请输入修订编号' }]}
          >
            <Input placeholder="请输入修订编号" />
          </Form.Item>
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
          <Form.Item name="reviser" label="修订人ID">
            <Input placeholder="请输入修订人ID" />
          </Form.Item>
          <Form.Item name="reviser_name" label="修订人姓名">
            <Input placeholder="请输入修订人姓名" />
          </Form.Item>
          <Form.Item name="revision_opinion" label="修订意见">
            <Input.TextArea rows={4} placeholder="描述修订意见，AI修订模式将基于此意见生成修订稿" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Drawer>

      {/* ═══ AI Generation Result Modal ═══ */}
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
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '48px 0' }}>
            <Spin size="large" />
            <Text style={{ marginTop: 16, color: '#787671' }}>AI 正在生成修订稿...</Text>
          </div>
        ) : aiContent ? (
          <>
            <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8, color: '#1a1a1a' }}>文档名称</div>
            <Input
              value={aiDocumentName}
              onChange={(e) => setAiDocumentName(e.target.value)}
              placeholder="修订稿文件名"
            />
            <Divider style={{ margin: '16px 0' }} />
            <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8, color: '#1a1a1a' }}>生成内容预览</div>
            <div
              style={{
                background: '#fafaf9',
                border: '1px solid #e5e3df',
                borderRadius: 8,
                padding: 16,
                maxHeight: 400,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                fontSize: 13,
                lineHeight: 1.6,
                color: '#37352f',
              }}
            >
              {aiContent}
            </div>
          </>
        ) : null}
      </Modal>

      {/* ── SOP Generator Modal ── */}
      <SopGeneratorModal
        open={generatorModalOpen}
        onClose={() => setGeneratorModalOpen(false)}
        onGenerated={handleSopGenerated}
      />

    </div>
  )
}
