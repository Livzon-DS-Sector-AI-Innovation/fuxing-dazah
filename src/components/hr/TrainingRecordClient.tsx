'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Select, Space, Spin } from 'antd'
import { FileTextOutlined, PrinterOutlined, DownloadOutlined } from '@ant-design/icons'
import { Employee } from '@/types/hr'
import { fetchEmployees, fetchOnboardingTrainingRecord } from '@/lib/api/hr'

export default function TrainingRecordClient() {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchEmployees({ page_size: 200 })
      .then((res) => {
        // eslint-disable-next-line no-console
        console.log('fetchEmployees success:', res)
        setEmployees(res.data || [])
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('fetchEmployees error:', err)
        message.error('加载员工列表失败: ' + (err.message || JSON.stringify(err) || '未知错误'))
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
      await fetchOnboardingTrainingRecord(selectedEmployee.id, selectedEmployee.name)
      message.success('培训记录已导出')
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
            导出Word
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
                  QR.SOP.PM.003/18（格式） P1/12
                </div>
                <div className="text-lg font-bold">丽珠集团新北江制药股份有限公司</div>
                <div className="text-base font-semibold mt-1">新员工入职培训记录</div>
              </div>
            }
            className="training-record-preview"
          >
            <div className="mb-4">
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第一部分：新员工概况</div>
              <table className="w-full border-collapse text-sm">
                <tbody>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 w-24 bg-gray-50">姓　　名</td>
                    <td className="border border-gray-300 px-3 py-2 w-32">{selectedEmployee.name}</td>
                    <td className="border border-gray-300 px-3 py-2 w-24 bg-gray-50">性　别</td>
                    <td className="border border-gray-300 px-3 py-2 w-32">{selectedEmployee.gender || ''}</td>
                    <td className="border border-gray-300 px-3 py-2 w-24 bg-gray-50">工作卡号</td>
                    <td className="border border-gray-300 px-3 py-2">{selectedEmployee.employee_number}</td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">部　　门</td>
                    <td className="border border-gray-300 px-3 py-2">{selectedEmployee.department}</td>
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">拟定岗位</td>
                    <td className="border border-gray-300 px-3 py-2" colSpan={3}>{selectedEmployee.position}</td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">报到日期</td>
                    <td className="border border-gray-300 px-3 py-2">{selectedEmployee.hire_date || ''}</td>
                    <td className="border border-gray-300 px-3 py-2 bg-gray-50">转正日期</td>
                    <td className="border border-gray-300 px-3 py-2" colSpan={3}></td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div>
              <div className="font-bold mb-2 border-b border-gray-300 pb-1">第二部分：培训记录</div>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border border-gray-300 bg-gray-50">
                    <th className="border border-gray-300 px-3 py-2 text-left w-1/2">培训内容</th>
                    <th className="border border-gray-300 px-3 py-2 text-left w-24">员工签名</th>
                    <th className="border border-gray-300 px-3 py-2 text-left w-24">考核人</th>
                    <th className="border border-gray-300 px-3 py-2 text-left w-24">日期</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="border border-gray-300 px-3 py-2 font-medium" colSpan={4}>
                      人事行政部 <span className="float-right text-gray-500">考核成绩：</span>
                    </td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">公司历史、企业文化、职业道德等</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">公司用工管理制度</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">公司其它规章制度</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr>
                    <td className="border border-gray-300 px-3 py-2 font-medium" colSpan={4}>
                      QA <span className="float-right text-gray-500">考核成绩：</span>
                    </td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">人员卫生要求</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">《药品生产质量管理规范》（GMP）</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">《药品管理法》等药品生产相关法律法规</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr>
                    <td className="border border-gray-300 px-3 py-2 font-medium" colSpan={4}>
                      安全环保部 <span className="float-right text-gray-500">考核成绩：</span>
                    </td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">公司安全生产制度和相关要求</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">公司职业健康方面知识</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2">安全生产、劳动保护的意义</td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                  </tr>
                  <tr>
                    <td className="border border-gray-300 px-3 py-2 font-medium" colSpan={4}>其他培训内容</td>
                  </tr>
                  <tr className="border border-gray-300">
                    <td className="border border-gray-300 px-3 py-2 h-16"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
                    <td className="border border-gray-300 px-3 py-2"></td>
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
          <p>请在上方选择员工以生成入职培训记录</p>
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
