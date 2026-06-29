'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Select, Space, Input } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { Employee } from '@/types/hr'
import {
  fetchOnboardingRecords,
} from '@/lib/api/hr'

const CELL = { border: '1px solid #999', padding: '6px 10px', fontSize: '13px' } as const
const LABEL = { ...CELL, background: '#f5f5f5', fontWeight: 600, textAlign: 'center' as const, width: '15%' }
const VALUE = { ...CELL }

export default function OnboardingPrejobClient() {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  const [downloadingWord, setDownloadingWord] = useState(false)
  const [allSops, setAllSops] = useState<any[]>([])
  const [selectedSops, setSelectedSops] = useState<any[]>([])
  const [sopSearch, setSopSearch] = useState('')
  const [trainers, setTrainers] = useState<{value:string,label:string}[]>([])
  const [sopDept, setSopDept] = useState('')
  const [sopCat, setSopCat] = useState('')
  const [sopDepts, setSopDepts] = useState<{value:string,label:string}[]>([])
  const [sopCats, setSopCats] = useState<{value:string,label:string}[]>([])

  useEffect(() => {
    setLoading(true)
    fetchOnboardingRecords({ page_size: 50 })
      .then((res) => setEmployees(res.data || []))
      .catch((err) => message.error('加载入职台账失败: ' + (err.message || '未知错误')))
      .finally(() => setLoading(false))
  }, [])

  const handleSearch = async (keyword: string) => {
    if (!keyword || keyword.length < 1) return
    setLoading(true)
    try {
      const res = await fetchOnboardingRecords({ keyword, page_size: 30 })
      setEmployees(res.data || [])
    } catch (err: any) {
      message.error('搜索失败: ' + (err.message || '未知错误'))
    } finally { setLoading(false) }
  }

  const selectedEmployee = employees.find((e: any) => e.id === selectedEmployeeId)

  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

  // 加载部门和分类列表
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/departments`).then(r => r.json())
      .then(res => setSopDepts((res.data||[]).map((d:string) => ({value:d,label:d}))))
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/categories`).then(r => r.json())
      .then(res => setSopCats((res.data||[]).map((c:string) => ({value:c,label:c}))))
    fetch(`http://localhost:8000/api/v1/hr/trainers?page_size=200`).then(r => r.json())
      .then(res => setTrainers((res.data||[]).map((t:any) => ({value:t.name,label:`${t.name}(${t.department})`}))))
  }, [])

  // 按条件加载 SOP 列表
  useEffect(() => {
    const params = new URLSearchParams({ page_size: '200' })
    if (sopDept) params.set('department', sopDept)
    if (sopCat) params.set('category', sopCat)
    if (sopSearch) params.set('keyword', sopSearch)
    fetch(`${API_BASE}/api/v1/hr/sop-catalog?${params.toString()}`)
      .then(r => r.json())
      .then(res => setAllSops(res.data || []))
      .catch(() => setAllSops([]))
  }, [sopDept, sopCat, sopSearch])

  const [sopMethods, setSopMethods] = useState<Record<string, string>>({})
  const [sopTrainers, setSopTrainers] = useState<Record<string, string>>({})

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

  const handleExportWord = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingWord(true)
    try {
      const items = selectedSops.map(s => ({
        sop_number: s.sop_number || '',
        file_name: s.file_name || '',
        content: s.file_name || '',
        method: sopMethods[s.id] || '',
        trainer: sopTrainers[s.id] || '',
      }))
      const res = await fetch(`http://localhost:8000/api/v1/hr/employees/${selectedEmployee.employee_number}/onboarding-training-record`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ training_items: items }),
      })
      if (!res.ok) throw new Error('导出失败')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `入职培训记录_${selectedEmployee.name || 'employee'}.docx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
      message.success('入职培训记录已导出')
    } catch (err: any) { message.error(err.message || '导出失败') }
    finally { setDownloadingWord(false) }
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
              label: `${e.employee_number} - ${e.name} (${e.department})`,
            }))}
            onSearch={handleSearch}
            loading={loading}
            filterOption={false}
            style={{ minWidth: 320 }}
          />
          <Button type="primary" icon={<DownloadOutlined />} onClick={handleExportWord} loading={downloadingWord}>导出岗位员工培训计划(Word)</Button>
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
                  <td style={LABEL}>类别<br/>Type</td><td style={VALUE}>新员工</td>
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

          {/* ===== SOP 选择面板（打印时隐藏） ===== */}
          <Card className="no-print" title="SOP 目录（点击勾选加入培训计划）" size="small">
            <Space wrap style={{ marginBottom: 12 }}>
              <Select placeholder="部门" allowClear value={sopDept||undefined}
                onChange={v => { setSopDept(v||''); setSopCat('') }}
                options={sopDepts} style={{ width: 200 }} showSearch
                filterOption={(input, option) => (option?.label||'').toLowerCase().includes(input.toLowerCase())} />
              <Select placeholder="分类" allowClear value={sopCat||undefined}
                onChange={v => setSopCat(v||'')}
                options={sopCats} style={{ width: 200 }} />
              <Input.Search placeholder="搜索编号或名称" value={sopSearch}
                onChange={e => setSopSearch(e.target.value)} style={{ width: 260 }} allowClear />
            </Space>
            <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid #eee', borderRadius: 4 }}>
              {allSops.slice(0, 200).map(sop => {
                const sel = selectedSops.find(s => s.id === sop.id)
                return (
                  <div key={sop.id} onClick={() => toggleSop(sop)}
                    style={{ padding: '6px 12px', cursor: 'pointer', borderBottom: '1px solid #f0f0f0',
                      background: sel ? '#e6f4ff' : 'white', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <input type="checkbox" checked={!!sel} readOnly style={{ flexShrink: 0 }} />
                    <span style={{ fontSize: 12, color: '#999', flexShrink: 0 }}>{sop.sop_number || ''}</span>
                    <span style={{ flex: 1, fontSize: 13 }}>{sop.file_name}</span>
                    <span style={{ fontSize: 11, color: '#888', flexShrink: 0 }}>{sop.department}</span>
                    <span style={{ fontSize: 11, color: '#aaa', flexShrink: 0 }}>{sop.category}</span>
                  </div>
                )
              })}
            </div>
            <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#666' }}>已选 {selectedSops.length} 项</span>
              <Space>
                <Button size="small" onClick={() => {
                  const visibleIds = new Set(allSops.slice(0, 200).map(s => s.id))
                  const others = selectedSops.filter(s => !visibleIds.has(s.id))
                  setSelectedSops([...others, ...allSops.slice(0, 200)])
                }}>全选当前</Button>
                <Button size="small" onClick={() => {
                  const visibleIds = new Set(allSops.slice(0, 200).map(s => s.id))
                  setSelectedSops(prev => prev.filter(s => !visibleIds.has(s.id)))
                }}>取消全选</Button>
              </Space>
            </div>
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
                    <td style={CELL} colSpan={2}></td>
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
                  <tr><td style={CELL} colSpan={13}>请在上方 SOP 目录中勾选培训内容</td></tr>
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
