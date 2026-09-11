'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Typography, Table, Button, Modal, Form, Input, InputNumber, Select,
  Space, App, Popconfirm, Upload, Card, Row, Col, Empty, Badge,
  Descriptions, Tag,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, UploadOutlined,
  FileTextOutlined, LinkOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import {
  fetchStandardDocuments, createStandardDocument, updateStandardDocument, deleteStandardDocument,
  fetchStandardItems, createStandardItem, updateStandardItem, deleteStandardItem,
  importStandardDocPreview, importStandardDocConfirm, fetchTemplates, bindTemplate,
  type StandardDocument, type StandardItem, type StandardImportDraft, type StandardImportDraftItem,
} from '@/actions/quality'
import ImportConfirmModal, { type ImportDraftDocument } from '@/components/quality/ImportConfirmModal'

const { Title, Paragraph, Text } = Typography

/** 展平模板树为路径列表。 */
function flattenTemplates(items: any[], prefix = ''): string[] {
  const out: string[] = []
  for (const it of items || []) {
    if (it.type === 'template') out.push(prefix ? `${prefix}/${it.filename}` : it.filename)
    else if (it.children) out.push(...flattenTemplates(it.children, prefix ? `${prefix}/${it.name}` : it.name))
  }
  return out
}

/** 提取文本中的数字串（号码片段）。 */
function numberTokens(...texts: (string | null | undefined)[]): string[] {
  const tokens: string[] = []
  for (const t of texts) {
    if (!t) continue
    for (const m of t.matchAll(/\d+/g)) tokens.push(m[0])
  }
  return tokens
}

/** 模板路径与标准文档的号码相似度（模板号码≈SOP号码，命中多的排前）。 */
function similarityScore(doc: StandardDocument, templatePath: string): number {
  const docTokens = numberTokens(doc.file_no, doc.product_internal_code, doc.product_code, doc.version)
  const tpTokens = numberTokens(templatePath)
  let score = 0
  for (const a of docTokens) {
    for (const b of tpTokens) {
      if (a === b) score += 10
      else if (a.includes(b) || b.includes(a)) score += 3
    }
  }
  return score
}

