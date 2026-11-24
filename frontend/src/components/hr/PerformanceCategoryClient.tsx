'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Space, Switch, Table, Tag, Tooltip } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined } from '@ant-design/icons'
import { fetchPerformanceCategories, createPerformanceCategory, updatePerformanceCategory, deletePerformanceCategory, fetchDeptWeights, saveDeptWeights, fetchDepartmentsAction } from '@/actions/hr'

export default function PerformanceCategoryClient() {
  const { message } = App.useApp()
  const [cats, setCats] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  // 新增/编辑项目保存中（Modal confirmLoading，避免连点重复提交）
  const [saving, setSaving] = useState(false)
  // 初始化默认项目中（按钮 loading，避免连点重复创建）
  const [initializing, setInitializing] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setCats((await fetchPerformanceCategories()).data || []) }
    catch (e: any) { message.error('加载失败: ' + (e?.message || String(e))) }
    finally { setLoading(false) }
  }

  const initDefaults = async () => {
    setInitializing(true)
    const defaults = [
      { name: '环保权重比', weight: 15, sort_order: 0 },
      { name: '安全权重', weight: 15, sort_order: 1 },
      { name: '质量权重', weight: 20, sort_order: 2 },
      { name: '人才建设权重', weight: 15, sort_order: 3 },
      { name: '生产权重比', weight: 20, sort_order: 4 },
      { name: '部门综合事项权重', weight: 15, sort_order: 5 },
    ]
    let failed = 0
    for (const d of defaults) {
      try { await createPerformanceCategory(d) } catch { failed++ }
    }
    if (failed > 0) message.warning(`初始化完成，但 ${failed} 个项目创建失败，请检查后重试`)
    else message.success('默认项目已初始化')
    setInitializing(false)
    load()
  }

  // 部门权重管理
  const [deptModalOpen, setDeptModalOpen] = useState(false)
  const [deptCategory, setDeptCategory] = useState<any>(null)
  const [deptWeights, setDeptWeights] = useState<Record<string, number>>({})
  const [deptList, setDeptList] = useState<string[]>([])
  // 部门权重保存中（Modal confirmLoading）
  const [deptSaving, setDeptSaving] = useState(false)

  const openDeptWeights = async (cat: any) => {
    setDeptCategory(cat)
    try {
      const [depsRes, dwRes] = await Promise.all([
        fetchDepartmentsAction({ page_size: 200 }),
        fetchDeptWeights(cat.id),
      ])
      setDeptList((depsRes.data || []).map((d: any) => d.name))
      const map: Record<string, number> = {}
      for (const dw of dwRes.data || []) map[dw.department] = dw.weight
      setDeptWeights(map)
    } catch { message.error('加载部门列表失败') }
    setDeptModalOpen(true)
  }

  const saveDeptWeightsHandler = async () => {
    setDeptSaving(true)
    try {
      const weights = Object.entries(deptWeights).map(([dept, w]) => ({ department: dept, weight: w }))
      await saveDeptWeights(deptCategory.id, weights)
      message.success('部门权重已保存')
      setDeptModalOpen(false)
    } catch { message.error('保存失败') }
    finally { setDeptSaving(false) }
  }
  // load 捕获了 message，不能进依赖数组（它每次渲染都会重建，进 deps 会无限加载）
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [])

  const handleSave = async () => {
    // 校验失败只走表单行内提示
    let vals: { name: string; weight: number; evaluator?: string; sort_order?: number; is_active?: boolean }
    try {
      vals = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      if (editing) {
        await updatePerformanceCategory(editing.id, vals)
        message.success('已更新')
      } else {
        await createPerformanceCategory(vals)
        message.success('已创建')
      }
      setModalOpen(false); setEditing(null); form.resetFields(); load()
    } catch (e: any) { message.error(e.message || '保存失败') }
    finally { setSaving(false) }
  }

  return (
    // 页面已有 PageHeader「考核项目配置」，卡片不再重复标题
    <Card extra={
      <Button icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新增项目</Button>
    }>
      {!loading && cats.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          <p className="mb-2">暂无考核项目</p>
          <p className="mb-4 text-sm">将自动创建：环保/安全/质量/人才/生产/综合 六个项目</p>
          <Button type="primary" loading={initializing} onClick={initDefaults}>初始化默认项目</Button>
        </div>
      )}
      {cats.length > 0 && <Table rowKey="id" loading={loading} dataSource={cats} pagination={false}
        columns={[
          { title: '排序', dataIndex: 'sort_order', width: 60 },
          { title: '项目名称', dataIndex: 'name', width: 160 },
          { title: '权重', dataIndex: 'weight', width: 70, render: (v: number) => `${v ?? 0}%` },
          { title: '负责人', dataIndex: 'evaluator', width: 100, render: (v: any) => v || '—' },
          { title: '启用', dataIndex: 'is_active', width: 60, render: (v: boolean) => v ? <Tag color="success">启用</Tag> : <Tag color="default">停用</Tag> },
          { title: '操作', width: 200, render: (_: any, r: any) => <Space>
            <Button size="small" icon={<SettingOutlined />} onClick={() => openDeptWeights(r)}>部门权重</Button>
            <Tooltip title="编辑">
              <Button size="small" icon={<EditOutlined />} aria-label={`编辑「${r.name}」`} onClick={() => { setEditing(r); form.setFieldsValue(r); setModalOpen(true) }} />
            </Tooltip>
            <Popconfirm title="确认删除？" onConfirm={async () => {
              try { await deletePerformanceCategory(r.id); load() }
              catch (e: any) { message.error(e?.message || '删除失败') }
            }}>
              <Tooltip title="删除">
                <Button size="small" danger icon={<DeleteOutlined />} aria-label={`删除「${r.name}」`} />
              </Tooltip>
            </Popconfirm>
          </Space> },
        ]}
      />}
      <Modal title={editing ? '编辑项目' : '新增项目'} open={modalOpen} onOk={handleSave} onCancel={() => setModalOpen(false)} confirmLoading={saving}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}><Input placeholder="如：环保权重比" /></Form.Item>
          <Form.Item name="weight" label="权重(%)" rules={[{ required: true, message: '请输入权重' }]}><InputNumber min={0} max={100} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="evaluator" label="项目负责人"><Input placeholder="负责人姓名" /></Form.Item>
          <Form.Item name="sort_order" label="排序"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          {/* 新建默认启用（initialValue），编辑时回填实际状态；后端创建接口已接收 is_active */}
          <Form.Item name="is_active" label="启用" valuePropName="checked" initialValue={true}><Switch /></Form.Item>
        </Form>
      </Modal>
      <Modal title={`${deptCategory?.name || ''} - 部门权重配置`} open={deptModalOpen} onOk={saveDeptWeightsHandler} onCancel={() => setDeptModalOpen(false)} confirmLoading={deptSaving} width={600}>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full border-collapse border">
            <thead><tr className="bg-gray-50"><th className="border p-2 text-left">部门</th><th className="border p-2" style={{ width: 120 }}>权重(%)</th></tr></thead>
            <tbody>
              {deptList.map(dept => (
                <tr key={dept}>
                  <td className="border p-2">{dept}</td>
                  <td className="border p-2">
                    <InputNumber min={0} max={100} value={deptWeights[dept] ?? deptCategory?.weight ?? 0}
                      onChange={(v) => setDeptWeights(prev => ({ ...prev, [dept]: v || 0 }))}
                      style={{ width: '100%' }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Modal>
    </Card>
  )
}
