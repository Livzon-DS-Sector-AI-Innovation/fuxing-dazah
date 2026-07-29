'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Select, Space } from 'antd'
import { FileTextOutlined, PrinterOutlined, DownloadOutlined } from '@ant-design/icons'
import { Employee } from '@/types/hr'
import { fetchEmployees, fetchPrejobTrainingPlan } from '@/lib/hr'

const DEPT_CONTENT_MAP: Record<string, string[]> = {
  '人事行政部': [
    '公司级公用文件(详见附件一)',
    '部门级公用文件(详见附件二)',
    '人事行政部人事行政专员岗位文件(详见附件三)',
    '人事行政专员岗位职责(QP.PM.053)',
    '生产安全知识',
    '岗前培训计划',
  ] }

export default function PreJobPlanClient() {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

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

  const handleExport = async () => {
    if (!selectedEmployee) {
      message.warning('请先选择员工')
      return
    }
    setDownloading(true)
    try {
      await fetchPrejobTrainingPlan(selectedEmployee.id, selectedEmployee.name)
      message.success('岗前培训计划已导出')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setDownloading(false)
    }
  }

  const handlePrint = () => {
    if (!selectedEmployee) {
      message.warning('请先选择员工')
      return
    }
    window.print()
  }

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
            onClick={handleExport}
            loading={downloading}
          >
            导出Excel
          </Button>
          <Button
            icon={<PrinterOutlined />}
            onClick={handlePrint}
            disabled={!selectedEmployee}
          >
            打印
          </Button>
        </Space>
      </Card>

      {/* 打印预览区 */}
      {selectedEmployee && (
        <div id="print-area" className="print-area">
          <Card
            title={
              <div className="text-center">
                <div className="text-xs text-gray-500 mb-1">
                  QR.SOP.PM.003/18（格式） P2/12
                </div>
                <div className="text-lg font-bold">丽珠集团福州福兴医药有限公司</div>
                <div className="text-base font-semibold mt-1">岗前培训计划</div>
              </div>
            }
            className="training-record-preview"
          >
            <div className="mb-4">
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第一部分：员工概况</div>
              <table className="w-full border-collapse text-sm">
                <tbody>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 w-24 bg-gray-50">姓　　名</td>
                    <td className="border border-gray-300 px-3 py-2 w-32">{selectedEmployee.name}</td>
                    <td className="border border-gray-300 px-3 py-2 w-24 bg-gray-50">部　　门</td>
                    <td className="border border-gray-300 px-3 py-2">{selectedEmployee.department}</td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">工作卡号</td>
                    <td className="border border-gray-300 px-3 py-2">{selectedEmployee.employee_number}</td>
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">报到日期</td>
                    <td className="border border-gray-300 px-3 py-2">{selectedEmployee.hire_date || ''}</td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">拟定岗位</td>
                    <td className="border border-gray-300 px-3 py-2" colSpan={3}>{selectedEmployee.position}</td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">类　　别</td>
                    <td className="border border-gray-300 px-3 py-2" colSpan={3}>
                      <span className="mr-4">□ 新员工</span>
                      <span className="mr-4">□ 岗位/职位变动</span>
                      <span>□ 长期（三个月以上）休假</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div>
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第二部分：培训计划</div>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border border-gray-300 bg-gray-50">
                    <th className="border border-gray-300 px-3 py-2 text-left w-16">序号</th>
                    <th className="border border-gray-300 px-3 py-2 text-left">培训内容</th>
                    <th className="border border-gray-300 px-3 py-2 text-left w-32">完成期限</th>
                    <th className="border border-gray-300 px-3 py-2 text-left w-32">培训师</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const contents = DEPT_CONTENT_MAP[selectedEmployee.department || ''] || []
                    return Array.from({ length: 10 }, (_, i) => (
                      <tr key={i} className="border border-gray-300">
                        <td className="border border-gray-300 px-3 py-2 text-center">{i + 1}</td>
                        <td className="border border-gray-300 px-3 py-2 h-8">{contents[i] || ''}</td>
                        <td className="border border-gray-300 px-3 py-2"></td>
                        <td className="border border-gray-300 px-3 py-2"></td>
                      </tr>
                    ))
                  })()}
                </tbody>
              </table>
            </div>

            <div className="mt-4">
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第三部分：审核批准</div>
              <table className="w-full border-collapse text-sm">
                <tbody>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 w-48 bg-gray-50">部门负责人</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2 w-24 bg-gray-50">日　　期</td>
                    <td className="border border-gray-300 px-3 py-2 w-48"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">人事行政部负责人</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">日　　期</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">QA负责人</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">日　　期</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">质量管理负责人</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">日　　期</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {!selectedEmployee && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>请在上方选择员工以生成岗前培训计划</p>
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