export default function StandardsPage() {
  const { message } = App.useApp()
  const [docs, setDocs] = useState<StandardDocument[]>([])
  const [activeProduct, setActiveProduct] = useState<string | undefined>()
  const [activeCode, setActiveCode] = useState<string | undefined>()
  const [activeDocId, setActiveDocId] = useState<string | undefined>()
  const [productSearch, setProductSearch] = useState('')
  const [items, setItems] = useState<StandardItem[]>([])
  const [loading, setLoading] = useState(false)

  const [docModalOpen, setDocModalOpen] = useState(false)
  const [editingDoc, setEditingDoc] = useState<StandardDocument | null>(null)
  const [docForm] = Form.useForm()

  const [itemModalOpen, setItemModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<StandardItem | null>(null)
  const [itemForm] = Form.useForm()

  const [bindOpen, setBindOpen] = useState(false)
  const [bindDoc, setBindDoc] = useState<StandardDocument | null>(null)
  const [bindValue, setBindValue] = useState<string | undefined>()
  const [bindOptions, setBindOptions] = useState<{ label: string; value: string }[]>([])

  const [importOpen, setImportOpen] = useState(false)
  const [importDraft, setImportDraft] = useState<StandardImportDraft | null>(null)
  const [importKey, setImportKey] = useState(0)
  const [confirming, setConfirming] = useState(false)

  const loadDocs = useCallback(async (): Promise<StandardDocument[]> => {
    setLoading(true)
    try {
      const res = await fetchStandardDocuments()
      setDocs(res.data || [])
      return res.data || []
    } catch (err: any) {
      message.error(err.message || '加载标准文档失败')
      return []
    } finally {
      setLoading(false)
    }
  }, [message])

  const loadItems = useCallback(async (docId: string) => {
    try {
      const res = await fetchStandardItems(docId)
      setItems(res.data || [])
    } catch (err: any) {
      message.error(err.message || '加载标准行失败')
    }
  }, [message])

  useEffect(() => { loadDocs() }, [loadDocs])

  // 三级结构：产品名称（去重）→ 产品代码（去重，一个代码可有多份文件）→ 文件下拉 + SOP 项目行
  const nameKey = (n: string) => n.replace(/\s+/g, '')
  const products = useMemo(() => {
    const seen = new Map<string, string>()
    for (const d of docs) {
      const k = nameKey(d.product_name)
      if (!seen.has(k)) seen.set(k, d.product_name)
    }
    return Array.from(seen.values()).sort((a, b) => a.localeCompare(b, 'zh-CN'))
  }, [docs])
  const docsOf = (product: string) => docs.filter((d) => nameKey(d.product_name) === nameKey(product))
  const filteredProducts = useMemo(() => {
    const kw = productSearch.trim().toLowerCase()
    if (!kw) return products
    return products.filter((p) =>
      nameKey(p).toLowerCase().includes(nameKey(kw)) ||
      docsOf(p).some((d) =>
        d.file_no.toLowerCase().includes(kw) ||
        (d.product_code || '').toLowerCase().includes(kw) ||
        (d.product_internal_code || '').toLowerCase().includes(kw),
      ),
    )
  }, [products, productSearch, docs])

  // 搜索直达：命中产品代码/内部代码/文件编号时，直接跳到对应文档（产品只有一个时也能看到效果）
  const handleSearch = (v: string) => {
    setProductSearch(v)
    const kw = v.trim().toLowerCase()
    if (!kw) return
    for (const d of docs) {
      if ((d.product_code || '').toLowerCase().includes(kw)
        || (d.product_internal_code || '').toLowerCase().includes(kw)) {
        setActiveProduct(d.product_name)
        setActiveCode(d.product_code || undefined)
        setActiveDocId(d.id)
        return
      }
    }
    for (const d of docs) {
      if (d.file_no.toLowerCase().includes(kw)) {
        setActiveProduct(d.product_name)
        setActiveCode(d.product_code || undefined)
        setActiveDocId(d.id)
        return
      }
    }
  }
  const activeProductName = activeProduct && filteredProducts.includes(activeProduct) ? activeProduct : filteredProducts[0]

  const codes = useMemo(() => {
    if (!activeProductName) return []
    const seen = new Set<string>()
    const out: string[] = []
    for (const d of docsOf(activeProductName)) {
      if (d.product_code && !seen.has(d.product_code)) {
        seen.add(d.product_code)
        out.push(d.product_code)
      }
    }
    return out
  }, [activeProductName, docs])
  const codeDocs = activeProductName && activeCode
    ? docsOf(activeProductName).filter((d) => d.product_code === activeCode)
    : []
  const activeCodeName = activeCode && codes.includes(activeCode) ? activeCode : codes[0]
  const activeDoc = codeDocs.find((d) => d.id === activeDocId) || codeDocs[0]

  useEffect(() => {
    if (activeDoc) loadItems(activeDoc.id)
    else setItems([])
  }, [activeDoc?.id, loadItems])

  const selectProduct = (p: string) => {
    setActiveProduct(p)
    const ds = docsOf(p)
    setActiveCode(ds[0]?.product_code || undefined)
    setActiveDocId(ds[0]?.id)
  }

  const selectCode = (c: string) => {
    setActiveCode(c)
    setActiveDocId(codeDocs.find((d) => d.product_code === c)?.id)
  }

  const openDocModal = (doc?: StandardDocument) => {
    setEditingDoc(doc || null)
    docForm.resetFields()
    if (doc) docForm.setFieldsValue(doc)
    else if (activeProductName) {
      docForm.setFieldsValue({ product_name: activeProductName, product_code: activeCodeName })
    }
    setDocModalOpen(true)
  }

  const handleDocSave = async () => {
    const values = await docForm.validateFields()
    try {
      if (editingDoc) {
        await updateStandardDocument(editingDoc.id, values)
        message.success('标准文档已更新')
      } else {
        const res = await createStandardDocument(values)
        message.success('标准文档已创建')
        setActiveCode(values.product_code || undefined)
        setActiveDocId(res.data.id)
      }
      setDocModalOpen(false)
      loadDocs()
    } catch (err: any) {
      message.error(err.message || '保存失败')
    }
  }

  const handleDocDelete = async (id: string) => {
    try {
      await deleteStandardDocument(id)
      message.success('已删除')
      if (activeDocId === id) setActiveDocId(undefined)
      loadDocs()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const handleImport = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importStandardDocPreview(fd)
      message.info(res.message || '解析完成，请核对')
      setImportDraft(res.data)
      setImportKey((k) => k + 1)
      setImportOpen(true)
    } catch (err: any) {
      message.error(err.message || '解析失败')
    }
    return false
  }

  const handleImportConfirm = async (document: ImportDraftDocument, draftItems: StandardImportDraftItem[]) => {
    setConfirming(true)
    try {
      const res = await importStandardDocConfirm(document, draftItems)
      message.success(res.message || '导入完成')
      setImportOpen(false)
      setImportDraft(null)
      setActiveProduct(document.product_name)
      setActiveCode(document.product_code || undefined)
      const fresh = await loadDocs()
      setActiveDocId(fresh.find((d) => d.file_no === document.file_no)?.id)
    } catch (err: any) {
      message.error(err.message || '导入失败')
    } finally {
      setConfirming(false)
    }
  }

  const openItemModal = (item?: StandardItem) => {
    setEditingItem(item || null)
    itemForm.resetFields()
    if (item) itemForm.setFieldsValue(item)
    setItemModalOpen(true)
  }

  const handleItemSave = async () => {
    if (!activeDoc) return
    const values = await itemForm.validateFields()
    try {
      if (editingItem) {
        await updateStandardItem(editingItem.id, values)
        message.success('标准行已更新')
      } else {
        await createStandardItem(activeDoc.id, values)
        message.success('标准行已添加')
      }
      setItemModalOpen(false)
      loadItems(activeDoc.id)
    } catch (err: any) {
      message.error(err.message || '保存失败')
    }
  }

  const handleItemDelete = async (id: string) => {
    try {
      await deleteStandardItem(id)
      message.success('已删除')
      if (activeDoc) loadItems(activeDoc.id)
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const openBindModal = async (doc: StandardDocument) => {
    setBindDoc(doc)
    setBindValue(doc.template_path || undefined)
    setBindOpen(true)
    try {
      const tree = await fetchTemplates()
      const paths = flattenTemplates(tree)
      const sorted = paths
        .map((p) => ({ p, s: similarityScore(doc, p) }))
        .sort((a, b) => b.s - a.s)
        .map((x) => ({ label: `${x.p}${x.s > 0 ? '（号码相近）' : ''}`, value: x.p }))
      setBindOptions([{ label: '（不绑定模板）', value: '' }, ...sorted])
    } catch {
      message.error('加载模板列表失败')
    }
  }

  const handleBindSave = async () => {
    if (!bindDoc || !bindValue) return
    try {
      // COA 侧绑定：模板路径 → 标准文档（一份 COA 唯一绑定一份 SOP）
      await bindTemplate(bindValue, bindDoc.id)
      message.success('模板绑定已保存')
      setBindOpen(false)
      loadDocs()
    } catch (err: any) {
      message.error(err.message || '绑定失败')
    }
  }

  const itemColumns: ColumnsType<StandardItem> = [
    { title: '序号', dataIndex: 'seq', key: 'seq', width: 60, render: (v: number | null) => v ?? '-' },
    { title: '子项目', dataIndex: 'item_name', key: 'item_name', width: 190, ellipsis: true },
    { title: 'SOP号', dataIndex: 'sop_no', key: 'sop_no', width: 130, render: (v: string | null) => v || '-' },
    { title: '合格标准', dataIndex: 'standard_text', key: 'standard_text', ellipsis: true },
    {
      title: '限度', key: 'limit', width: 110,
      render: (_: any, it: StandardItem) => {
        if (!it.operator) return '-'
        if (it.operator === '范围') return `${it.limit_min ?? ''}～${it.limit_max ?? ''}`
        if (it.operator === '≥' || it.operator === '>') return `${it.operator}${it.limit_min ?? ''}`
        return `${it.operator}${it.limit_max ?? ''}`
      },
    },
    { title: '来源', dataIndex: 'method_source', key: 'method_source', width: 130, ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '备注', dataIndex: 'remark', key: 'remark', width: 150, ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '操作', key: 'actions', width: 110,
      render: (_: any, it: StandardItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openItemModal(it)} />
          <Popconfirm title="确认删除?" onConfirm={() => handleItemDelete(it.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}><FileTextOutlined /> 质量标准库</Title>
          <Paragraph type="secondary">
            产品名称 → 产品代码 → 文件 → SOP 项目行；支持按产品名/产品代码/文件编号搜索（回车直达）。
          </Paragraph>
        </div>
        <Upload accept=".doc,.docx" showUploadList={false} beforeUpload={handleImport}>
          <Button type="primary" size="large" icon={<UploadOutlined />}>导入标准文档</Button>
        </Upload>
      </div>

      <Row gutter={12}>
        <Col span={5}>
          <Card size="small" title={`产品名称（${filteredProducts.length}）`}>
            <Input.Search
              placeholder="搜产品/代码/文件编号（回车直达）"
              allowClear
              value={productSearch}
              onChange={(e) => setProductSearch(e.target.value)}
              onSearch={handleSearch}
              style={{ marginBottom: 8 }}
            />
            {products.length === 0 ? (
              <Empty description="暂无标准文档，请导入" />
            ) : (
              <div style={{ maxHeight: 520, overflowY: 'auto' }}>
                {filteredProducts.map((p) => (
                  <div
                    key={p}
                    onClick={() => selectProduct(p)}
                    style={{
                      cursor: 'pointer', padding: '6px 12px', display: 'flex',
                      justifyContent: 'space-between', alignItems: 'center',
                      borderRadius: 4, marginBottom: 2,
                      background: p === activeProductName ? '#e6f4ff' : undefined,
                    }}
                  >
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p}</span>
                    <Badge count={docsOf(p).length} showZero color="#1677ff" />
                  </div>
                ))}
                {filteredProducts.length === 0 && <Empty description="无匹配产品" />}
              </div>
            )}
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" title={activeProductName ? `产品代码（${codes.length}）` : '产品代码'}>
            {!activeProductName ? (
              <Empty description="先在左侧选择产品名称" />
            ) : (
              <div style={{ maxHeight: 520, overflowY: 'auto' }}>
                {codes.map((c) => {
                  const fileCount = docsOf(activeProductName).filter((d) => d.product_code === c).length
                  return (
                    <div
                      key={c}
                      onClick={() => selectCode(c)}
                      style={{
                        cursor: 'pointer', padding: '6px 12px', display: 'flex',
                        justifyContent: 'space-between', alignItems: 'center',
                        borderRadius: 4, marginBottom: 2,
                        background: c === activeCodeName ? '#e6f4ff' : undefined,
                      }}
                    >
                      <span style={{ flex: 1 }}>{c}</span>
                      <Badge count={fileCount} showZero color="#1677ff" />
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        </Col>
        <Col span={14}>
          <Card
            size="small"
            title="SOP 项目行"
            extra={
              <Select
                size="small"
                style={{ width: 220 }}
                placeholder="选择文件"
                value={activeDoc?.id}
                onChange={setActiveDocId}
                options={codeDocs.map((d) => ({ label: `${d.file_no}（${d.version || '-'}）`, value: d.id }))}
              />
            }
          >
            {!activeDoc ? (
              <Empty description="选择产品名称与产品代码查看 SOP 项目行" />
            ) : (
              <div className="space-y-3">
                <Descriptions
                  size="small"
                  column={3}
                  items={[
                    { label: '文件编号', children: activeDoc.file_no },
                    { label: '产品代码', children: activeDoc.product_code || '-' },
                    { label: '版本', children: activeDoc.version || '-' },
                    { label: '规格', children: activeDoc.specification || '-' },
                    { label: '有效期', children: activeDoc.valid_years || '-' },
                    {
                      label: '绑定模板',
                      children: activeDoc.template_path ? <Tag color="green">{activeDoc.template_path}</Tag> : <Tag color="orange">未绑定</Tag>,
                    },
                  ]}
                />
                <Space>
                  <Button size="small" icon={<LinkOutlined />} onClick={() => openBindModal(activeDoc)}>
                    {activeDoc.template_path ? '更换模板' : '绑定模板'}
                  </Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openDocModal(activeDoc)}>编辑文档</Button>
                  <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => openItemModal()}>添加标准行</Button>
                  <Popconfirm title="确认删除该标准文档及其全部标准行?" onConfirm={() => handleDocDelete(activeDoc.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />}>删除文档</Button>
                  </Popconfirm>
                </Space>
                <Table
                  rowKey="id"
                  size="small"
                  loading={loading}
                  columns={itemColumns}
                  dataSource={items}
                  pagination={false}
                />
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <ImportConfirmModal
        key={importKey}
        open={importOpen}
        draft={importDraft}
        confirming={confirming}
        onCancel={() => { setImportOpen(false); setImportDraft(null) }}
        onConfirm={handleImportConfirm}
      />

      <Modal
        title={editingDoc ? '编辑标准文档' : '新建标准文档'}
        open={docModalOpen}
        onCancel={() => setDocModalOpen(false)}
        onOk={handleDocSave}
        okText="保存"
        width={600}
      >
        <Form form={docForm} layout="vertical" className="mt-4">
          <Row gutter={12}>
            <Col span={12}><Form.Item name="file_no" label="文件编号" rules={[{ required: true, message: '请输入文件编号' }]}><Input placeholder="SOP.02.3292.003" /></Form.Item></Col>
            <Col span={12}><Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '请输入产品名称' }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="product_code" label="产品代码"><Input placeholder="HAS" /></Form.Item></Col>
            <Col span={8}><Form.Item name="product_internal_code" label="产品代码"><Input placeholder="30205" /></Form.Item></Col>
            <Col span={8}><Form.Item name="version" label="版本"><Input placeholder="003" /></Form.Item></Col>
            <Col span={8}><Form.Item name="specification" label="规格"><Input placeholder="5kg/听" /></Form.Item></Col>
            <Col span={8}><Form.Item name="valid_years" label="有效期"><Input placeholder="36个月" /></Form.Item></Col>
            <Col span={8}><Form.Item name="effective_date" label="生效日期"><Input placeholder="2026年07月27日" /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title={editingItem ? '编辑标准行' : '添加标准行'}
        open={itemModalOpen}
        onCancel={() => setItemModalOpen(false)}
        onOk={handleItemSave}
        okText="保存"
        width={640}
      >
        <Form form={itemForm} layout="vertical" className="mt-4">
          <Row gutter={12}>
            <Col span={8}><Form.Item name="seq" label="序号"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={16}><Form.Item name="item_name" label="子项目名称" rules={[{ required: true, message: '请输入子项目名称' }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="sop_no" label="SOP号（匹配键）" rules={[{ required: true, message: '请输入 SOP 号' }]}><Input placeholder="SOP.03.5214" /></Form.Item></Col>
            <Col span={12}><Form.Item name="standard_text" label="合格标准原文" rules={[{ required: true, message: '请输入标准' }]}><Input placeholder="≤3.0%" /></Form.Item></Col>
            <Col span={8}>
              <Form.Item name="operator" label="运算符" initialValue="≤">
                <Select options={[{ value: '≤', label: '≤' }, { value: '≥', label: '≥' }, { value: '<', label: '<' }, { value: '>', label: '>' }, { value: '范围', label: '范围' }]} />
              </Form.Item>
            </Col>
            <Col span={8}><Form.Item name="limit_min" label="下限"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="limit_max" label="上限"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="method_source" label="方法来源"><Input placeholder="IP / Ph.Eur. / 内部" /></Form.Item></Col>
            <Col span={12}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title={bindDoc ? `绑定 COA 模板 —— ${bindDoc.product_code || ''}（${bindDoc.file_no}）` : '绑定 COA 模板'}
        open={bindOpen}
        onCancel={() => setBindOpen(false)}
        onOk={handleBindSave}
        okText="保存"
        width={560}
      >
        <div className="mt-4 space-y-3">
          <Text type="secondary">
            模板号码与 SOP 号码相近的自动排在前面；请先在「📑 报告模板」页上传模板，再回到这里绑定。
          </Text>
          <Select
            showSearch
            style={{ width: '100%' }}
            placeholder="选择模板路径"
            value={bindValue}
            onChange={setBindValue}
            options={bindOptions}
          />
        </div>
      </Modal>
    </div>
  )
}
