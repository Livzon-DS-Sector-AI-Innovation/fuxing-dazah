'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Form,
  Input,
  DatePicker,
  Select,
  Upload,
  Button,
  Space,
  Card,
  Typography,
  Row,
  Col,
  Divider,
  Avatar,
} from 'antd'
import {
  ThunderboltOutlined,
  SaveOutlined,
  InboxOutlined,
  SearchOutlined,
  CameraOutlined,
} from '@ant-design/icons'
import {
  INSPECTION_CATEGORY_OPTIONS,
  INSPECTOR_DEPARTMENT_OPTIONS,
} from '@/types/safety'
import { getCurrentUser } from '@/actions/auth'
import dayjs from 'dayjs'

const { TextArea } = Input
const { Text } = Typography
const { Dragger } = Upload

interface UserOption {
  value: string   // user UUID
  label: string   // "姓名 - 部门"
}

export interface InspectionFormValues {
  inspection_category?: string
  discovered_by?: string       // user UUID (person field)
  discovered_by_name?: string  // display name
  inspector_department?: string
  department?: string
  discovered_at?: string
  description?: string
}

interface Props {
  initialValues?: InspectionFormValues
  loading: boolean
  onSubmit: (values: InspectionFormValues, files: File[]) => Promise<void>
  onSaveDraft: (values: InspectionFormValues, files: File[]) => Promise<void>
}

