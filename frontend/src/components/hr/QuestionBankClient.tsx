'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Upload,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { fetchQuestionBank, API_BASE } from '@/lib/hr'
import { addQuestionBankItems, deleteQuestionBankItem } from '@/actions/hr'
import { QuestionBankItem } from '@/types/hr'

export default function QuestionBankClient() {
  const { message } = App.useApp()

  const [items, setItems] = useState<QuestionBankItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [fileNo, setFileNo] = useState('')
  const [keyword, setKeyword] = useState('')

  const [addOpen, setAddOpen] = useState(false)
  const [addForm] = Form.useForm()

  const loadBank = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const res = await fetchQuestionBank({ file_no: fileNo, keyword, page: p, page_size: 50 })
      setItems(res.data || [])
      setTotal(res.meta?.total || 0)
      setPage(p)
    } catch (err: any) { message.error(err.message || '检索失败') }
    finally { setLoading(false) }
  }, [fileNo, keyword, message])

  useEffect(() => { loadBank(1) }, [loadBank])

  const handleAdd = async () => {
    const values = await addForm.validateFields()
    try {
      const res = await addQuestionBankItems([values])
      message.success(res.message || '已入库')
      setAddOpen(false)
      addForm.resetFields()
      loadBank(page)
    } catch (err: any) { message.error(err.message || '入库失败') }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">共享题库</h1>
          <p className="text-[14px] text-[var(--color-steel)]">按 SOP 编号沉淀考题，供培训出题复用</p>
        </div>
        <Space>
          <Upload accept=".docx" showUploadList={false}
            beforeUpload={async (file) => {
              const fd = new FormData(); fd.append('file', file as File)
              setLoading(true)
              try {
                const r = await fetch(`${API_BASE}/api/v1/hr/question-bank/import-docx`, {
                  method: 'POST', body: fd, credentials: 'include',
                })
                const d = await r.json()
                if (!r.ok) throw new Error(d.message || d.detail || `HTTP ${r.status}`)
                message.success(d.message || '导入成功')
                loadBank(1)
              } catch (err: any) { message.error(err.message || '导入失败'); setLoading(false) }
              return false
            }}
          >
            <Button icon={<UploadOutlined />}>导入历史记录表</Button>
          </Upload>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>手工添加</Button>
        </Space>
      </div>

      <Card>
        <Space wrap className="mb-3">
          <Input placeholder="SOP/文件编号" value={fileNo} onChange={e => setFileNo(e.target.value)}
            style={{ width: 180 }} allowClear />
          <Input placeholder="题干/主题关键词" value={keyword} onChange={e => setKeyword(e.target.value)}
            style={{ width: 220 }} allowClear />
          <Button icon={<SearchOutlined />} onClick={() => loadBank(1)}>搜索</Button>
        </Space>
        <Table rowKey="id" loading={loading} dataSource={items}
          pagination={{ current: page, pageSize: 50, total, onChange: (p) => loadBank(p) }}
          columns={[
            { title: '文件编号', dataIndex: 'file_no', width: 150 },
            { title: '考题', dataIndex: 'question', ellipsis: true },
            { title: '答案', dataIndex: 'answer', ellipsis: true, width: 200 },
            { title: '分', dataIndex: 'score', width: 50, align: 'center' as const },
            { title: '来源', dataIndex: 'source', width: 84,
              render: (v: string) => <Tag color={v === 'AI生成' ? 'purple' : v === '历史导入' ? 'orange' : 'blue'}>{v}</Tag> },
            { title: '使用次数', dataIndex: 'usage_count', width: 80, align: 'center' as const },
            { title: '最近使用', dataIndex: 'last_used_date', width: 100 },
            { title: '操作', width: 60,
              render: (_: any, item: QuestionBankItem) => (
                <Popconfirm title="确认删除该题？" onConfirm={async () => {
                  try { await deleteQuestionBankItem(item.id); message.success('已删除'); loadBank(page) }
                  catch (err: any) { message.error(err.message || '删除失败') }
                }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Modal title="手工添加题目" open={addOpen} onCancel={() => setAddOpen(false)} onOk={handleAdd} width={520}>
        <Form form={addForm} layout="vertical" initialValues={{ score: 10 }}>
          <Form.Item name="file_no" label="文件编号（SOP编号）">
            <Input placeholder="如：SOP.13.2111.010" />
          </Form.Item>
          <Form.Item name="question" label="考题" rules={[{ required: true, message: '请填写考题' }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="answer" label="答案">
            <Input.TextArea rows={3} />
          </Form.Item>
          <div className="grid grid-cols-2 gap-3">
            <Form.Item name="score" label="分值">
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="subject" label="培训内容/主题">
              <Input placeholder="选填" />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
