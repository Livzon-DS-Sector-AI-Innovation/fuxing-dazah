'use client'

import { useState, type ReactNode } from 'react'
import { Alert, App, Button, Card, Col, DatePicker, Form, Input, Radio, Row, Select, Space, Switch, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { updateDeviation } from '@/actions/qa-deviation'
import {
  DEVIATION_CLASSIFICATION_LABEL,
  DEVIATION_ITEM_CATEGORY_LABEL,
  QUALITY_IMPACT_LABEL,
  ROOT_CAUSE_CATEGORY_LABEL,
  type DeviationClassification,
  type DeviationDetail,
  type DeviationHypothesisTest,
  type DeviationItem,
  type DeviationUpdateInput,
  type QualityImpact,
  type RootCauseCategory,
  type WhyStep,
} from '@/types/qa-deviation'
import { DeviationReportFields, reportFormInitialValues, reportFormToPayload, useQaDepartments, type ReportFormValues } from './DeviationReportFields'
import { Field, actionError, cardStyle, cardStyles, fmtDate, toOptions } from './shared'

const trimOrNull = (value?: string | null) => (value && value.trim() ? value.trim() : null)

export function SectionCard({
  title,
  hint,
  extra,
  children,
}: {
  title: ReactNode
  hint?: ReactNode
  extra?: ReactNode
  children: ReactNode
}) {
  return (
    <Card
      size="small"
      title={
        <Space size={8}>
          <span style={{ fontWeight: 600 }}>{title}</span>
          {hint && <span style={{ fontSize: 12, color: '#787671', fontWeight: 400 }}>{hint}</span>}
        </Space>
      }
      extra={extra}
      style={{ ...cardStyle, marginBottom: 16 }}
      styles={cardStyles}
    >
      {children}
    </Card>
  )
}

function EditButton({ onClick }: { onClick: () => void }) {
  return <Button size="small" icon={<EditOutlined />} onClick={onClick}>编辑</Button>
}

/** 未填写时用一句话代替整片「未填写」字段，避免空白网格淹没真正要看的内容。 */
function EmptyHint({ children }: { children: ReactNode }) {
  return <div style={{ padding: '2px 0', fontSize: 13, color: '#a4a097' }}>{children}</div>
}

/** 开关/单选组不是原生表单元素，用独立标签避免 antd 生成无效的 label[for]。 */
function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{ paddingBottom: 8, fontSize: 14, fontWeight: 500, lineHeight: '21px', color: '#1a1a1a' }}>
      {children}
    </div>
  )
}

