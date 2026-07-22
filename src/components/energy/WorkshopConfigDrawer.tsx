'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Button, Space, Switch, Modal, Tag, Checkbox } from 'antd'
import { UserAddOutlined } from '@ant-design/icons'
import { useEnergyStore } from '@/stores/energy'
import {
  createWorkshopConfig,
  updateWorkshopConfig,
  getWorkshopConfigById,
  getWorkshopPersonnelCandidates,
} from '@/actions/energy'
import type { CreateWorkshopConfigInput, UpdateWorkshopConfigInput, EnergyPersonnelCandidate } from '@/types/energy'

interface WorkshopConfigDrawerProps {
  onRefresh?: () => void
}

export function WorkshopConfigDrawer({ onRefresh }: WorkshopConfigDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)

  const {
    workshopConfigDrawerOpen,
    workshopConfigDrawerMode,
    workshopConfigDrawerId,
    closeWorkshopConfigDrawer,
  } = useEnergyStore()

  const isEdit = workshopConfigDrawerMode === 'edit'

  // 负责人多选
  const [selectedHeads, setSelectedHeads] = useState<{ name: string; feishu_open_id: string }[]>([])
  const [candidates, setCandidates] = useState<EnergyPersonnelCandidate[]>([])
  const [personnelModalOpen, setPersonnelModalOpen] = useState(false)
  const [personnelSearch, setPersonnelSearch] = useState('')

  const loadCandidates = useCallback(async () => {
    try {
      const data = await getWorkshopPersonnelCandidates()
      setCandidates(data)
    } catch {
      message.error('获取人员列表失败')
    }
  }, [message])

  useEffect(() => {
    if (!workshopConfigDrawerOpen) return
    const timer = setTimeout(() => {
      if (isEdit && workshopConfigDrawerId) {
        getWorkshopConfigById(workshopConfigDrawerId)
          .then((config) => {
            form.setFieldsValue({
              workshop: config.workshop,
              auto_notify_enabled: config.auto_notify_enabled,
              is_enabled: config.is_enabled,
            })
            setSelectedHeads(config.heads || [])
          })
          .catch(() => {
            message.error('获取车间配置失败')
          })
      } else {
        form.resetFields()
        form.setFieldsValue({
          auto_notify_enabled: true,
          is_enabled: true,
        })
        setSelectedHeads([])
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [workshopConfigDrawerOpen, workshopConfigDrawerId, isEdit, form, message])

  const openPersonnelSelect = async () => {
    setPersonnelSearch('')
    if (candidates.length === 0) {
      await loadCandidates()
    }
    setPersonnelModalOpen(true)
  }

  const toggleCandidate = (c: EnergyPersonnelCandidate, checked: boolean) => {
    if (checked) {
      setSelectedHeads((prev) => {
        if (prev.some((h) => h.feishu_open_id === c.feishu_open_id)) return prev
        return [...prev, { name: c.name, feishu_open_id: c.feishu_open_id }]
      })
    } else {
      setSelectedHeads((prev) => prev.filter((h) => h.feishu_open_id !== c.feishu_open_id))
    }
  }

  const removeHead = (head: { name: string; feishu_open_id: string }) => {
    setSelectedHeads((prev) => prev.filter((h) => h.feishu_open_id !== head.feishu_open_id))
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      if (isEdit && workshopConfigDrawerId) {
        const data: UpdateWorkshopConfigInput = {
          workshop: values.workshop,
          heads: selectedHeads,
          auto_notify_enabled: values.auto_notify_enabled,
          is_enabled: values.is_enabled,
        }
        await updateWorkshopConfig(workshopConfigDrawerId, data)
        message.success('更新成功')
      } else {
        const data: CreateWorkshopConfigInput = {
          workshop: values.workshop,
          heads: selectedHeads,
          auto_notify_enabled: values.auto_notify_enabled ?? true,
          is_enabled: values.is_enabled ?? true,
        }
        await createWorkshopConfig(data)
        message.success('创建成功')
      }
      closeWorkshopConfigDrawer()
      onRefresh?.()
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      if (err instanceof Error) message.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const filteredCandidates = personnelSearch
    ? candidates.filter(
        (c) =>
          c.name.includes(personnelSearch) ||
          (c.department || '').includes(personnelSearch)
      )
    : candidates

  return (
    <>
      <Drawer
        title={isEdit ? '编辑车间预警配置' : '新建车间预警配置'}
        size={520}
        open={workshopConfigDrawerOpen}
        onClose={closeWorkshopConfigDrawer}
        destroyOnHidden
        styles={{
          header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
          body: { padding: '24px' },
        }}
        extra={
          <Space>
            <Button
              onClick={closeWorkshopConfigDrawer}
              style={{ color: '#37352f', borderColor: '#c8c4be', borderRadius: 8, height: 36, fontSize: 14, fontWeight: 500 }}
            >
              取消
            </Button>
            <Button
              type="primary"
              loading={submitting}
              onClick={handleSubmit}
              style={{ background: '#5645d4', borderColor: '#5645d4', borderRadius: 8, height: 36, fontSize: 14, fontWeight: 500, boxShadow: 'none' }}
            >
              {isEdit ? '保存' : '创建'}
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="workshop" label="车间名称" rules={[{ required: true, message: '请输入车间名称' }]}>
            <Input placeholder="如：发酵车间" style={{ height: 44, borderRadius: 8 }} />
          </Form.Item>

          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8, color: '#37352f', fontSize: 14 }}>预警负责人</div>
            <Space wrap style={{ marginBottom: 8 }}>
              {selectedHeads.map((h) => (
                <Tag
                  key={h.feishu_open_id}
                  closable
                  onClose={(e) => {
                    e.preventDefault()
                    removeHead(h)
                  }}
                  color="blue"
                >
                  {h.name}
                </Tag>
              ))}
            </Space>
            <Button
              type="dashed"
              icon={<UserAddOutlined />}
              onClick={openPersonnelSelect}
              block
              style={{ borderRadius: 8, height: 40 }}
            >
              {selectedHeads.length === 0 ? '从人员表选择负责人' : '添加负责人'}
            </Button>
          </div>

          <div style={{ display: 'flex', gap: 32 }}>
            <Form.Item name="auto_notify_enabled" label="自动通知" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="is_enabled" label="启用配置" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>

          <div style={{ padding: '12px 16px', background: '#f6f3ff', borderRadius: 8, color: '#787671', fontSize: 13, lineHeight: 1.6, marginTop: 8 }}>
            系统将在每日定时检查该车间昨日各类能耗是否超过近 30 天均值的 115%，触发时通过飞书自动通知负责人。
          </div>
        </Form>
      </Drawer>

      {/* 多选负责人 Modal */}
      <Modal
        title="选择预警负责人"
        open={personnelModalOpen}
        onCancel={() => setPersonnelModalOpen(false)}
        onOk={() => setPersonnelModalOpen(false)}
        okText={`确定 (已选 ${selectedHeads.length} 人)`}
        cancelText="取消"
        width={500}
      >
        <Input
          placeholder="搜索姓名或部门..."
          value={personnelSearch}
          onChange={(e) => setPersonnelSearch(e.target.value)}
          style={{ marginBottom: 12 }}
          allowClear
        />
        <div style={{ maxHeight: 400, overflow: 'auto' }}>
          {filteredCandidates.slice(0, 200).map((c) => (
            <div
              key={c.feishu_open_id}
              style={{
                padding: '6px 12px',
                borderBottom: '1px solid #f0f0f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Checkbox
                checked={selectedHeads.some((h) => h.feishu_open_id === c.feishu_open_id)}
                onChange={(e) => toggleCandidate(c, e.target.checked)}
              >
                <span style={{ fontWeight: 500 }}>{c.name}</span>
                <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>{c.department || '-'}</span>
              </Checkbox>
            </div>
          ))}
          {filteredCandidates.length === 0 && (
            <div style={{ textAlign: 'center', color: '#bbb', padding: 24 }}>无匹配人员</div>
          )}
        </div>
      </Modal>
    </>
  )
}
