'use client'

import { useEffect, useState, useMemo } from 'react'
import { Select, Collapse, Tag, Spin, Empty, Button, App, Input, Modal, Form, Popconfirm, Upload, Space } from 'antd'
import { SearchOutlined, PlusOutlined, DeleteOutlined, UploadOutlined } from '@ant-design/icons'

import { API_BASE } from '@/lib/hr'

interface SopItem {
  id: string
  file_name: string
  sop_number: string | null
  category: string
  department: string
  position_name: string | null
}

interface PositionGroup {
  name: string
  categories: Record<string, SopItem[]>
}

export default function SopCatalogPage() {
  const { message } = App.useApp()
  const [allData, setAllData] = useState<SopItem[]>([])
  const [loading, setLoading] = useState(false)
  const [departments, setDepartments] = useState<string[]>([])
  const [selectedDept, setSelectedDept] = useState<string | undefined>()
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [positions, setPositions] = useState<string[]>([])

  // 加载部门列表
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/departments`)
      .then(r => r.json())
      .then(res => setDepartments(res.data || []))
      .catch(() => {})
  }, [])

  // 加载全部数据
  const loadAll = async () => {
    setLoading(true)
    try {
      let all: SopItem[] = []
      let page = 1
      while (true) {
        const params = new URLSearchParams()
        params.set('page', String(page))
        params.set('page_size', '200')
        if (selectedDept) params.set('department', selectedDept)
        const res = await fetch(`${API_BASE}/api/v1/hr/sop-catalog?${params}`)
        const d = await res.json()
        const items = d.data || []
        all = all.concat(items)
        if (items.length < 200) break
        page++
      }
      setAllData(all)
    } catch { message.error('加载SOP目录失败') }
    finally { setLoading(false) }
  }

  useEffect(() => { loadAll() }, [selectedDept])

  // 按岗位分组
  const grouped = useMemo(() => {
    const groups: Record<string, PositionGroup> = {}
    for (const item of allData) {
      const posName = item.position_name || '未分类'
      if (!groups[posName]) {
        groups[posName] = { name: posName, categories: {} }
      }
      const cat = item.category || '其他'
      if (!groups[posName].categories[cat]) {
        groups[posName].categories[cat] = []
      }
      // 过滤搜索
      if (search && !item.file_name.toLowerCase().includes(search.toLowerCase()) &&
          !(item.sop_number || '').toLowerCase().includes(search.toLowerCase())) {
        continue
      }
      groups[posName].categories[cat].push(item)
    }
    // 删除空分组
    for (const key of Object.keys(groups)) {
      const cats = groups[key].categories
      for (const ck of Object.keys(cats)) {
        if (cats[ck].length === 0) delete cats[ck]
      }
      if (Object.keys(cats).length === 0) delete groups[key]
    }
    return groups
  }, [allData, search])

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">SOP 目录</h1>
        <Space>
          <Upload accept=".xlsx,.xls" showUploadList={false} customRequest={async ({ file }) => {
            const fd = new FormData(); fd.append('file', file as File)
            try {
              const res = await fetch(`${API_BASE}/api/v1/hr/sop-catalog/upload`, { method: 'POST', body: fd })
              const d = await res.json()
              if (res.ok) {
                if (d.data.errors?.length) {
                  Modal.warning({ title: `上传完成但有${d.data.errors.length}条错误`, content: <ul>{d.data.errors.slice(0,10).map((e:string,i:number)=><li key={i}>{e}</li>)}</ul>, width: 500 })
                }
                message.success(`上传完成：新增${d.data.created}，更新${d.data.updated}`); loadAll()
              }
              else message.error(d.message || '上传失败')
            } catch { message.error('上传失败') }
          }}>
            <Button icon={<UploadOutlined />}>上传SOP</Button>
          </Upload>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新建职位SOP</Button>
        </Space>
      </div>

      <div className="flex gap-3 items-center flex-wrap">
        <Select placeholder="选择部门" allowClear value={selectedDept}
          onChange={setSelectedDept} options={departments.map(d => ({ value: d, label: d }))}
          style={{ width: 220 }} />
        <Input prefix={<SearchOutlined />} placeholder="搜索SOP编号或文件名" value={search}
          onChange={e => setSearch(e.target.value)} style={{ width: 280 }} allowClear />
        <Tag color="blue">{allData.length} 条记录</Tag>
        <Tag color="green">{Object.keys(grouped).length} 个岗位</Tag>
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><Spin size="large" /></div>
      ) : Object.keys(grouped).length === 0 ? (
        <Empty description="暂无SOP目录数据，请上传或新建" />
      ) : (
        <Collapse accordion>
          {Object.entries(grouped).sort((a, b) => a[0].localeCompare(b[0])).map(([posName, group]) => {
            const catEntries = Object.entries(group.categories)
            const totalSops = catEntries.reduce((sum, [, sops]) => sum + sops.length, 0)
            return (
              <Collapse.Panel
                key={posName}
                header={
                  <span onClick={e => e.stopPropagation()}>
                    <strong>{posName}</strong>
                    <Tag className="ml-2">{catEntries.length} 个培训类别</Tag>
                    <Tag color="blue">{totalSops} 条SOP</Tag>
                    <Popconfirm title={`删除岗位「${posName}」及其全部培训内容？`} onConfirm={async () => {
                      const res = await fetch(`${API_BASE}/api/v1/hr/positions/by-name/${encodeURIComponent(posName)}?department=${encodeURIComponent(selectedDept || '')}`, { method: 'DELETE' })
                      if (res.ok) { message.success('已删除'); loadAll() }
                      else message.error('删除失败')
                    }}>
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} style={{ marginLeft: 8 }} />
                    </Popconfirm>
                  </span>
                }
              >
                {catEntries.sort((a, b) => a[0].localeCompare(b[0])).map(([catName, sops]) => (
                  <div key={catName} className="inline-block mr-2 mb-2">
                    <Tag color="blue" closable onClose={async (e) => {
                      e.preventDefault()
                      for (const s of sops) {
                        await fetch(`${API_BASE}/api/v1/hr/sop-catalog/${s.id}`, { method: 'DELETE' })
                      }
                      message.success(`已删除「${catName}」`)
                      loadAll()
                    }}>{catName}</Tag>
                  </div>
                ))}
              </Collapse.Panel>
            )
          })}
        </Collapse>
      )}

      <Modal title="新建培训分类" open={modalOpen} forceRender onCancel={() => setModalOpen(false)}
        onOk={async () => {
          const vals = await form.validateFields()
          const payload = {
            ...vals,
            file_name: vals.file_name || vals.training_category,
          }
          const res = await fetch(`${API_BASE}/api/v1/hr/position-trainings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          })
          if (res.ok) { message.success('创建成功'); setModalOpen(false); form.resetFields(); loadAll() }
          else { const d = await res.json(); message.error(d.message || '创建失败') }
        }} okText="创建">
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item name="department" label="部门" rules={[{ required: true }]}>
            <Select placeholder="选择部门" showSearch options={departments.map(d => ({value:d,label:d}))}
              onChange={async (dept) => {
                const res = await fetch(`${API_BASE}/api/v1/hr/positions?department=${encodeURIComponent(dept)}`)
                const d = await res.json()
                setPositions((d.data || []).map((p: any) => p.name))
              }} />
          </Form.Item>
          <Form.Item name="position_name" label="岗位" rules={[{ required: true }]}>
            <Select placeholder="选择岗位" showSearch options={positions.map(p => ({value:p,label:p}))} />
          </Form.Item>
          <Form.Item name="training_category" label="培训类别" rules={[{ required: true }]}>
            <Input placeholder="如：岗位职责、文件管理、质量管理"
              onChange={e => { if (!form.getFieldValue('file_name')) form.setFieldValue('file_name', e.target.value) }} />
          </Form.Item>
          <Form.Item name="file_name" label="文件名称">
            <Input placeholder="默认与培训类别相同" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
