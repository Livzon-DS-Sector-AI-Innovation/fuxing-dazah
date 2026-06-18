'use client'

import { useState, useCallback, useMemo, useEffect } from 'react'
import { App, Progress, Typography } from 'antd'
import { ArrowLeftOutlined, CheckOutlined, CameraOutlined, AimOutlined, RobotOutlined, EnvironmentOutlined } from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { submitEquipmentCheck, uploadInspectionPhoto, completeInspectionTask, analyzeInspectionPhoto } from '@/actions/inspection'
import type { InspectionRecordItem, InspectionAIItemResult } from '@/types/inspection'
import type { InspectionTemplateItem } from '@/types/equipment'

const { Text } = Typography

const C = { navy: '#0a1530', purple: '#5645d4', purpleLight: '#e6e0f5', purpleDeep: '#391c57',
  ink: '#1a1a1a', charcoal: '#37352f', slate: '#5d5b54', steel: '#787671', stone: '#a4a097',
  muted: '#bbb8b1', hairline: '#e5e3df', hairlineSoft: '#ede9e4', surface: '#f6f5f4',
  surfaceSoft: '#fafaf9', canvas: '#ffffff', green: '#1aae39', error: '#e03131',
  orange: '#dd5b00', orangeBg: '#ffe8d4', greenBg: '#d9f3e1', yellowBg: '#fef7d6' }

interface Props { onClose: () => void }
interface VEq { equipment_id: string; equipment_name: string; equipment_no?: string }

/* ══════════════════════════════════════════════════
   Unified execution view — line & device inspection
   share the same step-by-step equipment check flow.
   Line inspection adds location-level navigation.
   ══════════════════════════════════════════════════ */

