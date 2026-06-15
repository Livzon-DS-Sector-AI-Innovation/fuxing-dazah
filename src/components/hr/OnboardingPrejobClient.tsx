'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Select, Space } from 'antd'
import {
  FileTextOutlined,
  PrinterOutlined,
  DownloadOutlined } from '@ant-design/icons'
import { Employee } from '@/types/hr'
import {
  fetchEmployees,
  fetchOnboardingTrainingRecord,
  fetchPrejobTrainingPlan,
  fetchOnboardingEvaluationByEmployeeId } from '@/lib/api/hr'

const DEPT_CONTENT_MAP: Record<string, string[]> = {
  '人事行政部': [
    '公司级公用文件(详见附件一)',
    '部门级公用文件(详见附件二)',
    '人事行政部人事行政专员岗位文件(详见附件三)',
    '人事行政专员岗位职责(QP.PM.053)',
    '生产安全知识',
    '岗前培训计划',
  ] }

const TD_LABEL = {
  border: '1px solid #1f2937',
  padding: '8px' } as React.CSSProperties

const TD_VALUE = {
  border: '1px solid #1f2937',
  padding: '8px' } as React.CSSProperties

const TH = {
  border: '1px solid #1f2937',
  padding: '8px' } as React.CSSProperties

export default function OnboardingPrejobClient() {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  const [downloadingWord, setDownloadingWord] = useState(false)
  const [downloadingExcel, setDownloadingExcel] = useState(false)
  const [downloadingEval, setDownloadingEval] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchEmployees({ page_size: 200 })
      .then((res) => {
        setEmployees(res.data || [])
      })
      .catch((err) => {
        message.error('加载员工列表失败: ' + (err.message || '未知错误'))
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const selectedEmployee = employees.find((e) => e.id === selectedEmployeeId)

  const handleExportWord = async () => {
    if (!selectedEmployee) {
      message.warning('请先选择员工')
      return
    }
    setDownloadingWord(true)
    try {
      await fetchOnboardingTrainingRecord(selectedEmployee.id, selectedEmployee.name)
      message.success('入职培训记录已导出')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setDownloadingWord(false)
    }
  }

  const handleExportExcel = async () => {
    if (!selectedEmployee) {
      message.warning('请先选择员工')
      return
    }
    setDownloadingExcel(true)
    try {
      await fetchPrejobTrainingPlan(selectedEmployee.id, selectedEmployee.name)
      message.success('岗前培训计划已导出')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setDownloadingExcel(false)
    }
  }

  const handleExportEvaluation = async () => {
    if (!selectedEmployee) {
      message.warning('请先选择员工')
      return
    }
    setDownloadingEval(true)
    try {
      await fetchOnboardingEvaluationByEmployeeId(
        selectedEmployee.id,
        selectedEmployee.name
      )
      message.success('员工上岗评估表已导出')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setDownloadingEval(false)
    }
  }

  const handlePrint = () => {
    if (!selectedEmployee) {
      message.warning('请先选择员工')
      return
    }
    window.print()
  }

  const prejobContents = selectedEmployee
    ? DEPT_CONTENT_MAP[selectedEmployee.department || ''] || []
    : []

  return (
    <div className="space-y-6">
      {/* 顶部选择器 */}
      <Card>
        <Space wrap size="middle" align="center">
          <Select
            showSearch
            placeholder="选择员工"
            value={selectedEmployeeId || undefined}
            onChange={(value) => setSelectedEmployeeId(value)}
            options={employees.map((e) => ({
              value: e.id,
              label: `${e.employee_number} - ${e.name} (${e.department})` }))}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
            style={{ minWidth: 320 }}
          />
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={handleExportWord}
            loading={downloadingWord}
          >
            导出入职培训记录(Word)
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={handleExportExcel}
            loading={downloadingExcel}
          >
            导出岗前培训计划(Excel)
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={handleExportEvaluation}
            loading={downloadingEval}
          >
            导出员工上岗评估表(Excel)
          </Button>
          <Button icon={<PrinterOutlined />} onClick={handlePrint} disabled={!selectedEmployee}>
            打印
          </Button>
        </Space>
      </Card>

      {/* 打印预览区 */}
      {selectedEmployee && (
        <div id="print-area" className="print-area space-y-6">
          {/* ─── 新员工入职培训记录 ─── */}
          <Card
            title={
              <div className="text-center">
                <div className="text-xs text-gray-500 mb-1">QR.SOP.PM.003/18（格式） P1/12</div>
                <div className="text-lg font-bold">丽珠集团新北江制药股份有限公司</div>
                <div className="text-base font-semibold mt-1">新员工入职培训记录</div>
              </div>
            }
            className="training-record-preview"
          >
            <div className="max-w-3xl mx-auto p-4 text-sm leading-relaxed">
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第一部分：新员工概况</div>
              <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                <tbody>
                  <tr>
                    <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">姓　　名</td>
                    <td style={TD_VALUE} className="w-32 text-center">{selectedEmployee.name}</td>
                    <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">性　别</td>
                    <td style={TD_VALUE} className="w-32 text-center">{selectedEmployee.gender || ''}</td>
                    <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">工作卡号</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.employee_number}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">部　　门</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.department}</td>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">拟定岗位</td>
                    <td style={TD_VALUE} colSpan={3} className="text-center">{selectedEmployee.position}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">报到日期</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.hire_date || ''}</td>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">转正日期</td>
                    <td style={TD_VALUE} colSpan={3} className="text-center"></td>
                  </tr>
                </tbody>
              </table>

              <div className="font-bold mb-2 mt-4 border-b border-gray-300 pb-1">第二部分：培训记录</div>
              <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={TH} className="text-left w-1/2 bg-gray-50">培训内容</th>
                    <th style={TH} className="text-left w-24 bg-gray-50">员工签名</th>
                    <th style={TH} className="text-left w-24 bg-gray-50">考核人</th>
                    <th style={TH} className="text-left w-24 bg-gray-50">日期</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td style={TD_VALUE} colSpan={4} className="font-medium">
                      人事行政部 <span className="float-right text-gray-500">考核成绩：</span>
                    </td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>公司历史、企业文化、职业道德等</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>公司用工管理制度</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>公司其它规章制度</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={4} className="font-medium">
                      QA <span className="float-right text-gray-500">考核成绩：</span>
                    </td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>人员卫生要求</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>《药品生产质量管理规范》（GMP）</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>《药品管理法》等药品生产相关法律法规</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={4} className="font-medium">安全环保部 <span className="float-right text-gray-500">考核成绩：</span></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>公司安全生产制度和相关要求</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>公司职业健康方面知识</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE}>安全生产、劳动保护的意义</td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={4} className="font-medium">其他培训内容</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_VALUE, height: '64px' }}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                    <td style={TD_VALUE}></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          {/* ─── 岗前培训计划 ─── */}
          <Card
            title={
              <div className="text-center">
                <div className="text-xs text-gray-500 mb-1">QR.SOP.PM.003/18（格式） P2/12</div>
                <div className="text-lg font-bold">丽珠集团新北江制药股份有限公司</div>
                <div className="text-base font-semibold mt-1">岗前培训计划</div>
              </div>
            }
            className="training-record-preview"
          >
            <div className="max-w-3xl mx-auto p-4 text-sm leading-relaxed">
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第一部分：员工概况</div>
              <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                <tbody>
                  <tr>
                    <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">姓　　名</td>
                    <td style={TD_VALUE} className="w-32 text-center">{selectedEmployee.name}</td>
                    <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">部　　门</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.department}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">工作卡号</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.employee_number}</td>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">报到日期</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.hire_date || ''}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">拟定岗位</td>
                    <td style={TD_VALUE} colSpan={3} className="text-center">{selectedEmployee.position}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">类　　别</td>
                    <td style={TD_VALUE} colSpan={3}>
                      <span className="mr-4">□ 新员工</span>
                      <span className="mr-4">□ 岗位/职位变动</span>
                      <span>□ 长期（三个月以上）休假</span>
                    </td>
                  </tr>
                </tbody>
              </table>

              <div className="font-bold mb-2 mt-4 border-b border-gray-300 pb-1">第二部分：培训计划</div>
              <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={TH} className="text-left w-16 bg-gray-50">序号</th>
                    <th style={TH} className="text-left bg-gray-50">培训内容</th>
                    <th style={TH} className="text-left w-32 bg-gray-50">完成期限</th>
                    <th style={TH} className="text-left w-32 bg-gray-50">培训师</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.from({ length: 10 }, (_, i) => (
                    <tr key={i}>
                      <td style={TD_VALUE} className="text-center">{i + 1}</td>
                      <td style={{ ...TD_VALUE, height: '32px' }}>{prejobContents[i] || ''}</td>
                      <td style={TD_VALUE}></td>
                      <td style={TD_VALUE}></td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mt-4">
                <div className="font-bold mb-2 border-b border-gray-300 pb-1">第三部分：审核批准</div>
                <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                  <tbody>
                    <tr>
                      <td style={TD_LABEL} className="w-48 bg-gray-50 font-bold text-center">部门负责人</td>
                      <td style={TD_VALUE}></td>
                      <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">日　　期</td>
                      <td style={TD_VALUE} className="w-48"></td>
                    </tr>
                    <tr>
                      <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">人事行政部负责人</td>
                      <td style={TD_VALUE}></td>
                      <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">日　　期</td>
                      <td style={TD_VALUE}></td>
                    </tr>
                    <tr>
                      <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">QA负责人</td>
                      <td style={TD_VALUE}></td>
                      <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">日　　期</td>
                      <td style={TD_VALUE}></td>
                    </tr>
                    <tr>
                      <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">质量管理负责人</td>
                      <td style={TD_VALUE}></td>
                      <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">日　　期</td>
                      <td style={TD_VALUE}></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </Card>

          {/* ─── 员工上岗评估表 ─── */}
          <Card
            title={
              <div className="text-center">
                <div className="text-xs text-gray-500 mb-1">QR.SOP.PM.003/18（格式） P9/12</div>
                <div className="text-lg font-bold">丽珠集团新北江制药股份有限公司</div>
                <div className="text-base font-semibold mt-1">员工上岗评估表</div>
              </div>
            }
            className="training-record-preview"
          >
            <div className="max-w-3xl mx-auto p-4 text-sm leading-relaxed">
              <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                <tbody>
                  <tr>
                    <td style={TD_LABEL} className="w-16 bg-gray-50 font-bold text-center">姓名</td>
                    <td style={TD_VALUE} className="w-24 text-center">{selectedEmployee.name}</td>
                    <td style={TD_LABEL} className="w-16 bg-gray-50 font-bold text-center">性别</td>
                    <td style={TD_VALUE} className="w-24 text-center">{selectedEmployee.gender || ''}</td>
                    <td style={TD_LABEL} className="w-24 bg-gray-50 font-bold text-center">所在部门/岗位</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.department}/{selectedEmployee.position}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">工作卡号</td>
                    <td style={TD_VALUE} className="text-center" colSpan={5}>{selectedEmployee.employee_number}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">入厂时间</td>
                    <td style={TD_VALUE} className="text-center">{selectedEmployee.hire_date || ''}</td>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">培训/考核期</td>
                    <td style={TD_VALUE} className="text-center"></td>
                    <td style={TD_LABEL} className="bg-gray-50 font-bold text-center">转正时间</td>
                    <td style={TD_VALUE} className="text-center"></td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, textAlign: 'center' }} className="font-bold bg-gray-50" colSpan={6}>上岗培训期内考核内容、培训内容和结果</td>
                  </tr>
                  {Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <td style={{ ...TD_VALUE, height: '28px' }} colSpan={6}></td>
                    </tr>
                  ))}
                  <tr>
                    <td style={TD_LABEL} className="font-bold bg-gray-50" colSpan={6}>培训/考核期综合评语：</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_VALUE, height: '48px' }} colSpan={6}></td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={6}>
                      □经考核该员工培训期表现优秀/确认，同意该员工正式上岗，担任<span style={{ borderBottom: '1px solid #1f2937', padding: '0 8px', display: 'inline-block', minWidth: '60px' }}></span>岗位。
                    </td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={6}>
                      □经考核该员工培训期内表现不符合此岗位要求，不准上岗。
                    </td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={6}>考核方式：□理论 □实操 □现场</td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={6}>
                      <div className="flex justify-between">
                        <span>部门负责人签名：<span style={{ borderBottom: '1px solid #1f2937', padding: '0 8px', display: 'inline-block', minWidth: '80px' }}></span></span>
                        <span>日期：<span style={{ borderBottom: '1px solid #1f2937', padding: '0 8px', display: 'inline-block', minWidth: '100px' }}></span></span>
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td style={TD_VALUE} colSpan={6}>备注：培训期延长或转岗，由部门主管决定。</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, textAlign: 'center' }} className="font-bold bg-gray-50" colSpan={6}>上岗考核审批</td>
                  </tr>
                  {['部门负责人', '人事行政部负责人', '质量管理负责人'].map((title, i) => (
                    <tr key={i}>
                      <td style={{ ...TD_VALUE, width: '128px' }} className="text-center">□同意  □不同意</td>
                      <td style={{ ...TD_LABEL, width: '128px' }} className="text-center font-bold bg-gray-50" colSpan={2}>{title}</td>
                      <td style={{ ...TD_VALUE, width: '128px' }} className="text-center"></td>
                      <td style={{ ...TD_LABEL, width: '64px' }} className="text-center font-bold bg-gray-50">日期</td>
                      <td style={TD_VALUE} className="text-center"></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {!selectedEmployee && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>请在上方选择员工以生成入职培训记录、岗前培训计划和员工上岗评估表</p>
        </div>
      )}

      {/* 打印样式 */}
      <style jsx global>{`
        @media print {
          body * {
            visibility: hidden;
          }
          #print-area,
          #print-area * {
            visibility: visible;
          }
          #print-area {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
          }
          .ant-card-head {
            border-bottom: 1px solid #000 !important;
          }
        }
      `}</style>
    </div>
  )
}
