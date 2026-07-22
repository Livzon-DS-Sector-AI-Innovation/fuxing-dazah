'use client'

import { useState, useEffect } from 'react'
import { App, Drawer, Descriptions, Tag, Timeline, Button, Space, Input, Image, Upload, Select, InputNumber, Modal, Tooltip } from 'antd'
import {
  ClockCircleOutlined, UserOutlined, ToolOutlined, UploadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import { useEquipmentStore } from '@/stores/equipment'
import { assignWorkOrder, startWorkOrder, completeWorkOrder, verifyWorkOrder, closeWorkOrder, uploadWorkOrderImages } from '@/actions/equipment'
import { WorkOrderStatus, WorkOrderPriority, Personnel, SparePart } from '@/types/equipment'
import { fetchWorkOrderByIdClient, fetchAvailableSparePartsClient } from '@/lib/api/equipment-client'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import { PersonnelSelect } from '@/components/equipment'
import { MaterialRecordTable } from './MaterialRecordTable'
import { usePermission } from '@/hooks/usePermission'

const { TextArea } = Input

const statusConfig: Record<WorkOrderStatus, { color: string; label: string }> = {
  '待处理': { color: '#e03131', label: '待处理' },
  '执行中': { color: '#dd5b00', label: '执行中' },
  '待验收': { color: '#d4b106', label: '待验收' },
  '已完成': { color: '#1aae39', label: '已完成' },
  '已关闭': { color: '#787671', label: '已关闭' },
}

const priorityConfig: Record<WorkOrderPriority, { color: string }> = {
  '紧急': { color: '#e03131' },
  '高': { color: '#dd5b00' },
  '中': { color: '#5645d4' },
  '低': { color: '#787671' },
}

function formatDuration(minutes: number | null): string {
  if (minutes === null || minutes === undefined) return '-'
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins > 0 ? `${hours}小时${mins}分` : `${hours}小时`
}

function formatTime(time: string | null): string {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

interface WorkOrderDetailDrawerProps {
  onRefresh?: () => void
}

export function WorkOrderDetailDrawer({ onRefresh }: WorkOrderDetailDrawerProps) {
  const { message, modal } = App.useApp()
  const { workOrderDetailOpen, viewingWorkOrder, closeWorkOrderDetail, setViewingWorkOrder } = useEquipmentStore()
  const { hasPermission } = usePermission()

  const [personnel, setPersonnel] = useState<Personnel[]>([])

  // 完成弹窗状态
  const [completeOpen, setCompleteOpen] = useState(false)
  const [repairDetail, setRepairDetail] = useState('')
  const [fileList, setFileList] = useState<any[]>([])
  const [consumedParts, setConsumedParts] = useState<{ sparePartId: string; qty: number }[]>([])
  const [availableParts, setAvailableParts] = useState<SparePart[]>([])
  const [completeLoading, setCompleteLoading] = useState(false)

  const refreshDetail = async (id: string) => {
    try {
      const updated = await fetchWorkOrderByIdClient(id)
      setViewingWorkOrder(updated)
    } catch { /* 静默失败，列表刷新已覆盖 */ }
    onRefresh?.()
  }
  useEffect(() => {
    if (workOrderDetailOpen) {
      fetchPersonnelList({}).then(r => setPersonnel(r.items.filter(p => p.is_active))).catch(() => {})
    }
  }, [workOrderDetailOpen])

  if (!viewingWorkOrder) return null

  const wo = viewingWorkOrder
  const statusCfg = statusConfig[wo.status]
  const priorityCfg = priorityConfig[wo.priority]

  const handleAssign = () => {
    let assigneeId = ''
    modal.confirm({
      title: '指派维修人',
      content: (
        <div style={{ marginTop: 16 }}>
          <PersonnelSelect
            personnel={personnel}
            placeholder="选择维修人员"
            style={{ width: '100%' }}
            onChange={(val) => { assigneeId = val }}
          />
        </div>
      ),
      okText: '确认指派',
      cancelText: '取消',
      onOk: async () => {
        if (!assigneeId) { message.warning('请选择维修人员'); return }
        const result = await assignWorkOrder(wo.id, { assignee_id: assigneeId })
        if (!result.success) { message.error(result.error); return }
        message.success('指派成功')
        await refreshDetail(wo.id)
      },
    })
  }

  const handleStart = async () => {
    const result = await startWorkOrder(wo.id)
    if (!result.success) { message.error(result.error); return }
    message.success('已开始维修')
    await refreshDetail(wo.id)
  }

  const openCompleteModal = async () => {
    setRepairDetail('')
    setFileList([])
    setConsumedParts([])
    setAvailableParts([])
    setCompleteLoading(false)
    setCompleteOpen(true)
    try {
      const parts = await fetchAvailableSparePartsClient(wo.equipment_id)
      setAvailableParts(parts)
    } catch (e) {
      console.error('获取可用备件失败:', e)
      setAvailableParts([])
    }
  }

  const handleCompleteSubmit = async () => {
    if (!repairDetail.trim()) { message.warning('请填写维修过程描述'); return }
    setCompleteLoading(true)
    try {
      // 先提交工单（含备件消耗），避免图片已上传但工单提交失败导致脏数据
      const validParts = consumedParts.filter(p => p.sparePartId && p.qty > 0)
      const result = await completeWorkOrder(wo.id, {
        repair_detail: repairDetail,
        consumed_parts: validParts.length > 0
          ? validParts.map(p => ({ spare_part_id: p.sparePartId, quantity: p.qty }))
          : undefined,
      })
      if (!result.success) { message.error(result.error); return }

      // 工单提交成功后再上传图片
      if (fileList.length > 0) {
        const formData = new FormData()
        fileList.forEach(f => {
          const file = (f as any).originFileObj || f
          if (file instanceof File) formData.append('files', file)
        })
        const uploadResult = await uploadWorkOrderImages(wo.id, formData)
        if (!uploadResult.success) {
          message.warning('工单已提交，但图片上传失败: ' + (uploadResult.error || '未知错误'))
        }
      }

      message.success('已提交验收')
      setCompleteOpen(false)
      await refreshDetail(wo.id)
    } finally {
      setCompleteLoading(false)
    }
  }

  const handleVerify = (result: '合格' | '不合格') => {
    let remark = ''
    modal.confirm({
      title: result === '合格' ? '验收通过' : '验收不通过',
      content: (
        <div style={{ marginTop: 16 }}>
          {result === '不合格' && <div style={{ marginBottom: 8, fontSize: 14, color: '#37352f' }}>不通过原因 *</div>}
          <TextArea
            placeholder={result === '合格' ? '验收备注（可选）' : '请说明不通过的原因'}
            rows={3} maxLength={500} showCount
            onChange={(e) => { remark = e.target.value }}
          />
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      okButtonProps: result === '不合格' ? { danger: true } : {},
      onOk: async () => {
        if (result === '不合格' && !remark.trim()) { message.warning('请填写不通过原因'); return }
        const actionResult = await verifyWorkOrder(wo.id, { result, remark: remark || undefined })
        if (!actionResult.success) { message.error(actionResult.error); return }
        message.success(result === '合格' ? '验收通过' : '已打回重修')
        await refreshDetail(wo.id)
      },
    })
  }

  const handleClose = async () => {
    const result = await closeWorkOrder(wo.id)
    if (!result.success) { message.error(result.error); return }
    message.success('工单已关闭')
    await refreshDetail(wo.id)
  }

  const timelineItems = []
  if (wo.reported_at) {
    timelineItems.push({
      color: '#e03131',
      icon: <ClockCircleOutlined style={{ fontSize: 14 }} />,
      content: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>报修</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.reported_at)}</div>
        </div>
      ),
    })
  }
  if (wo.assigned_at) {
    timelineItems.push({
      color: '#5645d4',
      icon: <UserOutlined style={{ fontSize: 14 }} />,
      content: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>已指派</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.assigned_at)}</div>
        </div>
      ),
    })
  }
  if (wo.started_at) {
    timelineItems.push({
      color: '#dd5b00',
      icon: <ToolOutlined style={{ fontSize: 14 }} />,
      content: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>开始维修</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.started_at)}</div>
        </div>
      ),
    })
  }
  if (wo.completed_at) {
    timelineItems.push({
      color: '#d4b106',
      icon: <CheckCircleOutlined style={{ fontSize: 14 }} />,
      content: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>提交完成</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.completed_at)}</div>
          {wo.repair_detail && <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 4 }}>维修描述: {wo.repair_detail}</div>}
        </div>
      ),
    })
  }
  if (wo.verified_at) {
    timelineItems.push({
      color: wo.verification_result === '合格' ? '#1aae39' : '#e03131',
      icon: wo.verification_result === '合格'
        ? <CheckCircleOutlined style={{ fontSize: 14 }} />
        : <CloseCircleOutlined style={{ fontSize: 14 }} />,
      content: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>
            验收 - <Tag color={wo.verification_result === '合格' ? 'success' : 'error'}>{wo.verification_result}</Tag>
          </div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.verified_at)}</div>
          {wo.verification_remark && <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 4 }}>备注: {wo.verification_remark}</div>}
        </div>
      ),
    })
  }
  if (wo.status === '已关闭') {
    timelineItems.push({
      color: '#787671',
      icon: <StopOutlined style={{ fontSize: 14 }} />,
      content: <div><div style={{ fontWeight: 500, color: '#1a1a1a' }}>已关闭</div></div>,
    })
  }

  return (
    <Drawer
      title={
        <div className="flex items-center gap-3">
          <span style={{ fontWeight: 600 }}>{wo.work_order_no}</span>
          <Tag style={{ color: statusCfg.color, background: statusCfg.color + '18', border: 'none', borderRadius: 4, fontWeight: 500 }}>
            {statusCfg.label}
          </Tag>
        </div>
      }
      size={520}
      open={workOrderDetailOpen}
      onClose={closeWorkOrderDetail}
      destroyOnHidden
    >
      <Descriptions column={2} size="small" styles={{ label: { color: '#787671', fontSize: 13 }, content: { color: '#1a1a1a', fontSize: 14 } }}>
        <Descriptions.Item label="工单类型">
          <Tag style={{
            color: wo.order_type === '故障维修' || wo.order_type === '异常处理' ? '#dd5b00'
                 : wo.order_type === '日常维护' ? '#0075de'
                 : '#5645d4',
            background: wo.order_type === '故障维修' || wo.order_type === '异常处理' ? '#fff7e6'
                      : wo.order_type === '日常维护' ? '#dcecfa'
                      : '#ede9f7',
            border: 'none', borderRadius: 4,
          }}>{wo.order_type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="优先级">
          <span style={{ color: priorityCfg.color, fontWeight: 500 }}>{wo.priority}</span>
        </Descriptions.Item>
        <Descriptions.Item label="关联设备" span={2}>{wo.equipment_name || wo.equipment_id}</Descriptions.Item>
        <Descriptions.Item label="故障现象" span={2}>{wo.symptom_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="故障描述" span={2}>{wo.fault_description || '-'}</Descriptions.Item>
        <Descriptions.Item label="报修人">{wo.reporter_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="维修人">{wo.assignee_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="责任人">{wo.responsible_person_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="报修时间">{formatTime(wo.reported_at)}</Descriptions.Item>
        <Descriptions.Item label="维修耗时">{formatDuration(wo.actual_duration)}</Descriptions.Item>
      </Descriptions>

      {wo.images && wo.images.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', marginBottom: 12 }}>现场照片</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {wo.images.map((img) => (
              <Image
                key={img.id}
                src={`${process.env.NEXT_PUBLIC_API_BASE_URL || ''}/api/v1/equipment/maintenance/work-orders/${wo.id}/images/${img.id}/file`}
                alt={img.file_name}
                width={100}
                height={100}
                style={{ objectFit: 'cover', borderRadius: 6, cursor: 'pointer' }}
              />
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 24, marginBottom: 24 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', marginBottom: 16 }}>工单进度</div>
        <Timeline items={timelineItems} />
      </div>

      {/* 已关闭工单显示领料记录 */}
      {wo.status === '已关闭' && (
        <div style={{ marginTop: 24, marginBottom: 24 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', marginBottom: 12 }}>领料记录</div>
          <MaterialRecordTable workOrderId={wo.id} />
        </div>
      )}

      <div style={{ borderTop: '1px solid #ede9e4', paddingTop: 16 }}>
        <Space wrap>
          {wo.status === '待处理' && hasPermission('equipment:work_order:update') && (
            <>
              <Button type="primary" onClick={handleStart}>开始执行</Button>
              <Button onClick={handleAssign}>指派维修人</Button>
            </>
          )}
          {wo.status === '执行中' && hasPermission('equipment:work_order:update') && <Button type="primary" onClick={openCompleteModal}>提交完成</Button>}
          {wo.status === '待验收' && hasPermission('equipment:work_order:approve') && (
            <>
              <Button type="primary" onClick={() => handleVerify('合格')}>验收通过</Button>
              <Button danger onClick={() => handleVerify('不合格')}>打回重修</Button>
            </>
          )}
          {wo.status === '已完成' && hasPermission('equipment:work_order:update') && <Button onClick={handleClose}>关闭工单</Button>}
        </Space>
      </div>

      <Modal
        title="提交维修完成"
        open={completeOpen}
        width={640}
        onCancel={() => setCompleteOpen(false)}
        onOk={handleCompleteSubmit}
        confirmLoading={completeLoading}
        okText="提交验收"
        cancelText="取消"
        destroyOnHidden
        styles={{ body: { padding: '20px 24px' } }}
      >
        {/* ── 维修描述 ── */}
        <div style={{
          fontSize: 11, fontWeight: 600, color: '#a4a097',
          textTransform: 'uppercase', letterSpacing: 1,
          marginBottom: 10, marginTop: 4,
        }}>
          维修描述
        </div>
        <TextArea
          placeholder="请详细描述维修过程、处理措施和维修结果"
          rows={4}
          maxLength={1000}
          showCount
          value={repairDetail}
          onChange={(e) => setRepairDetail(e.target.value)}
          style={{ marginBottom: 24 }}
        />

        {/* ── 消耗备件 ── */}
        <div style={{
          fontSize: 11, fontWeight: 600, color: '#a4a097',
          textTransform: 'uppercase', letterSpacing: 1,
          marginBottom: 10,
        }}>
          消耗备件
          <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: '#a4a097', marginLeft: 6 }}>
            （选填）
          </span>
        </div>

        {consumedParts.length === 0 ? (
          <div style={{
            padding: '20px 16px', textAlign: 'center',
            color: '#a4a097', fontSize: 13,
            background: '#fafaf9', borderRadius: 8,
            border: '1px dashed #e5e3df',
            marginBottom: 8,
          }}>
            暂无消耗备件
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 10 }}>
            {consumedParts.map((item, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '12px',
                  background: '#fafaf9',
                  borderRadius: 8,
                  border: '1px solid #ede9e4',
                }}
              >
                <Select
                  showSearch
                  placeholder="搜索并选择备件"
                  style={{ flex: 1, minWidth: 0 }}
                  value={item.sparePartId || undefined}
                  onChange={(v) => {
                    setConsumedParts(prev => prev.map((p, i) => i === idx ? { ...p, sparePartId: v } : p))
                  }}
                  filterOption={(input, option) => {
                    if (!option) return false
                    const d = option as any
                    const hay = `${d.code || ''} ${d.name || ''} ${d.spec || ''} ${d.stock || ''}`.toLowerCase()
                    return hay.includes(input.toLowerCase())
                  }}
                  popupMatchSelectWidth={false}
                  popupStyle={{ minWidth: 420 }}
                  listHeight={320}
                  optionRender={(option) => {
                    const d = option.data as any
                    return (
                      <div style={{ padding: '2px 0' }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: '#1a1a1a', lineHeight: 1.4 }}>
                          <span style={{ color: '#787671' }}>{d.code}</span>
                          <span style={{ margin: '0 6px', color: '#c8c4be' }}>|</span>
                          {d.name}
                        </div>
                        <div style={{ fontSize: 12, color: '#787671', lineHeight: 1.4, marginTop: 1 }}>
                          规格: {d.spec}
                          <span style={{ margin: '0 8px', color: '#c8c4be' }}>|</span>
                          库存: {d.stock} {d.unit}
                        </div>
                      </div>
                    )
                  }}
                  labelRender={(props) => {
                    const sp = availableParts.find(s => s.id === props.value)
                    const tooltip = sp
                      ? `${sp.code} ${sp.name} / ${sp.specification || '-'} / 库存 ${sp.current_qty ?? 0} ${sp.unit || ''}`
                      : ''
                    return (
                      <Tooltip title={tooltip}>
                        <span style={{
                          display: 'block',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}>
                          {props.label}
                        </span>
                      </Tooltip>
                    )
                  }}
                  options={availableParts.map(sp => ({
                    label: `${sp.code} ${sp.name}`,
                    value: sp.id,
                    code: sp.code,
                    name: sp.name,
                    spec: sp.specification || '-',
                    stock: sp.current_qty ?? 0,
                    unit: sp.unit || '',
                  }))}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                  <InputNumber
                    min={1}
                    value={item.qty || undefined}
                    onChange={(v) => {
                      setConsumedParts(prev => prev.map((p, i) => i === idx ? { ...p, qty: v || 1 } : p))
                    }}
                    style={{ width: 72 }}
                    placeholder="数量"
                  />
                  <span style={{ fontSize: 12, color: '#787671', whiteSpace: 'nowrap' }}>
                    {availableParts.find(s => s.id === item.sparePartId)?.unit || ''}
                  </span>
                </div>
                <Button
                  type="text"
                  danger
                  size="small"
                  style={{ flexShrink: 0, color: '#e03131' }}
                  onClick={() => {
                    setConsumedParts(prev => {
                      const next = prev.filter((_, i) => i !== idx)
                      return next.length === 0 ? [] : next
                    })
                  }}
                >
                  移除
                </Button>
              </div>
            ))}
          </div>
        )}

        <Button
          type="dashed"
          size="small"
          onClick={() => setConsumedParts(prev => [...prev, { sparePartId: '', qty: 1 }])}
          style={{ marginBottom: 24 }}
        >
          + 添加备件
        </Button>

        {/* ── 现场照片 ── */}
        <div style={{
          fontSize: 11, fontWeight: 600, color: '#a4a097',
          textTransform: 'uppercase', letterSpacing: 1,
          marginBottom: 10,
        }}>
          现场照片
          <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: '#a4a097', marginLeft: 6 }}>
            （选填）
          </span>
        </div>
        <Upload
          multiple
          listType="picture"
          fileList={fileList}
          onChange={({ fileList: fl }) => setFileList(fl)}
          beforeUpload={() => false}
        >
          <Button icon={<UploadOutlined />}>选择图片</Button>
        </Upload>
      </Modal>
    </Drawer>
  )
}
