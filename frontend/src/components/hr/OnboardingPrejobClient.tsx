'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Empty, Select, Space, Input, DatePicker } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee } from '@/types/hr'
import { downloadBase64File } from '@/lib/hr'
import {
  fetchTrainingCandidates,
  fetchPositionTrainings,
  fetchTrainers,
  downloadPrejobTrainingPlan,
  downloadEmployeeTrainingRecord,
  downloadWorkPermit,
  checkExistingTrainingLedgers,
  createTrainingLedger,
} from '@/actions/hr'

const CELL = { border: '1px solid #999', padding: '6px 10px', fontSize: '13px' } as const
const LABEL = { ...CELL, background: '#f5f5f5', fontWeight: 600, textAlign: 'center' as const, width: '15%' }
const VALUE = { ...CELL }

export default function OnboardingPrejobClient() {
  const { message, modal } = App.useApp()
  const [employees, setEmployees] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  // 已选员工单独保存：再次搜索会整体替换 employees，不能只靠 employees.find 取当前员工
  const [selectedEmployee, setSelectedEmployee] = useState<(typeof employees)[number] | null>(null)
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
      const d = await fetchTrainingCandidates(keyword)
      setEmployees(d.data || [])
    } catch (err: any) {
      message.error('加载失败: ' + (err.message || '未知错误'))
    } finally { setLoading(false) }
  }

  const handleSearch = async (keyword: string) => {
    loadEmployees(keyword || undefined)
  }

  // 选中员工后，根据岗位+部门自动加载关联培训大类
  useEffect(() => {
    if (!selectedEmployee) return
    const pos = selectedEmployee.position
    const dept = selectedEmployee.department
    if (!pos) return

    // 员工再次切换后丢弃上一次请求的响应，避免把上一名员工的培训内容填进来
    let outdated = false
    fetchPositionTrainings({ position_name: pos, department: dept || undefined })
      .then(res => {
        if (outdated) return
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
      .catch((err: any) => {
        if (outdated) return
        message.error('加载培训内容失败: ' + (err.message || '未知错误'))
      })
    return () => { outdated = true }
  }, [selectedEmployeeId])

  // 加载培训师列表
  useEffect(() => {
    fetchTrainers({ page_size: 200 })
      .then(res => setTrainers((res.data||[]).map((t:any) => ({value:t.name,label:`${t.name}(${t.department})`}))))
      .catch(() => {})
  }, [])

  const [sopMethods, setSopMethods] = useState<Record<string, string>>({})
  const [sopTrainers, setSopTrainers] = useState<Record<string, string>>({})
  const [sopPlanDates, setSopPlanDates] = useState<Record<string, string>>({})

  // 切换员工：清空上一名员工残留的培训方式/培训师/完成期限及培训明细
  const handleSelectEmployee = (id: string) => {
    const emp = employees.find((e: any) => e.id === id) || null
    setSelectedEmployeeId(emp ? id : null)
    setSelectedEmployee(emp)
    setSelectedSops([])
    setSopMethods({})
    setSopTrainers({})
    setSopPlanDates({})
  }

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

  const handleExportPlan = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingWord(true)
    try {
      const r = await downloadPrejobTrainingPlan(
        selectedEmployee.employee_id || selectedEmployee.id,
        selectedEmployee.name || 'employee',
        buildItems(),
      )
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
    } catch (err) { message.error((err as Error)?.message || '导出失败') }
    finally { setDownloadingWord(false) }
  }

  const handleExportRecord = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingRecord(true)
    try {
      const items = buildItems()
      const r = await downloadEmployeeTrainingRecord(
        selectedEmployee.employee_number,
        selectedEmployee.name,
        items,
      )
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
      // 与培训台账联动：导出的培训记录顺势写入台账（此前纯下载零联动）
      const ledgerItems = items.filter((it) => it.plan_date && it.content)
      const skipped = items.length - ledgerItems.length
      if (ledgerItems.length === 0) {
        if (items.length > 0) {
          message.info('培训内容均未填「完成期限」，无法写入培训台账（台账需培训日期）')
        }
        return
      }
      // 写入前查重：同日期同主题已有记录的条目不再创建（创建接口本身不查重，重复导出会产生重复记录）
      const dupKeys = new Set<string>()
      const groups = Array.from(new Set(ledgerItems.map((it) => `${it.plan_date}\u0000${it.content}`)))
      try {
        const checks = await Promise.all(groups.map(async (g) => {
          const [training_date, training_subject] = g.split('\u0000')
          const r = await checkExistingTrainingLedgers({
            training_date, training_subject, employee_numbers: [selectedEmployee.employee_number],
          })
          return r.data?.employee_numbers?.length ? g : null
        }))
        checks.filter((g): g is string => !!g).forEach((g) => dupKeys.add(g))
      } catch {
        // 查重失败不阻断流程（按「无重复」继续）
      }
      const freshItems = ledgerItems.filter((it) => !dupKeys.has(`${it.plan_date}\u0000${it.content}`))
      if (freshItems.length === 0) {
        message.info('这些培训记录当天已在培训台账中，无需重复写入')
        return
      }
      const dupCount = ledgerItems.length - freshItems.length

      modal.confirm({
        title: '写入培训台账',
        content: `是否将本次导出的 ${freshItems.length} 条培训记录写入培训台账？${
          skipped > 0 ? `（${skipped} 条缺完成期限将跳过）` : ''
        }${dupCount > 0 ? `（${dupCount} 条当天已有同主题记录，将跳过）` : ''}`,
        okText: '写入台账',
        cancelText: '仅导出',
        onOk: async () => {
          let ok = 0
          for (const it of freshItems) {
            try {
              await createTrainingLedger({
                employee_number: selectedEmployee.employee_number,
                training_date: it.plan_date,
                training_subject: it.content,
                training_method: it.method || undefined,
                trainer: it.trainer || undefined,
                source_type: 'prejob_export',
                remarks: '入职培训记录表导出写入',
              })
              ok += 1
            } catch { /* 逐条容错，失败汇总 */ }
          }
          if (ok === freshItems.length) {
            message.success(`已写入培训台账 ${ok} 条，可在培训台账页查看`)
          } else {
            message.warning(`写入台账 ${ok}/${freshItems.length} 条，失败的条目请到台账页手动补录`)
          }
        },
      })
    } catch (err) { message.error((err as Error)?.message || '导出失败') }
    finally { setDownloadingRecord(false) }
  }

  const handleExportPermit = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingPermit(true)
    try {
      const r = await downloadWorkPermit(
        selectedEmployee.employee_number,
        selectedEmployee.name,
        buildItems(),
      )
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
    } catch (err) { message.error((err as Error)?.message || '导出失败') }
    finally { setDownloadingPermit(false) }
  }

  return (
    <div className="space-y-4">
      <Card>
        <Space wrap size="middle">
          <Select
            showSearch
            placeholder="输入工号或姓名搜索员工"
            value={selectedEmployeeId || undefined}
            onChange={handleSelectEmployee}
            options={employees.map((e) => ({
              value: e.id,
              label: `${e.employee_number} - ${e.name} (${e.department}) [${e.source || '新入职'}]`,
            }))}
            onSearch={handleSearch}
            loading={loading}
            filterOption={false}
            style={{ minWidth: 320 }}
          />
          <Button type="primary" icon={<DownloadOutlined />} onClick={handleExportPlan} loading={downloadingWord} disabled={!selectedEmployee}>导出岗前培训计划</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportRecord} loading={downloadingRecord} disabled={!selectedEmployee}>导出培训记录</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportPermit} loading={downloadingPermit} disabled={!selectedEmployee}>导出上岗证</Button>
        </Space>
      </Card>

      {/* 未选员工时的空状态（打印时隐藏） */}
      {!selectedEmployee && (
        <Card className="no-print">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先选择员工" />
        </Card>
      )}

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
