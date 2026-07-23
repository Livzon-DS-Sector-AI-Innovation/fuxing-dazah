'use client'

import { useState, useEffect, useMemo } from 'react'
import { Table, Typography, Tag, Button, Popconfirm, Empty, Card, Row, Col, Statistic, Space, Modal, Form, Input, Select, Upload, message } from 'antd'
import { DeleteOutlined, DownloadOutlined, CheckCircleOutlined, CloseCircleOutlined, ExperimentOutlined, FileTextOutlined, UploadOutlined, FilterOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

const { Title, Text } = Typography
const SKEY = 'lc_saved_data'
const GKEY = 'lc_generated'
const TPL_API = 'http://localhost:8000/api/v1/quality/templates'
const RPT_API = 'http://localhost:8000/api/v1/quality/report/generate'
const PRD_API = 'http://localhost:8000/api/v1/quality/products'

function getGenInfo(idx: number): string | null {
  try { const g = JSON.parse(localStorage.getItem(GKEY) || '{}'); return g[String(idx)] || null } catch { return null }
}
function markGenerated(idx: number, tpl: string) {
  try {
    const g = JSON.parse(localStorage.getItem(GKEY) || '{}')
    g[String(idx)] = tpl
    localStorage.setItem(GKEY, JSON.stringify(g))
  } catch { }
}
function unmarkGenerated(idx: number) {
  try {
    const g = JSON.parse(localStorage.getItem(GKEY) || '{}')
    delete g[String(idx)]
    localStorage.setItem(GKEY, JSON.stringify(g))
  } catch { }
}

interface SavedEntry {
  time: string; fid: string; batch: string; vb: string; tot: string; pass: boolean
  imps: { name: string; val: string; pass: boolean }[]
}

export default function SummaryPage() {
  const [data, setData] = useState<SavedEntry[]>([])
  const [reportOpen, setReportOpen] = useState(false)
  const [reportIdx, setReportIdx] = useState<number>(0)
  const [genLoading, setGenLoading] = useState(false)
  const [templates, setTemplates] = useState<{ filename: string; name: string }[]>([])
  const [allFields, setAllFields] = useState<string[]>([])
  const [prodMap, setProdMap] = useState<Record<string, string>>({})  // code→产品名
  const [prodTab, setProdTab] = useState('')
  const [form] = Form.useForm()

  useEffect(() => { load(); loadProducts() }, [])

  function load() { try { setData(JSON.parse(localStorage.getItem(SKEY) || '[]')) } catch { setData([]) } }

  async function loadProducts() {
    try {
      const r = await fetch(PRD_API)
      if (r.ok) {
        const list = await r.json()
        const map: Record<string, string> = {}
        list.forEach((p: any) => {
          if (p.codes) p.codes.split(/\s+/).forEach((c: string) => { if (c) map[c.toUpperCase()] = p.name })
        })
        setProdMap(map)
      }
    } catch { }
  }
  function del(idx: number) { const s = JSON.parse(localStorage.getItem(SKEY) || '[]'); s.splice(idx, 1); localStorage.setItem(SKEY, JSON.stringify(s)); load() }

  function genSerial(): string {
    const now = new Date()
    const yy = String(now.getFullYear()).slice(2)
    const mm = String(now.getMonth() + 1).padStart(2, '0')
    const dd = String(now.getDate()).padStart(2, '0')
    const prefix = yy + mm + dd
    // 查找今天已有的最大序号
    const todayReports = data.filter(d => d.time && d.time.slice(0, 10) === now.toISOString().slice(0, 10))
    let maxSeq = 0
    // 也查localStorage中带流水号的记录
    try {
      const all = JSON.parse(localStorage.getItem('lc_serials') || '[]') as string[]
      all.forEach((s: string) => { if (s.startsWith(prefix)) { const n = parseInt(s.slice(6)); if (n > maxSeq) maxSeq = n } })
    } catch { }
    // 加上今天已保存但可能没流水号的
    maxSeq = Math.max(maxSeq, todayReports.length)
    return prefix + String(maxSeq + 1).padStart(2, '0')
  }

  async function loadTemplates() {
    try {
      const [resp, phResp] = await Promise.all([
        fetch(TPL_API),
        fetch(TPL_API + '/all-placeholders')
      ])
      if (resp.ok) {
        const list = await resp.json()
        const flat: { filename: string; name: string }[] = []
        function walk(items: any[], prefix = '') {
          items.forEach((item: any) => {
            if (item.type === 'folder') walk(item.children || [], prefix + item.name + '/')
            else flat.push({ filename: prefix + item.filename, name: (prefix || '') + item.filename.replace('.docx', '') })
          })
        }
        walk(list)
        setTemplates(flat)
        if (!flat.length) message.warning('未找到报告模板，请先在「模板管理」中上传')
      }
      if (phResp.ok) {
        const phs = await phResp.json()
        setAllFields(phs)
      }
    } catch {
      message.warning('无法加载模板列表，使用默认模板')
      setTemplates([{ filename: '万古霉素/3205.docx', name: '3205' }])
    }
  }

  function openReportModal(idx: number) {
    setReportIdx(idx)
    loadTemplates()
    const serial = genSerial()
    // 从保存数据预填液相结果
    const vals: any = { '流水号': serial, 'template': templates[0]?.filename || '万古霉素/3205.docx' }
    if (idx >= 0 && data[idx]) {
      const e = data[idx]
      vals['批号'] = e.batch
      vals['万古霉素B'] = e.vb
      vals['总杂质'] = e.tot
      e.imps.forEach(im => {
        const nm = im.name.split('（')[0].replace('杂质', '')
        vals[nm] = im.val
        if (nm === 'A') vals['杂质A'] = im.val
        if (nm === 'B1') vals['杂质B'] = im.val
        if (nm === 'C') vals['杂质C'] = im.val
        if (nm === 'D') vals['杂质D'] = im.val
        if (nm.startsWith('任何未知')) vals['任何未知杂质'] = im.val
      })
    }
    form.setFieldsValue(vals)
    setReportOpen(true)
  }

  async function generateReport(values: Record<string, string>) {
    const entry = data[reportIdx]; if (!entry) return
    setGenLoading(true)
    try {
      // 所有表单值
      const payload: Record<string, string> = {}
      Object.entries(values).forEach(([k, v]) => {
        if (v && k !== 'template') payload[k] = String(v)
      })
      // 自动补填: 批号用保存记录的(如果表单没填)
      if (!payload['批号']) payload['批号'] = entry.batch

      const tpl = values['template'] || '万古霉素/3205.docx'
      const resp = await fetch(RPT_API, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: payload, template: tpl }),
      })
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); message.error('生成失败: ' + (e.detail || 'HTTP ' + resp.status)); setGenLoading(false); return }
      const blob = await resp.blob()
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
      a.download = 'COA-' + entry.batch + '.docx'; a.click()
      URL.revokeObjectURL(a.href)
      // 记录流水号防止重复
      const sn = values['流水号'] || payload['流水号']
      if (sn) {
        try {
          const serials = JSON.parse(localStorage.getItem('lc_serials') || '[]')
          if (!serials.includes(sn)) { serials.push(sn); localStorage.setItem('lc_serials', JSON.stringify(serials)) }
        } catch { }
      }
      markGenerated(reportIdx, (values['template'] || '3205.docx').replace('.docx', ''))
      message.success('报告已生成')
      setReportOpen(false)
    } catch (e: any) { message.error(e.message) }
    finally { setGenLoading(false) }
  }

  function productCode(batch: string): string {
    const m = batch.match(/^[A-Z]+/); return m ? m[0] : batch.slice(0, 3)
  }
  function productName(code: string): string { return prodMap[code] || code }

  const products = useMemo(() => {
    const seen = new Set<string>()
    data.forEach(d => { if (d.batch) seen.add(productCode(d.batch)) })
    return Array.from(seen).sort()
  }, [data, prodMap])

  const filteredData = useMemo(() =>
    prodTab ? data.filter(d => productCode(d.batch) === prodTab) : data
  , [data, prodTab])

  const stats = useMemo(() => {
    const total = filteredData.length, passed = filteredData.filter(d => d.pass).length
    return { total, passed, failed: total - passed, rate: total ? Math.round(passed / total * 100) : 0 }
  }, [filteredData])

  function exportAll() {
    if (!filteredData.length) return
    const impNames = filteredData[0]?.imps?.map((im: any) => im.name.split('（')[0].replace('杂质', '')) || []
    let h = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="UTF-8"></head><body><table border="1">'
    h += '<tr><th>时间</th><th>批号</th><th>万古B</th>' + impNames.map((n: string) => '<th>' + n + '</th>').join('') + '<th>总杂质</th><th>判定</th></tr>'
    filteredData.forEach(e => {
      h += '<tr><td>' + e.time.slice(0, 16).replace('T', ' ') + '</td><td>' + e.batch + '</td><td>' + e.vb + '</td>'
      e.imps.forEach(im => { h += '<td>' + im.val + '</td>' })
      h += '<td>' + e.tot + '</td><td>' + (e.pass ? '合格' : '不合格') + '</td></tr>'
    })
    h += '</table></body></html>'
    const b = new Blob(['﻿' + h], { type: 'application/vnd.ms-excel;charset=utf-8' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(b)
    a.download = '液相计算汇总_' + new Date().toISOString().slice(0, 10) + '.xls'; a.click()
    URL.revokeObjectURL(a.href)
  }

  const columns: ColumnsType<SavedEntry & { key: number }> = useMemo(() => {
    const base: ColumnsType<SavedEntry & { key: number }> = [
      { title: '时间', dataIndex: 'time', width: 110, fixed: 'left' as const,
        render: (v: string) => <Text style={{ fontSize: 11, color: '#999' }}>{v.slice(5, 16).replace('T', ' ')}</Text> },
      { title: '产品', dataIndex: 'batch', width: 60, fixed: 'left' as const,
        render: (v: string) => <Tag color="blue" style={{ fontSize: 10 }}>{productName(productCode(v))}</Tag> },
      { title: '批号', dataIndex: 'batch', width: 120, fixed: 'left' as const,
        render: (v: string) => <Text strong>{v}</Text> },
      { title: '万古B', dataIndex: 'vb', width: 85,
        render: (v: string) => <span style={{ fontSize: 15, fontWeight: 700, color: '#1a73e8' }}>{v}</span> },
    ]
    if (filteredData.length && filteredData[0].imps) {
      filteredData[0].imps.forEach((im, i) => {
        const short = im.name.split('（')[0].replace('杂质', '')
        base.push({
          title: <span style={{ fontSize: 10 }}>{short}</span>, dataIndex: 'imps', width: 78, align: 'center' as const,
          render: (imps: any[]) => {
            const v = imps?.[i]; if (!v) return <Text type="secondary">-</Text>
            return <span style={{ fontSize: 12, fontWeight: 500, color: v.pass ? '#006000' : '#c00' }}>{v.val}</span>
          },
        })
      })
    }
    base.push(
      { title: '总杂质', dataIndex: 'tot', width: 80, render: (v: string) => <Text strong style={{ fontSize: 12 }}>{v}</Text> },
      { title: '判定', dataIndex: 'pass', width: 60, align: 'center' as const, fixed: 'right' as const,
        render: (v: boolean) => v ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag> },
      {
        title: '操作', key: 'act', width: 120, fixed: 'right' as const,
        render: (_: any, __: any, idx: number) => {
          const gen = getGenInfo(idx)
          return (
            <Space size={0}>
              {gen ? (
                <Popconfirm title={`模板${gen}，已生成过报告，确定重新生成？`} onConfirm={() => { unmarkGenerated(idx); openReportModal(idx) }}>
                  <Button type="link" size="small" style={{ color: '#d97706', fontSize: 11 }}>已生成({gen})</Button>
                </Popconfirm>
              ) : (
                <Button type="link" size="small" icon={<FileTextOutlined />} style={{ color: '#059669' }}
                  onClick={() => openReportModal(idx)}>报告</Button>
              )}
              <Popconfirm title="删除？" onConfirm={() => del(idx)}>
                <Button type="link" danger size="small" icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          )
        },
      },
    )
    return base
  }, [filteredData])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <ExperimentOutlined style={{ fontSize: 20, color: '#1a73e8' }} />
          <Title level={4} style={{ margin: 0 }}>液相计算结果汇总</Title>
        </Space>
        <Space>
          <Select value={prodTab} onChange={setProdTab} size="small" style={{ width: 180 }}
            placeholder="全部产品" options={[{ value: '', label: '全部产品' }, ...products.map(p => ({ value: p, label: productName(p) }))]}
            prefix={<FilterOutlined />} />
          <Button type="primary" icon={<DownloadOutlined />} onClick={exportAll} disabled={!data.length}>导出全部</Button>
        </Space>
      </div>


      {filteredData.length > 0 && (
        <Row gutter={12} style={{ marginBottom: 12 }}>
          <Col span={6}><Card size="small"><Statistic title="总记录" value={stats.total} suffix="条" /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="合格" value={stats.passed} suffix="条" valueStyle={{ color: '#006000' }} prefix={<CheckCircleOutlined />} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="不合格" value={stats.failed} suffix="条" valueStyle={{ color: stats.failed > 0 ? '#c00' : '#999' }} prefix={<CloseCircleOutlined />} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="合格率" value={stats.rate} suffix="%" valueStyle={{ color: stats.rate >= 90 ? '#006000' : '#c00' }} /></Card></Col>
        </Row>
      )}

      {filteredData.length ? (
        <Table
          columns={columns}
          dataSource={filteredData.map((d, i) => ({ ...d, key: i }))}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
          size="small" scroll={{ x: 1400 }} bordered
        />
      ) : (
        <Empty description={data.length ? "此分类暂无记录" : "暂无保存记录。请在「📊 计算表」中保存结果"} />
      )}

      <Modal title="补充报告信息" open={reportOpen} onCancel={() => setReportOpen(false)}
        onOk={() => form.submit()} confirmLoading={genLoading} okText="生成报告" width={520}>
        <Form form={form} layout="vertical" onFinish={generateReport} style={{ marginTop: 16 }}>
          <Row gutter={12}>
            <Col span={12}><Form.Item label="报告模板" name="template" rules={[{ required: true }]}>
              <Select options={templates.map(t => ({ value: t.filename, label: t.name }))} placeholder="选择模板"
                dropdownRender={menu => (
                  <>{menu}<div style={{ borderTop: '1px solid #f0f0f0', padding: '6px 8px' }}>
                    <Upload accept=".docx" showUploadList={false} maxCount={1}
                      customRequest={async (opt) => {
                        const fd = new FormData(); fd.append('file', opt.file as File)
                        const r = await fetch(TPL_API + '/upload', { method: 'POST', body: fd })
                        if (r.ok) { message.success('模板已上传'); loadTemplates() } else { const e = await r.json().catch(() => ({})); message.error(e.detail || '上传失败') }
                        opt.onSuccess?.('ok')
                      }}>
                      <Button type="link" size="small" icon={<UploadOutlined />} style={{ padding: 0 }}>上传新模板</Button>
                    </Upload>
                  </div></>
                )} />
            </Form.Item></Col>
            <Col span={12}><Form.Item label="流水号" name="流水号"><Input placeholder="26070601" /></Form.Item></Col>
            {allFields.filter(f => !['流水号'].includes(f)).map(f => (
              <Col span={8} key={f}><Form.Item label={f} name={f}><Input placeholder={f} /></Form.Item></Col>
            ))}
          </Row>
          <Text type="secondary" style={{ fontSize: 11 }}>注：液相结果（万古霉素B、各杂质%、总杂质）自动从保存数据中预填。切换模板不会影响已有填写内容。</Text>
        </Form>
      </Modal>
    </div>
  )
}