/** 长表单按调查步骤分组，用细线分隔，避免一屏字段没有层次。 */
function FormBlock({
  title,
  hint,
  first = false,
  children,
}: {
  title: string
  hint?: string
  first?: boolean
  children: ReactNode
}) {
  return (
    <section
      style={{
        marginTop: first ? 0 : 20,
        paddingTop: first ? 0 : 16,
        borderTop: first ? 'none' : '1px solid #ede9e4',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#37352f' }}>{title}</span>
        {hint && <span style={{ fontSize: 12, color: '#787671' }}>{hint}</span>}
      </div>
      {children}
    </section>
  )
}

function EditActions({ saving, onCancel }: { saving: boolean; onCancel: () => void }) {
  return (
    <Space style={{ marginTop: 20 }}>
      <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
      <Button onClick={onCancel} disabled={saving}>取消</Button>
    </Space>
  )
}

function useSectionSave(deviationId: string, onSaved: () => void) {
  const { message } = App.useApp()
  const [saving, setSaving] = useState(false)
  const save = async (payload: DeviationUpdateInput, done: () => void) => {
    setSaving(true)
    try {
      const result = await updateDeviation(deviationId, payload)
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('已保存')
      done()
      onSaved()
    } finally {
      setSaving(false)
    }
  }
  return { saving, save }
}

// ───────────────────────── ① 报告信息 ─────────────────────────

const itemColumns: ColumnsType<DeviationItem> = [
  { title: '类别', dataIndex: 'category', width: 90, render: (value: DeviationItem['category']) => DEVIATION_ITEM_CATEGORY_LABEL[value] },
  { title: '名称', dataIndex: 'name' },
  { title: '批号 / 编号', dataIndex: 'batch_no', width: 200, render: (value: string | null) => value || '—' },
  { title: '处理意见', dataIndex: 'handling', render: (value: string | null) => value || <span style={{ color: '#a4a097' }}>待评估</span> },
]

export function ReportSection({ detail, canEdit, onSaved }: { detail: DeviationDetail; canEdit: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [form] = Form.useForm<ReportFormValues>()
  const departments = useQaDepartments()
  const { saving, save } = useSectionSave(detail.id, onSaved)

  const handleFinish = (values: ReportFormValues) => {
    void save(reportFormToPayload(values, departments), () => setEditing(false))
  }

  return (
    <SectionCard
      title="① 偏差报告"
      hint="发生部门报告的内容，由 QA 登记"
      extra={canEdit && !editing && <EditButton onClick={() => setEditing(true)} />}
    >
      {editing ? (
        <Form form={form} layout="vertical" initialValues={reportFormInitialValues(detail)} onFinish={handleFinish}>
          <DeviationReportFields departments={departments} showHandling />
          <EditActions saving={saving} onCancel={() => setEditing(false)} />
        </Form>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Field label="偏差描述">{detail.description}</Field>
          <Field label="应急处理措施">{detail.emergency_measures}</Field>
          <div>
            <div style={{ fontSize: 12, color: '#787671', marginBottom: 6 }}>涉及物料 / 产品 / 设备 / 文件</div>
            <Table<DeviationItem>
              rowKey={(row) => row.id ?? `${row.category}-${row.name}-${row.batch_no}`}
              size="small"
              pagination={false}
              columns={itemColumns}
              dataSource={detail.items}
              locale={{ emptyText: '未登记涉及对象' }}
            />
          </div>
          {detail.remark && <Field label="其他说明">{detail.remark}</Field>}
        </div>
      )}
    </SectionCard>
  )
}

// ───────────────────────── ② 偏差调查 ─────────────────────────

const M1E_FIELDS: { key: keyof Pick<DeviationDetail, 'm1e_personnel' | 'm1e_machine' | 'm1e_material' | 'm1e_method' | 'm1e_environment' | 'm1e_other'>; label: string; hint: string }[] = [
  { key: 'm1e_personnel', label: '人员', hint: '培训资质、当时状态、是否多任务、询问记录' },
  { key: 'm1e_machine', label: '设备 / 仪器', hint: '校准状态、运行状态、界面或标识缺陷' },
  { key: 'm1e_material', label: '物料', hint: '包装标签形态是否易混淆' },
  { key: 'm1e_method', label: '方法 / 程序', hint: 'SOP 是否清晰、可操作、有防错设计' },
  { key: 'm1e_environment', label: '环境', hint: '光线噪音布局、干扰源' },
  { key: 'm1e_other', label: '其他', hint: '记录存放、提示标识等' },
]

interface InvestigationFormValues {
  m1e_personnel?: string
  m1e_machine?: string
  m1e_material?: string
  m1e_method?: string
  m1e_environment?: string
  m1e_other?: string
  direct_cause?: string
  root_cause?: string
  root_cause_category?: RootCauseCategory | null
  why_chain?: Partial<WhyStep>[]
  extended_investigation?: boolean
  extended_result?: string
  hypothesis_tests?: (Omit<Partial<DeviationHypothesisTest>, 'tested_at'> & { tested_at?: Dayjs | null })[]
}

const DEFAULT_WHY: WhyStep[] = [
  { question: '为什么会发生？', answer: '' },
  { question: '为什么没有被发现？', answer: '' },
  { question: '为什么体系没有预防？', answer: '' },
]

const hypothesisColumns: ColumnsType<DeviationHypothesisTest> = [
  { title: '假设原因', dataIndex: 'hypothesis' },
  { title: '方案 / 预期', render: (_, row) => [row.protocol, row.expected].filter(Boolean).join(' → ') || '—' },
  { title: '结果', dataIndex: 'result', render: (value: string | null) => value || '—' },
  { title: '数据评价', dataIndex: 'conclusion', render: (value: string | null) => value || '—' },
  { title: '检验人 / 日期', width: 150, render: (_, row) => [row.tested_by, row.tested_at ? fmtDate(row.tested_at) : null].filter(Boolean).join(' · ') || '—' },
]

export function InvestigationSection({
  detail,
  canEdit,
  locked,
  onSaved,
}: {
  detail: DeviationDetail
  canEdit: boolean
  /** 登记阶段尚未开始调查时只读并提示。 */
  locked: boolean
  onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [form] = Form.useForm<InvestigationFormValues>()
  const { saving, save } = useSectionSave(detail.id, onSaved)

  const hasInvestigation = Boolean(
    detail.m1e_personnel || detail.m1e_machine || detail.m1e_material || detail.m1e_method ||
    detail.m1e_environment || detail.m1e_other || detail.direct_cause || detail.root_cause ||
    detail.extended_result || detail.why_chain.length || detail.hypothesis_tests.length,
  )

  const initial: InvestigationFormValues = {
    m1e_personnel: detail.m1e_personnel ?? undefined,
    m1e_machine: detail.m1e_machine ?? undefined,
    m1e_material: detail.m1e_material ?? undefined,
    m1e_method: detail.m1e_method ?? undefined,
    m1e_environment: detail.m1e_environment ?? undefined,
    m1e_other: detail.m1e_other ?? undefined,
    direct_cause: detail.direct_cause ?? undefined,
    root_cause: detail.root_cause ?? undefined,
    root_cause_category: detail.root_cause_category,
    why_chain: detail.why_chain.length ? detail.why_chain : DEFAULT_WHY,
    extended_investigation: detail.extended_investigation,
    extended_result: detail.extended_result ?? undefined,
    hypothesis_tests: detail.hypothesis_tests.map((test) => ({ ...test, tested_at: test.tested_at ? dayjs(test.tested_at) : null })),
  }

  const handleFinish = (values: InvestigationFormValues) => {
    const payload: DeviationUpdateInput = {
      m1e_personnel: trimOrNull(values.m1e_personnel),
      m1e_machine: trimOrNull(values.m1e_machine),
      m1e_material: trimOrNull(values.m1e_material),
      m1e_method: trimOrNull(values.m1e_method),
      m1e_environment: trimOrNull(values.m1e_environment),
      m1e_other: trimOrNull(values.m1e_other),
      direct_cause: trimOrNull(values.direct_cause),
      root_cause: trimOrNull(values.root_cause),
      root_cause_category: values.root_cause_category ?? null,
      why_chain: (values.why_chain ?? [])
        .filter((step) => step.question && step.question.trim() && step.answer && step.answer.trim())
        .map((step) => ({ question: step.question!.trim(), answer: step.answer!.trim() })),
      extended_investigation: Boolean(values.extended_investigation),
      extended_result: trimOrNull(values.extended_result),
      hypothesis_tests: (values.hypothesis_tests ?? [])
        .filter((test) => test.hypothesis && test.hypothesis.trim())
        .map((test) => ({
          hypothesis: test.hypothesis!.trim(),
          sample: trimOrNull(test.sample),
          protocol: trimOrNull(test.protocol),
          expected: trimOrNull(test.expected),
          result: trimOrNull(test.result),
          conclusion: trimOrNull(test.conclusion),
          tested_by: trimOrNull(test.tested_by),
          tested_at: test.tested_at ? test.tested_at.format('YYYY-MM-DD') : null,
        })),
    }
    void save(payload, () => setEditing(false))
  }

  return (
    <SectionCard
      title="② 偏差调查"
      hint="人机料法环 + 5Why，人的错误只是直接原因，须追到系统性根因"
      extra={canEdit && !locked && !editing && <EditButton onClick={() => setEditing(true)} />}
    >
      {locked && !editing && (
        <Alert type="info" showIcon title="点击右上角「开始调查」进入调查阶段后填写。" style={{ marginBottom: 16 }} />
      )}
      {editing ? (
        <Form form={form} layout="vertical" initialValues={initial} onFinish={handleFinish}>
          <FormBlock title="人机料法环" hint="从人、机、料、法、环、其他六个方向记录现场事实" first>
            <Row gutter={[16, 16]}>
              {M1E_FIELDS.map((field) => (
                <Col key={field.key} xs={24} sm={12} xl={8}>
                  <Form.Item name={field.key} label={field.label} extra={field.hint} style={{ marginBottom: 0 }}>
                    <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} maxLength={8000} />
                  </Form.Item>
                </Col>
              ))}
            </Row>
          </FormBlock>

          <FormBlock title="5Why 根本原因分析" hint="连续追问，直到找到系统性原因">
            <Form.List name="why_chain">
              {(fields, { add, remove }) => (
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {fields.map((field, index) => (
                    <div key={field.key} style={{ display: 'grid', gridTemplateColumns: '32px minmax(0, 1fr)', gap: 12 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <span
                          style={{
                            width: 26,
                            height: 26,
                            borderRadius: '50%',
                            background: '#e6e0f5',
                            color: '#5645d4',
                            fontSize: 12,
                            fontWeight: 600,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginTop: 3,
                            fontVariantNumeric: 'tabular-nums',
                          }}
                        >
                          {index + 1}
                        </span>
                        {index < fields.length - 1 && (
                          <span aria-hidden="true" style={{ width: 2, flex: 1, minHeight: 16, background: '#e5e3df', marginTop: 4 }} />
                        )}
                      </div>
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.6fr) 32px',
                          gap: 8,
                          alignItems: 'start',
                          paddingBottom: index < fields.length - 1 ? 12 : 0,
                        }}
                      >
                        <Form.Item name={[field.name, 'question']} style={{ marginBottom: 0 }} rules={[{ required: true, whitespace: true, message: '填写问题' }]}>
                          <Input placeholder="为什么……？" maxLength={500} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'answer']} style={{ marginBottom: 0 }} rules={[{ required: true, whitespace: true, message: '填写回答' }]}>
                          <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} placeholder="回答" maxLength={4000} />
                        </Form.Item>
                        <Button type="text" icon={<DeleteOutlined />} onClick={() => remove(field.name)} aria-label="删除这一问" style={{ marginTop: 2 }} />
                      </div>
                    </div>
                  ))}
                  <Button
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() => add({ question: '', answer: '' })}
                    style={{ alignSelf: 'flex-start', marginLeft: 44, marginTop: 8 }}
                    disabled={fields.length >= 20}
                  >
                    再问一个为什么
                  </Button>
                </div>
              )}
            </Form.List>
          </FormBlock>

          <FormBlock title="原因结论" hint="直接原因说明如何发生，根本原因说明为何发生">
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <Form.Item name="direct_cause" label="直接原因" extra="偏差是「如何发生」的" style={{ marginBottom: 0 }}>
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={8000} />
                </Form.Item>
              </Col>
              <Col xs={24} lg={12}>
                <Form.Item name="root_cause" label="根本原因" extra="偏差「为何发生」的最底层原因" style={{ marginBottom: 0 }}>
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={8000} />
                </Form.Item>
              </Col>
              <Col xs={24} md={10} xl={8}>
                <Form.Item name="root_cause_category" label="根本原因分类" style={{ marginBottom: 0 }}>
                  <Select options={toOptions(ROOT_CAUSE_CATEGORY_LABEL)} allowClear placeholder="选择分类" />
                </Form.Item>
              </Col>
            </Row>
          </FormBlock>

          <FormBlock title="补充调查" hint="确认是否还有同类隐患，必要时用实验验证假设">
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8} xl={4}>
                <FieldLabel>是否扩展调查</FieldLabel>
                <Form.Item name="extended_investigation" valuePropName="checked" style={{ marginBottom: 0 }}>
                  <Switch checkedChildren="是" unCheckedChildren="否" aria-label="是否扩展调查" />
                </Form.Item>
              </Col>
              <Col xs={24} md={16} xl={20}>
                <Form.Item name="extended_result" label="扩展调查结果" extra="别处是否存在同样的隐患结构，如前后三批、同类仪器" style={{ marginBottom: 0 }}>
                  <Input.TextArea autoSize={{ minRows: 1, maxRows: 6 }} maxLength={8000} />
                </Form.Item>
              </Col>
            </Row>
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#37352f', marginBottom: 8 }}>假设性检验</div>
              <Form.List name="hypothesis_tests">
                {(fields, { add, remove }) => (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {fields.map((field) => (
                      <div key={field.key} style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: 12, display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr)) 32px', gap: 8, alignItems: 'start' }}>
                        <Form.Item name={[field.name, 'hypothesis']} style={{ marginBottom: 0, gridColumn: 'span 2' }} rules={[{ required: true, whitespace: true, message: '填写假设原因' }]}>
                          <Input placeholder="假设原因" maxLength={4000} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'sample']} style={{ marginBottom: 0, gridColumn: 'span 2' }}>
                          <Input placeholder="需要检验的样品" maxLength={4000} />
                        </Form.Item>
                        <Button type="text" icon={<DeleteOutlined />} onClick={() => remove(field.name)} aria-label="删除" />
                        <Form.Item name={[field.name, 'protocol']} style={{ marginBottom: 0, gridColumn: 'span 2' }}>
                          <Input placeholder="假设方案" maxLength={4000} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'expected']} style={{ marginBottom: 0, gridColumn: 'span 2' }}>
                          <Input placeholder="预期的标准 / 结果" maxLength={4000} />
                        </Form.Item>
                        <span />
                        <Form.Item name={[field.name, 'result']} style={{ marginBottom: 0 }}>
                          <Input placeholder="检验结果" maxLength={4000} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'conclusion']} style={{ marginBottom: 0 }}>
                          <Input placeholder="数据评价 / 结论" maxLength={4000} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'tested_by']} style={{ marginBottom: 0 }}>
                          <Input placeholder="检验员" maxLength={128} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'tested_at']} style={{ marginBottom: 0 }}>
                          <DatePicker placeholder="检验日期" style={{ width: '100%' }} />
                        </Form.Item>
                      </div>
                    ))}
                    {fields.length === 0 && (
                      <div style={{ fontSize: 13, color: '#a4a097' }}>尚无假设性检验。只有常规分析无法确认根因时，才需要添加实验验证。</div>
                    )}
                    <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({})} style={{ alignSelf: 'flex-start' }}>
                      添加假设性检验
                    </Button>
                  </div>
                )}
              </Form.List>
            </div>
          </FormBlock>
          <EditActions saving={saving} onCancel={() => setEditing(false)} />
        </Form>
      ) : !hasInvestigation ? (
        locked ? null : (
          <EmptyHint>尚未填写调查内容。点击右上角「编辑」记录人机料法环、5Why 与根本原因。</EmptyHint>
        )
      ) : (
        <>
          <FormBlock title="人机料法环" hint="现场事实记录" first>
            <Row gutter={[16, 16]}>
              {M1E_FIELDS.map((field) => (
                <Col key={field.key} xs={24} sm={12} xl={8}>
                  <Field label={field.label}>{detail[field.key]}</Field>
                </Col>
              ))}
            </Row>
          </FormBlock>
          <FormBlock title="5Why 根本原因分析" hint="连续追问得到的因果链">
            {detail.why_chain.length === 0 ? (
              <span style={{ color: '#a4a097', fontSize: 13 }}>未填写</span>
            ) : (
              <ol style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {detail.why_chain.map((step, index) => (
                  <li key={index}>
                    <span style={{ fontWeight: 600 }}>{step.question}</span>
                    <div style={{ color: '#37352f', whiteSpace: 'pre-wrap' }}>{step.answer}</div>
                  </li>
                ))}
              </ol>
            )}
          </FormBlock>
          <FormBlock title="原因结论" hint="直接原因说明如何发生，根本原因说明为何发生">
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <Field label="直接原因">{detail.direct_cause}</Field>
              </Col>
              <Col xs={24} lg={12}>
                <Field label="根本原因">{detail.root_cause}</Field>
              </Col>
              <Col xs={24} md={10} xl={8}>
                <Field label="根本原因分类">{detail.root_cause_category ? ROOT_CAUSE_CATEGORY_LABEL[detail.root_cause_category] : null}</Field>
              </Col>
            </Row>
          </FormBlock>
          <FormBlock title="补充调查" hint="同类隐患排查与实验验证">
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8} xl={4}>
                <Field label="是否扩展调查">{detail.extended_investigation ? '是' : '否'}</Field>
              </Col>
              <Col xs={24} md={16} xl={20}>
                <Field label="扩展调查结果">{detail.extended_result}</Field>
              </Col>
            </Row>
            {detail.hypothesis_tests.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#37352f', marginBottom: 8 }}>假设性检验</div>
                <Table<DeviationHypothesisTest>
                  rowKey={(row) => row.id ?? row.hypothesis}
                  size="small"
                  pagination={false}
                  columns={hypothesisColumns}
                  dataSource={detail.hypothesis_tests}
                />
              </div>
            )}
          </FormBlock>
        </>
      )}
    </SectionCard>
  )
}