export function InspectionExecuteView({ onClose }: Props) {
  const { message, modal } = App.useApp()
  const s = useInspectionStore()
  const { executingTaskId, executingPlanType, executingRouteDetail, executingTemplateItems, executingTemplateName,
    executingEquipmentId, executingEquipmentName, executingEquipmentNo,
    executingEquipmentIds, executingEquipments, executingCompletedEquipmentIds, clearExecuting } = s

  const isLine = executingPlanType === '线路巡检'
  const routeName = executingRouteDetail?.name || ''

  // flatten all equipment from route locations (line) or task config (device)
  const allEqs: VEq[] = useMemo(() => {
    if (isLine && executingRouteDetail?.locations) {
      return executingRouteDetail.locations.flatMap(loc =>
        (loc.equipments || []).map(eq => ({
          equipment_id: eq.equipment_id,
          equipment_name: eq.equipment_name || '设备',
          equipment_no: eq.equipment_no || undefined,
        }))
      )
    }
    if (executingEquipmentIds?.length) {
      const m = new Map(executingEquipments.map(e => [e.id, e]))
      return executingEquipmentIds.map(id => ({
        equipment_id: id, equipment_name: m.get(id)?.name || id.slice(0, 8) + '…', equipment_no: m.get(id)?.no,
      }))
    }
    if (executingEquipmentId) {
      return [{ equipment_id: executingEquipmentId, equipment_name: executingEquipmentName || executingEquipmentNo || '设备', equipment_no: executingEquipmentNo }]
    }
    return []
  }, [isLine, executingRouteDetail, executingEquipmentIds, executingEquipments, executingEquipmentId, executingEquipmentName, executingEquipmentNo])

  const total = allEqs.length
  const initDone = useMemo(() => new Set(executingCompletedEquipmentIds || []), [executingCompletedEquipmentIds])
  const initStep = useMemo(() => { const i = allEqs.findIndex(eq => !initDone.has(eq.equipment_id)); return i >= 0 ? i : 0 }, [allEqs, initDone])
  const [step, setStep] = useState(initStep)
  const [done, setDone] = useState<Set<string>>(initDone)
  const [submitting, setSubmitting] = useState(false)
  const [photos, setPhotos] = useState<Record<string, File[]>>({})
  const cur = allEqs[step]
  const doneN = done.size
  const pct = total > 0 ? Math.round((doneN / total) * 100) : 0

  // location info for current equipment (line inspection only)
  let curLocName = ''
  if (isLine && executingRouteDetail?.locations) {
    for (const loc of executingRouteDetail.locations) {
      for (const eq of (loc.equipments || [])) {
        if (eq.equipment_id === cur?.equipment_id) { curLocName = loc.location_name || ''; break }
      }
    }
  }

  const submitCheck = useCallback(async (records: InspectionRecordItem[]) => {
    if (!executingTaskId || !cur) return
    try {
      await submitEquipmentCheck(executingTaskId, cur.equipment_id, { records })
      for (const f of photos[cur.equipment_id] || []) {
        const fd = new FormData(); fd.append('file', f)
        await uploadInspectionPhoto(executingTaskId, cur.equipment_id, fd)
      }
      setDone(prev => new Set(prev).add(cur.equipment_id))
      message.success(`${cur.equipment_name} 检查完成`)
      if (step < total - 1) setStep(step + 1)
    } catch (err: unknown) { message.error((err as Error).message || '提交失败') }
  }, [executingTaskId, cur, step, total, photos, message])

  const finish = useCallback(() => {
    if (!executingTaskId) return
    const left = total - doneN
    modal.confirm({
      title: '提交巡检',
      content: left > 0 ? `还有 ${left} 台设备未检查（已完成 ${doneN}/${total}），确定提交吗？` : `全部 ${total} 台设备已检查完成，确认提交？`,
      okText: '确认提交', cancelText: '取消',
      onOk: async () => {
        setSubmitting(true)
        try { await completeInspectionTask(executingTaskId); message.success('巡检任务已完成'); clearExecuting(); onClose() }
        catch (err: unknown) { message.error((err as Error).message || '提交失败') }
        finally { setSubmitting(false) }
      },
    })
  }, [executingTaskId, doneN, total, clearExecuting, onClose, message, modal])

  const addPhoto = useCallback((eqId: string, file: File) => { setPhotos(prev => ({ ...prev, [eqId]: [...(prev[eqId] || []), file] })) }, [])
  const rmPhoto = useCallback((eqId: string, idx: number) => { setPhotos(prev => ({ ...prev, [eqId]: (prev[eqId] || []).filter((_, i) => i !== idx) })) }, [])

  if (allEqs.length === 0) {
    return (
      <div style={{ maxWidth: 480, margin: '120px auto', textAlign: 'center' }}>
        <Text type="secondary" style={{ fontSize: 15, display: 'block', marginBottom: 20 }}>无法获取巡检设备信息</Text>
        <button onClick={onClose} style={{ padding: '10px 24px', background: C.navy, color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: 'inherit' }}>返回</button>
      </div>
    )
  }

  const curPhotos = photos[cur?.equipment_id || ''] || []

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '28px 0 48px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: C.slate, fontSize: 13, fontWeight: 500, fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <ArrowLeftOutlined />返回任务列表
          </button>
          <h2 style={{ fontSize: 22, fontWeight: 600, color: C.ink, margin: 0 }}>
            {isLine ? '线路巡检' : '设备巡检'}
            <span style={{ fontWeight: 400, fontSize: 16, color: C.steel, marginLeft: 12 }}>
              {isLine ? routeName : executingTemplateName}
            </span>
          </h2>
        </div>
      </div>

      {/* Location + route info (line only) */}
      {isLine && curLocName && (
        <div style={{ padding: '14px 20px', marginBottom: 20, background: C.purpleLight, borderRadius: 10, border: `1px solid #d6b6f6`, display: 'flex', alignItems: 'center', gap: 10 }}>
          <EnvironmentOutlined style={{ color: C.purple, fontSize: 18 }} />
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.purpleDeep, textTransform: 'uppercase', letterSpacing: 0.5 }}>当前地点</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: C.ink }}>{curLocName}</div>
          </div>
        </div>
      )}

      {/* Guide */}
      <div style={{ padding: '14px 20px', marginBottom: 20, background: C.purpleLight, borderRadius: 10, border: `1px solid #d6b6f6` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <AimOutlined style={{ fontSize: 20, color: C.purple }} />
          <div>
            <Text strong style={{ fontSize: 14, color: C.purpleDeep, display: 'block' }}>
              {total > 1 ? `第 ${step + 1} 步 / 共 ${total} 步 — 对下方设备逐项检查并拍照` : '对下方设备逐项检查并拍照，完成后提交巡检'}
            </Text>
            <Text style={{ fontSize: 12, color: C.purple }}>每台设备至少拍摄一张现场照片 · 逐项标记检查结果 · 异常项请备注说明</Text>
          </div>
        </div>
      </div>

      {/* Progress */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', marginBottom: 16, background: C.surfaceSoft, borderRadius: 10, border: `1px solid ${C.hairlineSoft}` }}>
        <div>
          <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 }}>进度</Text>
          <div style={{ fontSize: 28, fontWeight: 600, color: C.ink, lineHeight: 1.1, marginTop: 2 }}>
            {doneN}<span style={{ fontSize: 16, fontWeight: 400, color: C.stone }}> / {total}</span>
          </div>
        </div>
        <Progress type="circle" percent={pct} size={60} strokeColor={pct === 100 ? C.green : C.purple} railColor={C.hairline} />
      </div>

      {/* Equipment step indicator */}
      {total > 1 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 20, flexWrap: 'wrap' }}>
          {allEqs.map((eq, i) => (
            <button key={eq.equipment_id} onClick={() => setStep(i)}
              style={{
                padding: '6px 14px', borderRadius: 20, border: 'none', cursor: 'pointer',
                background: done.has(eq.equipment_id) ? C.greenBg : i === step ? C.purple : C.surfaceSoft,
                color: done.has(eq.equipment_id) ? C.green : i === step ? '#fff' : C.stone,
                fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                transition: 'all 0.15s',
              }}>
              {done.has(eq.equipment_id) && <CheckOutlined style={{ marginRight: 4 }} />}
              {eq.equipment_name}
            </button>
          ))}
        </div>
      )}

      {/* Current equipment check card */}
      {cur && (
        <EquipmentCheckCard
          key={cur.equipment_id}
          equipmentId={cur.equipment_id} equipmentName={cur.equipment_name} equipmentNo={cur.equipment_no}
          templateItems={executingTemplateItems} photos={curPhotos}
          onAddPhoto={f => addPhoto(cur.equipment_id, f)} onRemovePhoto={i => rmPhoto(cur.equipment_id, i)}
          onSubmit={submitCheck} disabled={done.has(cur.equipment_id)}
        />
      )}

      {/* Submit */}
      <div style={{ marginTop: 28, textAlign: 'center' }}>
        <button onClick={finish} disabled={submitting} style={{
          padding: '12px 32px', borderRadius: 8,
          background: pct === 100 ? C.green : C.purple, color: '#fff', border: 'none',
          fontSize: 15, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
          opacity: submitting ? 0.7 : 1, boxShadow: '0 2px 8px rgba(86,69,212,0.3)',
        }}>
          <CheckOutlined />{pct === 100 ? '提交巡检' : `提交巡检（已完成 ${doneN}/${total}）`}
        </button>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════
   EquipmentCheckCard — single device check card
   ══════════════════════════════════════════════════ */

