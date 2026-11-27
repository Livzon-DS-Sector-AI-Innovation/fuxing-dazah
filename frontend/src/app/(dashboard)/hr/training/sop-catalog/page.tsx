'use client'

import { useEffect, useState, useMemo } from 'react'
import { Select, Collapse, Tag, Spin, Empty, Button, App, Input, Modal, Form, Popconfirm, Upload, Space, Tooltip } from 'antd'
import { SearchOutlined, PlusOutlined, DeleteOutlined, UploadOutlined } from '@ant-design/icons'

import { fetchSopDepartments, fetchSopCatalog, uploadSopCatalog, deletePositionByName, deleteSopItem, createPositionTraining, fetchPositions } from '@/actions/hr'
import PageHeader from '@/components/hr/PageHeader'

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
  const { message, modal } = App.useApp()
  const [allData, setAllData] = useState<SopItem[]>([])
  const [loading, setLoading] = useState(false)
  const [departments, setDepartments] = useState<string[]>([])
  const [selectedDept, setSelectedDept] = useState<string | undefined>()
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [positions, setPositions] = useState<string[]>([])

  // 加载部门列表
  useEffect(() => {
    fetchSopDepartments()
      .then(res => setDepartments(res.data || []))
      .catch(() => message.error('加载SOP部门列表失败'))
  }, [])

  // 加载全部数据
  const loadAll = async () => {
    setLoading(true)
    try {
      let all: SopItem[] = []
      let page = 1
      while (true) {
        const d = await fetchSopCatalog({ department: selectedDept, page, page_size: 200 })
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
      <PageHeader
        // 与左侧菜单名逐字一致（菜单是「SOP目录」）
        title="SOP目录"
        actions={
          <Space>
            <Upload accept=".xlsx,.xls,.doc,.docx" showUploadList={false} customRequest={async ({ file }) => {
              const fd = new FormData(); fd.append('file', file as File)
              try {
                const d = await uploadSopCatalog(fd)
                if (d.data.errors?.length) {
                  modal.warning({ title: `上传完成但有${d.data.errors.length}条错误`, content: <ul>{d.data.errors.slice(0,10).map((e:string,i:number)=><li key={i}>{e}</li>)}</ul>, width: 500 })
                }
                message.success(`上传完成：新增${d.data.created}，更新${d.data.updated}`); loadAll()
              } catch (err) { message.error((err as Error)?.message || '上传失败') }
            }}>
              <Tooltip title="支持 Excel 或 GMP 文件目录 Word 文档（.doc/.docx），自动解析大分类与SOP编号">
                <Button icon={<UploadOutlined />}>上传SOP</Button>
              </Tooltip>
            </Upload>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新建职位SOP</Button>
          </Space>
        }
      />

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
                      try { await deletePositionByName(posName, selectedDept || ''); message.success('已删除'); loadAll() }
                      catch { message.error('删除失败') }
                    }}>
                      <Tooltip title="删除岗位">
                        <Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label="删除岗位" style={{ marginLeft: 8 }} />
                      </Tooltip>
                    </Popconfirm>
                  </span>
                }
              >
                {catEntries.sort((a, b) => a[0].localeCompare(b[0])).map(([catName, sops]) => (
                  <div key={catName} className="inline-block mr-2 mb-2">
                    {/*
                      类别标签上的「×」会删除该类别下全部 SOP：必须先确认
                      （此前 closable 的 onClose 直接逐条删除，点一下叉就全没了）
                    */}
                    <Popconfirm
                      title={`删除培训类别「${catName}」？`}
                      description={`将删除该类别下 ${sops.length} 条 SOP，不可恢复。`}
                      okText="删除"
                      okButtonProps={{ danger: true }}
                      onConfirm={async () => {
                        let failed = 0
                        for (const s of sops) {
                          try { await deleteSopItem(s.id) } catch { failed++ }
                        }
                        if (failed > 0) message.error(`删除「${catName}」：${sops.length - failed} 条成功，${failed} 条失败，请重试`)
                        else message.success(`已删除「${catName}」`)
                        loadAll()
                      }}
                    >
                      <Tag color="blue" closable onClose={(e) => e.preventDefault()} style={{ cursor: 'pointer' }}>{catName}</Tag>
                    </Popconfirm>
                  </div>
                ))}
              </Collapse.Panel>
            )
          })}
        </Collapse>
      )}

      {/* 不加 forceRender：关闭状态下预渲染会让服务端与客户端输出不一致（hydration 报错），表单方法只在弹窗打开后才调用 */}
      <Modal title="新建培训分类" open={modalOpen} onCancel={() => setModalOpen(false)}
        mask={{ closable: false }}
        onOk={async () => {
          const vals = await form.validateFields()
          const payload = {
            ...vals,
            file_name: vals.file_name || vals.training_category,
          }
          setSaving(true)
          try {
            await createPositionTraining(payload)
            message.success('创建成功'); setModalOpen(false); form.resetFields(); loadAll()
          } catch (err) { message.error((err as Error)?.message || '创建失败') }
          finally { setSaving(false) }
        }} okText="创建" confirmLoading={saving}>
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item name="department" label="部门" rules={[{ required: true }]}>
            <Select placeholder="选择部门" showSearch options={departments.map(d => ({value:d,label:d}))}
              onChange={async (dept) => {
                const list = await fetchPositions(dept)
                setPositions(list.map((p) => p.name))
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