// ───────────────────────── ③ 偏差评估 ─────────────────────────

interface AssessmentFormValues {
  quality_impact?: QualityImpact | null
  quality_impact_reason?: string
  classification?: DeviationClassification | null
  stability_needed?: boolean
  stability_note?: string
  validation_impact?: boolean
  validation_note?: string
  registration_impact?: boolean
  registration_note?: string
  notify_customer?: boolean
  customer_note?: string
  is_repeat?: boolean
  repeat_deviation_ids?: string[]
  capa_initiated?: boolean | null
  capa_not_initiated_reason?: string
}

const TOGGLES: { flag: 'stability_needed' | 'validation_impact' | 'registration_impact' | 'notify_customer'; note: 'stability_note' | 'validation_note' | 'registration_note' | 'customer_note'; label: string; notePlaceholder: string }[] = [
  { flag: 'stability_needed', note: 'stability_note', label: '开展稳定性研究', notePlaceholder: '加速 / 长期试验安排' },
  { flag: 'validation_impact', note: 'validation_note', label: '影响验证 / 协议事项', notePlaceholder: '措施' },
  { flag: 'registration_impact', note: 'registration_note', label: '影响注册资料（RA）', notePlaceholder: '措施' },
  { flag: 'notify_customer', note: 'customer_note', label: '通知客户', notePlaceholder: '依据质量协议的说明' },
]