export default function HazardInspectionForm({
  initialValues,
  loading,
  onSubmit,
  onSaveDraft,
}: Props) {
  const [form] = Form.useForm<InspectionFormValues>()
  const [fileList, setFileList] = useState<any[]>([])

  // ── 人员搜索状态 ──
  const [userOptions, setUserOptions] = useState<UserOption[]>([])
  const [userSearchLoading, setUserSearchLoading] = useState(false)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const handleUserSearch = useCallback((keyword: string) => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!keyword || keyword.length < 1) {
      setUserOptions([])
      return
    }
    searchTimerRef.current = setTimeout(async () => {
      setUserSearchLoading(true)
      try {
        const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
        const params = new URLSearchParams({ keyword, limit: '50' })
        const resp = await fetch(`${API_BASE}/api/v1/identity/personnel?${params}`)
        if (resp.ok) {
          const json = await resp.json()
          const items = (json.data?.items ?? []) as Record<string, unknown>[]
          setUserOptions(items.map((u) => ({
            value: String(u.id),
            label: `${String(u.name)} - ${String(u.department || '未知部门')}`,
          })))
        }
      } catch {
        // 静默失败
      } finally {
        setUserSearchLoading(false)
      }
    }, 300)
  }, [])

  // 回填草稿数据
  useEffect(() => {
    if (initialValues) {
      form.setFieldsValue({
        inspection_category: initialValues.inspection_category,
        inspector_department: initialValues.inspector_department
          ? initialValues.inspector_department.split(/[,，]/).filter(Boolean)
          : undefined,
        discovered_by: initialValues.discovered_by || undefined,
        discovered_by_name: initialValues.discovered_by_name,
        department: initialValues.department,
        description: initialValues.description,
        discovered_at: initialValues.discovered_at
          ? dayjs(initialValues.discovered_at)
          : undefined,
      } as any)
      // 回填时预填当前用户到选项列表，确保 Select 正确显示
      if (initialValues.discovered_by && initialValues.discovered_by_name) {
        setUserOptions([{
          value: initialValues.discovered_by,
          label: `${initialValues.discovered_by_name} - ${initialValues.inspector_department || ''}`,
        }])
      }
    }
  })

  // 从飞书登录信息自动填充检查人员姓名和部门（仅新建表单，草稿不覆盖）
  useEffect(() => {
    if (initialValues) return // 有草稿数据时不覆盖
    getCurrentUser().then((user) => {
      if (!user) return
      const patch: Record<string, any> = {}
      if (user.name && user.id) {
        patch.discovered_by = user.id
        patch.discovered_by_name = user.name
        // 预填当前用户到选项列表，确保 Select 正确显示
        setUserOptions([{
          value: user.id,
          label: `${user.name} - ${user.department || ''}`,
        }])
      }
      if (user.department) {
        // inspector_department 是 mode="multiple" Select，需要数组格式
        // 仅当用户部门在预设选项中时才自动填充（mode="multiple" 不支持自由输入）
        const isKnownDept = INSPECTOR_DEPARTMENT_OPTIONS.some(
          (o) => o.value === user.department
        )
        if (isKnownDept) {
          patch.inspector_department = [user.department!]
        }
      }
      if (Object.keys(patch).length > 0) {
        form.setFieldsValue(patch)
      }
    })
  }, [initialValues])

  // 规范化表单值：mode="tags"/"multiple" 字段返回数组，需转为字符串
  const normalizeValues = (values: any): InspectionFormValues => {
    // 从选中的用户选项中提取纯姓名（去掉 " - 部门" 后缀）
    let discoveredByName = values.discovered_by_name || ''
    if (!discoveredByName && values.discovered_by) {
      const selected = userOptions.find((o) => o.value === values.discovered_by)
      if (selected) {
        discoveredByName = selected.label.split(' - ')[0]
      }
    }
    return {
      ...values,
      discovered_by: values.discovered_by || undefined,
      discovered_by_name: discoveredByName || undefined,
      inspector_department: Array.isArray(values.inspector_department)
        ? values.inspector_department.join(',')
        : values.inspector_department,
      discovered_at: values.discovered_at
        ? dayjs(values.discovered_at).format('YYYY-MM-DD')
        : undefined,
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const rawFiles = fileList
        .filter((f) => f.originFileObj)
        .map((f) => f.originFileObj as File)
      await onSubmit(normalizeValues(values), rawFiles)
    } catch {
      // 表单校验失败
    }
  }

  const handleSaveDraft = async () => {
    try {
      const values = await form.validateFields()
      const rawFiles = fileList
        .filter((f) => f.originFileObj)
        .map((f) => f.originFileObj as File)
      await onSaveDraft(normalizeValues(values), rawFiles)
    } catch {
      // 草稿允许不完整，直接取 form 当前值
      const values = form.getFieldsValue()
      const rawFiles = fileList
        .filter((f) => f.originFileObj)
        .map((f) => f.originFileObj as File)
      await onSaveDraft(normalizeValues(values), rawFiles)
    }
  }

  return (
    <Card
      style={{
        borderRadius: 12,
        border: '1px solid #e5e3df',
        borderLeft: '4px solid #5645d4',
      }}
      styles={{ body: { padding: '20px 24px' } }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 24,
          paddingBottom: 16,
          borderBottom: '1px solid #ede9e4',
        }}
      >
        <SearchOutlined style={{ color: '#5645d4', fontSize: 18 }} />
        <div>
          <span style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a' }}>登记隐患信息</span>
          <Text type="secondary" style={{ display: 'block', fontSize: 13, color: '#5d5b54' }}>
            填写隐患基本信息并上传图片，AI 将自动识别并回填分类信息
          </Text>
        </div>
      </div>

      <Form
        form={form}
        layout="vertical"
        initialValues={{
          discovered_at: dayjs(),
          ...initialValues,
        }}
      >
        <Row gutter={16}>
          <Col span={24}>
            <Form.Item
              name="inspection_category"
              label="检查类别"
              rules={[{ required: true, message: '请选择检查类别' }]}
            >
              <Select
                placeholder="请选择检查类别"
                options={INSPECTION_CATEGORY_OPTIONS.map((o) => ({
                  value: o.value,
                  label: o.label,
                }))}
              />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="discovered_by"
              label="检查人员"
              rules={[{ required: true, message: '请搜索并选择检查人员' }]}
            >
              <Select
                showSearch
                placeholder="搜索姓名选择检查人员"
                filterOption={false}
                onSearch={handleUserSearch}
                options={userOptions}
                loading={userSearchLoading}
                notFoundContent={userSearchLoading ? '搜索中...' : '输入姓名搜索'}
                onChange={(userId: string) => {
                  form.setFieldValue('discovered_by', userId)
                  const selected = userOptions.find((o) => o.value === userId)
                  if (selected) {
                    form.setFieldValue('discovered_by_name', selected.label.split(' - ')[0])
                  }
                }}
                optionRender={(option) => {
                  const parts = (option.label as string).split(' - ')
                  const name = parts[0] || ''
                  const dept = parts.slice(1).join(' - ')
                  return (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
                      <Avatar size={28} style={{ backgroundColor: '#5645d4', flexShrink: 0, fontSize: 12, fontWeight: 600 }}>
                        {name.charAt(0)}
                      </Avatar>
                      <div style={{ lineHeight: 1.3 }}>
                        <Text style={{ fontSize: 14, fontWeight: 500, color: '#1a1a1a', display: 'block' }}>
                          {name}
                        </Text>
                        {dept && (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {dept}
                          </Text>
                        )}
                      </div>
                    </div>
                  )
                }}
              />
            </Form.Item>
            {/* 隐藏字段：存储检查人员姓名 */}
            <Form.Item name="discovered_by_name" hidden>
              <Input />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="department"
              label="责任部门"
              rules={[{ required: true, message: '请输入责任部门' }]}
            >
              <Input placeholder="请输入责任部门" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="inspector_department"
              label="检查人员部门"
            >
              <Select
                mode="multiple"
                placeholder="请选择检查人员部门（可多选）"
                options={INSPECTOR_DEPARTMENT_OPTIONS.map((o) => ({
                  value: o.value,
                  label: o.label,
                }))}
                maxTagCount={3}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="discovered_at"
              label="检查日期"
              rules={[{ required: true, message: '请选择检查日期' }]}
            >
              <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="description" label="隐患描述（可选）">
          <TextArea
            rows={3}
            placeholder="可选填写隐患描述。如上传图片，AI 将自动识别并生成描述。"
          />
        </Form.Item>

        <Divider />

        <div style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <CameraOutlined style={{ color: '#5645d4', fontSize: 14 }} />
            <Text strong style={{ fontSize: 14 }}>隐患图片上传</Text>
          </div>
          <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
            上传隐患现场图片，AI 将自动分析识别隐患信息（支持 JPG/PNG，单张不超过 10MB）
          </Text>
        </div>
        <Dragger
          multiple
          fileList={fileList}
          beforeUpload={() => false}
          accept="image/*"
          listType="picture-card"
          onChange={(info) => setFileList(info.fileList)}
          style={{ marginBottom: 24 }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽图片到此区域上传</p>
          <p className="ant-upload-hint">支持批量上传</p>
        </Dragger>

        <Divider />

        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
          <Button
            icon={<SaveOutlined />}
            onClick={handleSaveDraft}
            disabled={loading}
          >
            保存草稿
          </Button>
          <Button
            type="primary"
            size="large"
            icon={<ThunderboltOutlined />}
            onClick={handleSubmit}
            loading={loading}
          >
            提交并AI分析
          </Button>
        </Space>
      </Form>
    </Card>
  )
}