interface CardProps { equipmentId: string; equipmentName: string; equipmentNo?: string; templateItems: InspectionTemplateItem[]; photos: File[]; onAddPhoto: (f: File) => void; onRemovePhoto: (i: number) => void; onSubmit: (records: InspectionRecordItem[]) => Promise<void>; disabled?: boolean }

function EquipmentCheckCard({ equipmentId, equipmentName, equipmentNo, templateItems, photos, onAddPhoto, onRemovePhoto, onSubmit, disabled }: CardProps) {
  const { message } = App.useApp()
  const [subLoading, setSubLoading] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [formVals, setFormVals] = useState<Record<number, { result: string; actual_value: string; remark: string }>>({})

  const photoUrls = useMemo(() => photos.map(f => URL.createObjectURL(f)), [photos])
  useEffect(() => { return () => { photoUrls.forEach(u => URL.revokeObjectURL(u)) } }, [photoUrls])

  const handleSubmit = async () => {
    const records: InspectionRecordItem[] = templateItems.map((item, i) => ({
      template_item_id: item.id,
      result: (formVals[i]?.result || '正常') as '正常' | '异常' | '跳过',
      actual_value: formVals[i]?.actual_value || undefined,
      remark: formVals[i]?.remark || undefined,
    }))
    // validate: abnormal items must have value or remark
    for (const r of records) {
      if (r.result === '异常' && !r.actual_value && !r.remark) {
        message.warning(`检查项异常时必须填写实际值或备注`); return
      }
    }
    setSubLoading(true)
    try { await onSubmit(records) }
    catch (err: unknown) { message.error((err as Error).message || '提交失败') }
    finally { setSubLoading(false) }
  }

  const handleAI = async () => {
    const { executingTaskId: tid } = useInspectionStore.getState()
    if (!tid) { message.error('任务信息丢失'); return }
    if (photos.length === 0) { message.warning('请先拍摄到位照片'); return }
    setAiLoading(true)
    try {
      const file = photos[0]
      const b64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => { const result = r.result as string; resolve(result.split(',')[1] || result) }
        r.onerror = () => reject(new Error('图片读取失败'))
        r.readAsDataURL(file)
      })
      const results = await analyzeInspectionPhoto(tid, equipmentId, b64, file.type || 'image/jpeg')
      const vals: typeof formVals = {}
      templateItems.forEach((item, i) => {
        const ai = results.find(r => r.template_item_id === item.id)
        vals[i] = { result: ai?.result || '正常', actual_value: ai?.actual_value ?? '', remark: ai?.remark ?? '' }
      })
      setFormVals(vals)
      const skips = results.filter(r => r.result === '跳过').length
      message.success(skips > 0 ? `AI 分析完成，${skips} 项无法识别已标记"跳过"` : 'AI 分析完成')
    } catch (err: unknown) { message.error((err as Error).message || 'AI 分析失败') }
    finally { setAiLoading(false) }
  }

  const pickFile = () => {
    const inp = document.createElement('input')
    inp.type = 'file'; inp.accept = 'image/*'; inp.capture = 'environment'
    inp.onchange = e => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) onAddPhoto(f) }
    inp.click()
  }

  const noPhoto = photos.length === 0

  return (
    <div style={{ background: C.canvas, borderRadius: 12, border: `1px solid ${C.hairline}`, overflow: 'hidden' }}>
      {/* equipment title bar */}
      <div style={{ padding: '12px 20px', background: C.navy, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <Text strong style={{ fontSize: 16, color: '#fff' }}>{equipmentName}</Text>
          {equipmentNo && <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, color: C.stone, background: 'rgba(255,255,255,0.12)' }}>{equipmentNo}</span>}
        </div>
        {disabled && <span style={{ padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: C.green, background: 'rgba(26,174,57,0.15)' }}>已完成</span>}
      </div>

      <div style={{ padding: 20 }}>
        {/* photo area */}
        <div style={{ padding: 16, marginBottom: 20, background: noPhoto ? C.yellowBg : C.surfaceSoft, borderRadius: 10, border: noPhoto ? '2px dashed #f5d75e' : `1px solid #d9f3e1` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: photos.length > 0 ? 12 : 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CameraOutlined style={{ fontSize: 15, color: noPhoto ? C.orange : C.green }} />
              <Text strong style={{ fontSize: 13 }}>到位照片</Text>
              {!noPhoto && <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, color: C.green, background: C.greenBg }}>{photos.length} 张</span>}
              {noPhoto && <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, color: C.orange, background: C.orangeBg }}>待拍照</span>}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={handleAI} disabled={disabled || photos.length === 0} style={{ padding: '6px 12px', background: 'transparent', color: disabled ? C.muted : C.purple, border: `1px solid ${disabled ? C.hairline : C.purple}`, borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 4, opacity: aiLoading ? 0.7 : 1 }}>
                <RobotOutlined />{aiLoading ? '分析中...' : 'AI分析'}
              </button>
              <button onClick={pickFile} disabled={disabled} style={{ padding: '6px 12px', background: 'transparent', color: disabled ? C.muted : C.slate, border: `1px solid ${C.hairline}`, borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer', fontFamily: 'inherit' }}>
                <CameraOutlined />拍照
              </button>
            </div>
          </div>
          {!noPhoto && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {photos.map((f, i) => (
                <div key={i} style={{ position: 'relative', width: 80, height: 80, borderRadius: 8, overflow: 'hidden', border: `1px solid ${C.hairline}`, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
                  <img src={photoUrls[i]} alt={`${equipmentName}-${i + 1}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  {!disabled && (
                    <span role="button" onClick={() => onRemovePhoto(i)} style={{ position: 'absolute', top: 3, right: 3, width: 18, height: 18, borderRadius: 9, background: 'rgba(224,49,49,0.88)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 10, fontWeight: 600, lineHeight: 1 }}>✕</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* check items */}
        <Text strong style={{ fontSize: 13, color: C.charcoal, display: 'block', marginBottom: 12 }}>检查项目</Text>
        {templateItems.map((item, i) => (
          <div key={item.id} style={{ padding: '12px 14px', marginBottom: 6, background: C.surfaceSoft, borderRadius: 8, border: `1px solid ${C.hairlineSoft}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 20, height: 20, borderRadius: 10, background: C.purple, color: '#fff', fontSize: 11, fontWeight: 700 }}>{i + 1}</span>
                  <Text strong style={{ fontSize: 13 }}>{item.item_name}</Text>
                </div>
                {item.expected_result && <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 2, marginLeft: 28 }}>标准值：{item.expected_result}</Text>}
                {item.item_description && <Text type="secondary" style={{ fontSize: 11, display: 'block', marginLeft: 28 }}>{item.item_description}</Text>}
              </div>
              <select value={formVals[i]?.result || '正常'} onChange={e => setFormVals(prev => ({ ...prev, [i]: { ...prev[i], result: e.target.value } }))}
                disabled={disabled} style={{ borderRadius: 6, border: `1px solid ${C.hairline}`, padding: '3px 8px', fontSize: 12, fontFamily: 'inherit', background: C.canvas }}>
                <option value="正常">正常</option><option value="异常">异常</option><option value="跳过">跳过</option>
              </select>
            </div>
            <div style={{ display: 'flex', gap: 8, marginLeft: 28 }}>
              <input placeholder="实际值" value={formVals[i]?.actual_value || ''} onChange={e => setFormVals(prev => ({ ...prev, [i]: { ...prev[i], actual_value: e.target.value } }))}
                disabled={disabled} style={{ flex: 1, borderRadius: 6, border: `1px solid ${C.hairline}`, padding: '4px 8px', fontSize: 12, fontFamily: 'inherit' }} />
              <input placeholder="备注" value={formVals[i]?.remark || ''} onChange={e => setFormVals(prev => ({ ...prev, [i]: { ...prev[i], remark: e.target.value } }))}
                disabled={disabled} style={{ flex: 1, borderRadius: 6, border: `1px solid ${C.hairline}`, padding: '4px 8px', fontSize: 12, fontFamily: 'inherit' }} />
            </div>
          </div>
        ))}

        {/* submit per equipment */}
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <button onClick={handleSubmit} disabled={disabled || subLoading} style={{
            padding: '8px 20px', borderRadius: 8, border: 'none',
            background: disabled ? C.hairline : C.purple, color: disabled ? C.muted : '#fff',
            fontSize: 13, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit', opacity: subLoading ? 0.7 : 1,
          }}>
            <CheckOutlined />提交本设备检查
          </button>
        </div>
      </div>
    </div>
  )
}