function AssessmentForm({
  initial,
  candidateOptions,
  saving,
  onFinish,
  onCancel,
}: {
  initial: AssessmentFormValues
  candidateOptions: { value: string; label: string }[]
  saving: boolean
  onFinish: (values: AssessmentFormValues) => void
  onCancel: () => void
}) {
  const [form] = Form.useForm<AssessmentFormValues>()
  const isRepeat = Form.useWatch('is_repeat', form)
  const capaInitiated = Form.useWatch('capa_initiated', form)
  const toggles = {
    stability_needed: Form.useWatch('stability_needed', form),
    validation_impact: Form.useWatch('validation_impact', form),
    registration_impact: Form.useWatch('registration_impact', form),
    notify_customer: Form.useWatch('notify_customer', form),
  }

  return (
    <Form form={form} layout="vertical" initialValues={initial} onFinish={onFinish}>
      <FormBlock title="质量影响判断" hint="依据调查数据判断是否影响产品质量" first>
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <FieldLabel>对质量的影响</FieldLabel>
            <Form.Item name="quality_impact" style={{ marginBottom: 0 }}>
              <Radio.Group options={toOptions(QUALITY_IMPACT_LABEL)} aria-label="对质量的影响" />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item name="classification" label="偏差分类" extra="按调查确认的实际影响判定" style={{ marginBottom: 0 }}>
              <Select options={toOptions(DEVIATION_CLASSIFICATION_LABEL)} allowClear placeholder="选择分类" />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <FieldLabel>是否重复发生</FieldLabel>
            <Form.Item
              name="is_repeat"
              valuePropName="checked"
              extra="同部门同组别 3 个月内同一根本原因再发"
              style={{ marginBottom: 0 }}
            >
              <Switch checkedChildren="是" unCheckedChildren="否" aria-label="是否重复发生" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="quality_impact_reason" label="影响结论的理由" extra="依据数据、复测结果、理论判断" style={{ marginTop: 16, marginBottom: 0 }}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} maxLength={8000} />
        </Form.Item>
        {isRepeat && (
          <Form.Item
            name="repeat_deviation_ids"
            label="关联的重复偏差"
            rules={[{ required: true, message: '请选择关联的偏差' }]}
            style={{ marginTop: 16, marginBottom: 0 }}
          >
            <Select mode="multiple" options={candidateOptions} placeholder="选择关联的偏差（可多选）" style={{ maxWidth: 720 }} />
          </Form.Item>
        )}
      </FormBlock>

      <FormBlock title="附加影响评估" hint="开启后补充说明">
        <div>
          {TOGGLES.map((toggle, index) => (
            <div
              key={toggle.flag}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 0',
                borderBottom: index < TOGGLES.length - 1 ? '1px solid #f5f3f0' : 'none',
              }}
            >
              <Form.Item name={toggle.flag} valuePropName="checked" noStyle>
                <Switch checkedChildren="是" unCheckedChildren="否" aria-label={toggle.label} />
              </Form.Item>
              <span style={{ width: 170, flexShrink: 0, fontSize: 14, color: '#37352f' }}>{toggle.label}</span>
              {toggles[toggle.flag] ? (
                <Form.Item name={toggle.note} noStyle>
                  <Input
                    placeholder={toggle.notePlaceholder}
                    maxLength={4000}
                    aria-label={`${toggle.label}说明`}
                    style={{ flex: 1, maxWidth: 520 }}
                  />
                </Form.Item>
              ) : (
                <span style={{ fontSize: 12, color: '#a4a097' }}>无需填写说明</span>
              )}
            </div>
          ))}
        </div>
      </FormBlock>

      <FormBlock title="CAPA 决定" hint="需要纠正预防措施时发起 CAPA">
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <FieldLabel>是否执行 CAPA 程序</FieldLabel>
            <Form.Item name="capa_initiated" style={{ marginBottom: 0 }}>
              <Radio.Group
                aria-label="是否执行 CAPA 程序"
                options={[
                  { value: true, label: '发起 CAPA' },
                  { value: false, label: '不发起' },
                ]}
              />
            </Form.Item>
          </div>
          {capaInitiated === false && (
            <Form.Item
              name="capa_not_initiated_reason"
              label="不发起 CAPA 的原因"
              rules={[{ required: true, whitespace: true, message: '请说明不发起原因' }]}
              style={{ flex: 1, minWidth: 260, marginBottom: 0 }}
            >
              <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} maxLength={4000} />
            </Form.Item>
          )}
        </div>
      </FormBlock>
      <EditActions saving={saving} onCancel={onCancel} />
    </Form>
  )
}

