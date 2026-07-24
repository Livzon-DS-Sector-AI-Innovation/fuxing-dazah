'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Select, Space, Input, DatePicker } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee } from '@/types/hr'
import { logApiError } from '@/lib/hr'
import {
  fetchOnboardingRecords,
  API_BASE,
} from '@/lib/hr'

const CELL = { border: '1px solid #999', padding: '6px 10px', fontSize: '13px' } as const
const LABEL = { ...CELL, background: '#f5f5f5', fontWeight: 600, textAlign: 'center' as const, width: '15%' }
const VALUE = { ...CELL }

export default function OnboardingPrejobClient() {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  const [downloadingWord, setDownloadingWord] = useState(false)
  const [downloadingRecord, setDownloadingRecord] = useState(false)
  const [downloadingPermit, setDownloadingPermit] = useState(false)
  const [selectedSops, setSelectedSops] = useState<any[]>([])
  const [trainers, setTrainers] = useState<{value:string,label:string}[]>([])

  useEffect(() => {
    loadEmployees()
  }, [])

  const loadEmployees = async (keyword?: string) => {
    setLoading(true)
    try {
      const sp = new URLSearchParams()
      if (keyword) sp.set('keyword', keyword)
      const res = await fetch(`${API_BASE}/api/v1/hr/employees/training-candidates?${sp}`, { credentials: 'include' })
      const d = await res.json()
      setEmployees(d.data || [])
    } catch (err: any) {
      message.error('加载失败: ' + (err.message || '未知错误'))
    } finally { setLoading(false) }
  }

  const handleSearch = async (keyword: string) => {
    loadEmployees(keyword || undefined)
  }

  const selectedEmployee = employees.find((e: any) => e.id === selectedEmployeeId)

  // 选中员工后，根据岗位+部门自动加载关联培训大类
  useEffect(() => {
    if (!selectedEmployee) return
    const pos = selectedEmployee.position
    const dept = selectedEmployee.department
    if (!pos) return

    const params = new URLSearchParams({ position_name: pos })
    if (dept) params.set('department', dept)
    fetch(`${API_BASE}/api/v1/hr/position-trainings?${params}`)
      .then(r => r.json())
      .then(res => {
        const items: any[] = res.data || []
        if (items.length === 0) {
          message.info(`岗位「${pos}」暂无关联培训内容`)
          return
        }
        // 按培训类别去重，每个大类只取一条作为代表
        const seen = new Set<string>()
        const categories: any[] = []
        for (const item of items) {
          const cat = item.training_category
          if (cat && !seen.has(cat)) {
            seen.add(cat)
            categories.push({
              id: cat,
              sop_number: '',
              file_name: cat,
              department: item.department,
              category: cat,
              trainer: item.trainer,
              training_method: item.training_method,
            })
          }
        }
        setSelectedSops(categories)
        message.success(`已根据岗位「${pos}」加载 ${categories.length} 个培训大类`)
      })
      .catch(() => message.error('加载培训内容失败'))
  }, [selectedEmployeeId])

  // 加载培训师列表
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/trainers?page_size=200`).then(r => r.json())
      .then(res => setTrainers((res.data||[]).map((t:any) => ({value:t.name,label:`${t.name}(${t.department})`}))))
  }, [])

  const [sopMethods, setSopMethods] = useState<Record<string, string>>({})
  const [sopTrainers, setSopTrainers] = useState<Record<string, string>>({})
  const [sopPlanDates, setSopPlanDates] = useState<Record<string, string>>({})

  const updateSopMethod = (sopId: string, method: string) => {
    setSopMethods(prev => ({ ...prev, [sopId]: method }))
  }

  const toggleSop = (sop: any) => {
    setSelectedSops(prev => {
      const exists = prev.find(s => s.id === sop.id)
      if (exists) return prev.filter(s => s.id !== sop.id)
      return [...prev, sop]
    })
  }

  const buildItems = () => selectedSops.map(s => ({
    sop_number: s.sop_number || '',
    file_name: s.file_name || '',
    content: s.file_name || '',
    method: sopMethods[s.id] || '',
    trainer: sopTrainers[s.id] || '',
    plan_date: sopPlanDates[s.id] || '',
  }))

  const downloadDoc = async (url: string, method: string, filename: string, setLoading: (v: boolean) => void, body?: any) => {
    setLoading(true)
    try {
      const opts: any = { method, headers: {}, credentials: 'include' }
      if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body) }
      const res = await fetch(url, opts)
      if (!res.ok) {
        let detail = '导出失败'
        try { const d = await res.json(); detail = d.message || d.detail || detail } catch { /* ignore */ }
        logApiError(method, url, res.status, detail)
        throw new Error(detail)
      }
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = window.URL.createObjectURL(blob)
      a.download = filename
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      message.success('导出成功')
    } catch (err: any) { message.error(err.message || '导出失败') }
    finally { setLoading(false) }
  }

  const handleExportPlan = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    await downloadDoc(
      `${API_BASE}/api/v1/hr/employees/${selectedEmployee.id}/prejob-training-plan`,
      'POST',
      `岗前培训计划_${selectedEmployee.name || 'employee'}.docx`,
      setDownloadingWord,
      { training_items: buildItems() },
    )
  }

  const handleExportRecord = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    await downloadDoc(
      `${API_BASE}/api/v1/hr/employees/${selectedEmployee.employee_number}/training-record`,
      'POST',
      `培训记录_${selectedEmployee.name}.docx`,
      setDownloadingRecord,
      { training_items: buildItems() },
    )
  }

  const handleExportPermit = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    await downloadDoc(
      `${API_BASE}/api/v1/hr/employees/${selectedEmployee.employee_number}/work-permit`,
      'POST',
      `上岗证_${selectedEmployee.name}.docx`,
      setDownloadingPermit,
      { training_items: buildItems() },
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <Space wrap size="middle">
          <Select
            showSearch
            placeholder="输入工号或姓名搜索员工"
            value={selectedEmployeeId || undefined}
            onChange={setSelectedEmployeeId}
            options={employees.map((e) => ({
              value: e.id,
              label: `${e.employee_number} - ${e.name} (${e.department}) [${e.source || '新入职'}]`,
            }))}
            onSearch={handleSearch}
            loading={loading}
            filterOption={false}
            style={{ minWidth: 320 }}
          />
          <Button type="primary" icon={<DownloadOutlined />} onClick={handleExportPlan} loading={downloadingWord}>导出岗前培训计划</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportRecord} loading={downloadingRecord}>导出培训记录</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportPermit} loading={downloadingPermit}>导出上岗证</Button>
        </Space>
      </Card>

      {selectedEmployee && (
        <div id="print-area" className="space-y-6">
          {/* ===== Part I: 员工概况 (匹配模板) ===== */}
          <Card className="no-print-padding">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: '16%' }} /><col style={{ width: '17%' }} />
                <col style={{ width: '16%' }} /><col style={{ width: '17%' }} />
                <col style={{ width: '16%' }} /><col style={{ width: '18%' }} />
              </colgroup>
              <tbody>
                <tr>
                  <td colSpan={6} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第一部分：员工概况 Part I: Description of the employee
                  </td>
                </tr>
                <tr>
                  <td style={LABEL}>姓名<br/>Name</td><td style={VALUE}>{selectedEmployee.name}</td>
                  <td style={LABEL}>学历<br/>Education</td><td style={VALUE}>{selectedEmployee.education || ''}</td>
                  <td style={LABEL}>类别<br/>Type</td><td style={VALUE}>{selectedEmployee.source || '新入职'}</td>
                </tr>
                <tr>
                  <td style={LABEL}>毕业院校<br/>Graduation school</td><td style={VALUE}>{selectedEmployee.school || ''}</td>
                  <td style={LABEL}></td><td style={VALUE}></td>
                  <td style={LABEL}>毕业时间<br/>Graduation time</td><td style={VALUE}>{selectedEmployee.graduation_date || ''}</td>
                </tr>
                <tr>
                  <td style={LABEL}>部门<br/>Dept.</td><td style={VALUE}>{selectedEmployee.department}</td>
                  <td style={LABEL}>拟定岗位<br/>Intended post</td><td style={VALUE}>{selectedEmployee.position || ''}</td>
                  <td style={LABEL}>职称<br/>Title</td><td style={VALUE}></td>
                </tr>
                <tr>
                  <td style={LABEL}>报到日期<br/>Entry date</td><td style={VALUE}>{selectedEmployee.hire_date || ''}</td>
                  <td style={LABEL}>预定培训期<br/>Training period</td><td style={{...VALUE}} colSpan={3}></td>
                </tr>
              </tbody>
            </table>
          </Card>

          {/* ===== Part II & IV: 培训计划 + 完成确认 (匹配模板) ===== */}
          <Card className="no-print-padding">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: '4%' }} /><col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
                <col style={{ width: '8%' }} /><col style={{ width: '8%' }} /><col style={{ width: '8%' }} />
                <col style={{ width: '10%' }} /><col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
              </colgroup>
              <tbody>
                {/* 标题行 */}
                <tr>
                  <td colSpan={10} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第二部分：培训计划/内容 Part II: Training plans/content
                  </td>
                  <td colSpan={3} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第四部分：培训完成情况确认 Part IV: Training completion
                  </td>
                </tr>
                {/* 表头 */}
                <tr style={{ background: '#f5f5f5' }}>
                  <td style={CELL}></td>
                  <td style={CELL} colSpan={4}>培训内容 Training items</td>
                  <td style={CELL} colSpan={2}>计划完成期限 Plan date</td>
                  <td style={CELL} colSpan={2}>培训师 Trainer</td>
                  <td style={CELL}>培训方式 Method</td>
                  <td style={CELL}>培训日期 Date</td>
                  <td style={CELL}>员工/日期</td>
                  <td style={CELL}>培训师/日期</td>
                </tr>
                {/* 培训明细行 */}
                {selectedSops.length > 0 ? selectedSops.map((item, i) => (
                  <tr key={i}>
                    <td style={{...CELL, textAlign: 'center'}}>{i + 1}</td>
                    <td style={CELL} colSpan={4}>{item.sop_number ? `${item.sop_number} ` : ''}{item.file_name || ''}</td>
                    <td style={CELL} colSpan={2}>
                      <DatePicker size="small" style={{ width: '100%' }} placeholder="完成期限"
                        value={sopPlanDates[item.id] ? dayjs(sopPlanDates[item.id]) : null}
                        onChange={(d) => setSopPlanDates(prev => ({...prev, [item.id]: d ? d.format('YYYY-MM-DD') : ''}))} />
                    </td>
                    <td style={CELL} colSpan={2}>
                      <Select size="small" value={sopTrainers[item.id] || undefined}
                        onChange={v => setSopTrainers(prev => ({...prev, [item.id]: v}))}
                        options={trainers} placeholder="选培训师" style={{ width: '100%' }}
                        showSearch filterOption={(input, option) => (option?.label||'').toLowerCase().includes(input.toLowerCase())} />
                    </td>
                    <td style={CELL}>
                      <Select size="small" value={sopMethods[item.id] || undefined}
                        onChange={v => updateSopMethod(item.id, v)}
                        options={[{value:'面授',label:'面授'},{value:'自学',label:'自学'},{value:'自学+面授',label:'自学+面授'}]}
                        placeholder="选择" style={{ width: '100%' }} />
                    </td>
                    <td style={CELL}></td><td style={CELL}></td><td style={CELL}></td>
                  </tr>
                )) : (
                  <tr><td style={CELL} colSpan={13}>选择员工后将自动加载岗位培训内容</td></tr>
                )}
                {/* Part III: 审核批准 */}
                <tr>
                  <td colSpan={10} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第三部分：培训计划审核批准 Part III: Training plans review and approval
                  </td>
                  <td colSpan={3} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    备注 Remarks
                  </td>
                </tr>
                <tr>
                  <td style={LABEL} colSpan={3}>部门/日期<br/>Dept./Date</td>
                  <td style={VALUE} colSpan={2}></td>
                  <td style={LABEL} colSpan={2}>HR/日期<br/>HR/Date</td>
                  <td style={VALUE} colSpan={3}></td>
                  <td style={LABEL}>QA/日期<br/>QA/Date</td>
                  <td style={VALUE} colSpan={2}></td>
                  <td style={VALUE} colSpan={3}></td>
                </tr>
              </tbody>
            </table>
          </Card>
        </div>
      )}
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .no-print-padding .ant-card-body { padding: 0 !important; }
        }
      `}</style>
    </div>
  )
}