export function AssessmentSection({
  detail,
  canEdit,
  locked,
  onSaved,
  capaSlot,
}: {
  detail: DeviationDetail
  canEdit: boolean
  locked: boolean
  onSaved: () => void
  /** CAPA 发起按钮与已发起列表，由页面注入以共享弹窗状态。 */
  capaSlot: ReactNode
}) {
  const [editing, setEditing] = useState(false)
  const { saving, save } = useSectionSave(detail.id, onSaved)

  const hasAssessment = Boolean(
    detail.quality_impact || detail.classification || detail.quality_impact_reason ||
    detail.stability_needed || detail.validation_impact || detail.registration_impact || detail.notify_customer ||
    detail.stability_note || detail.validation_note || detail.registration_note || detail.customer_note ||
    detail.is_repeat || detail.capa_initiated !== null || detail.capas.length,
  )

  const initial: AssessmentFormValues = {
    quality_impact: detail.quality_impact,
    quality_impact_reason: detail.quality_impact_reason ?? undefined,
    classification: detail.classification,
    stability_needed: detail.stability_needed,
    stability_note: detail.stability_note ?? undefined,
    validation_impact: detail.validation_impact,
    validation_note: detail.validation_note ?? undefined,
    registration_impact: detail.registration_impact,
    registration_note: detail.registration_note ?? undefined,
    notify_customer: detail.notify_customer,
    customer_note: detail.customer_note ?? undefined,
    is_repeat: detail.is_repeat,
    repeat_deviation_ids: detail.repeat_deviation_ids,
    capa_initiated: detail.capa_initiated,
    capa_not_initiated_reason: detail.capa_not_initiated_reason ?? undefined,
  }

  const candidateOptions = [
    ...detail.repeat_candidates.map((candidate) => ({
      value: candidate.id,
      label: `${candidate.deviation_no} · ${fmtDate(candidate.discovery_date)}`,
    })),
    ...detail.repeat_deviation_ids
      .filter((id) => !detail.repeat_candidates.some((candidate) => candidate.id === id))
      .map((id) => ({ value: id, label: id })),
  ]

  const handleFinish = (values: AssessmentFormValues) => {
    const payload: DeviationUpdateInput = {
      quality_impact: values.quality_impact ?? null,
      quality_impact_reason: trimOrNull(values.quality_impact_reason),
      classification: values.classification ?? null,
      stability_needed: Boolean(values.stability_needed),
      stability_note: values.stability_needed ? trimOrNull(values.stability_note) : null,
      validation_impact: Boolean(values.validation_impact),
      validation_note: values.validation_impact ? trimOrNull(values.validation_note) : null,
      registration_impact: Boolean(values.registration_impact),
      registration_note: values.registration_impact ? trimOrNull(values.registration_note) : null,
      notify_customer: Boolean(values.notify_customer),
      customer_note: values.notify_customer ? trimOrNull(values.customer_note) : null,
      is_repeat: Boolean(values.is_repeat),
      repeat_deviation_ids: values.is_repeat ? values.repeat_deviation_ids ?? [] : [],
      capa_initiated: values.capa_initiated ?? null,
      capa_not_initiated_reason: values.capa_initiated === false ? trimOrNull(values.capa_not_initiated_reason) : null,
    }
    void save(payload, () => setEditing(false))
  }

  const repeatNames = detail.repeat_deviation_ids.map(
    (id) => detail.repeat_candidates.find((candidate) => candidate.id === id)?.deviation_no ?? id,
  )

  return (
    <SectionCard
      title="③ 偏差评估"
      hint="QA + RA：质量影响、分类、批次处置与 CAPA 决定"
      extra={canEdit && !locked && !editing && <EditButton onClick={() => setEditing(true)} />}
    >
      {locked && !editing && (
        <Alert type="info" showIcon title="调查提交后进入评估阶段再填写。" style={{ marginBottom: 16 }} />
      )}
      {detail.repeat_candidates.length > 0 && (
        <Alert
          type="warning"
          showIcon
          title={`发现 ${detail.repeat_candidates.length} 起同部门同组别同根因分类、发现日期相距 3 个月内的偏差，请判断是否为重复偏差`}
          description={detail.repeat_candidates.map((candidate) => `${candidate.deviation_no}（${fmtDate(candidate.discovery_date)}）：${candidate.description}`).join('\n')}
          style={{ marginBottom: 16, whiteSpace: 'pre-wrap' }}
        />
      )}
      {editing ? (
        <AssessmentForm
          initial={initial}
          candidateOptions={candidateOptions}
          saving={saving}
          onFinish={handleFinish}
          onCancel={() => setEditing(false)}
        />
      ) : !hasAssessment ? (
        locked ? null : (
          <EmptyHint>尚未填写评估内容。点击右上角「编辑」记录质量影响、偏差分类与 CAPA 决定。</EmptyHint>
        )
      ) : (
        <>
          <FormBlock title="质量影响判断" hint="依据调查数据判断是否影响产品质量" first>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Field label="对质量的影响">{detail.quality_impact ? QUALITY_IMPACT_LABEL[detail.quality_impact] : null}</Field>
              </Col>
              <Col xs={24} md={8}>
                <Field label="偏差分类">{detail.classification ? DEVIATION_CLASSIFICATION_LABEL[detail.classification] : null}</Field>
              </Col>
              <Col xs={24} md={8}>
                <Field label="是否重复发生">{detail.is_repeat ? `是（${repeatNames.join('、') || '未关联'}）` : '否'}</Field>
              </Col>
              <Col span={24}>
                <Field label="影响结论的理由">{detail.quality_impact_reason}</Field>
              </Col>
            </Row>
          </FormBlock>
          <FormBlock title="附加影响评估" hint="稳定性、验证、注册与客户通知">
            <Row gutter={[16, 16]}>
              {TOGGLES.map((toggle) => (
                <Col key={toggle.flag} xs={24} md={12} xl={6}>
                  <Field label={toggle.label}>
                    {detail[toggle.flag] ? `是${detail[toggle.note] ? `：${detail[toggle.note]}` : ''}` : '否'}
                  </Field>
                </Col>
              ))}
            </Row>
          </FormBlock>
          <FormBlock title="CAPA 决定" hint="纠正预防措施的发起情况">
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Field label="是否执行 CAPA 程序">
                  {detail.capa_initiated === null ? null : detail.capa_initiated ? '是' : `否：${detail.capa_not_initiated_reason ?? ''}`}
                </Field>
              </Col>
              <Col xs={24} md={16}>{capaSlot}</Col>
            </Row>
          </FormBlock>
        </>
      )}
    </SectionCard>
  )
}
