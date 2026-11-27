'use client'

// 离岗体检登记（重点岗位门禁）：未登记完成不能发起离职审批。
// 报告按扩展名 + 文件头校验（后端 validate_upload），这里只负责收集：日期 + 可选附件。

import { useState } from 'react'
import { App as AntdApp, Button, DatePicker, Space, Tag, Upload } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { OffboardingCaseDetail } from '@/types/hr'
import { downloadOffboardingHealthCheck, registerOffboardingHealthCheck } from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'

const ACCEPT = '.pdf,.jpg,.jpeg,.png'

export default function HealthCheckPanel({
  detail,
  onChanged,
}: {
  detail: OffboardingCaseDetail
  /** 登记成功后刷新详情 */
  onChanged: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  const [checkDate, setCheckDate] = useState<dayjs.Dayjs | null>(
    detail.health_check_date ? dayjs(detail.health_check_date) : dayjs(),
  )
  const [busy, setBusy] = useState(false)
  const [downloadBusy, setDownloadBusy] = useState(false)

  const register = async (file?: File) => {
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('health_check_done', 'true')
      if (checkDate) fd.append('health_check_date', checkDate.format('YYYY-MM-DD'))
      if (file) fd.append('file', file)
      await registerOffboardingHealthCheck(detail.id, fd)
      message.success(file ? '体检报告已上传，登记完成' : '体检登记已保存')
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '体检登记失败')
    } finally {
      setBusy(false)
    }
  }

  const download = async () => {
    setDownloadBusy(true)
    try {
      const file = await downloadOffboardingHealthCheck(detail.id, detail.health_check_file_name || '')
      downloadBase64File(file.base64, file.filename)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '下载体检报告失败')
    } finally {
      setDownloadBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <Tag color={detail.health_check_done ? 'success' : 'warning'}>
          {detail.health_check_done ? '已完成' : '未完成'}
        </Tag>
        {detail.health_check_done && (
          <span className="text-[var(--color-slate)]">
            完成日期 {detail.health_check_date || '—'}
          </span>
        )}
        {detail.health_check_file_name && (
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            loading={downloadBusy}
            onClick={() => void download()}
            className="px-0"
          >
            {detail.health_check_file_name}
          </Button>
        )}
      </div>
      <Space wrap>
        <DatePicker
          value={checkDate}
          onChange={setCheckDate}
          placeholder="体检完成日期"
          disabledDate={(d) => d.isAfter(dayjs(), 'day')}
        />
        <Upload
          accept={ACCEPT}
          showUploadList={false}
          maxCount={1}
          beforeUpload={(file) => {
            void register(file)
            return false // 不走 Upload 自带的上传，由上面的处理函数提交
          }}
        >
          <Button icon={<UploadOutlined />} loading={busy}>
            {detail.health_check_file_name ? '重新上传报告' : '上传报告并登记'}
          </Button>
        </Upload>
        {!detail.health_check_file_name && (
          <Button loading={busy} onClick={() => void register()}>
            仅登记完成（不传报告）
          </Button>
        )}
      </Space>
    </div>
  )
}

/** 已登记完成的体检：收进基本信息里的一行，不再单独占面板 */
export function healthCheckText(detail: OffboardingCaseDetail): string {
  if (!detail.health_check_required) return '非重点岗位，无需体检'
  if (!detail.health_check_done) return '未完成'
  const parts = [detail.health_check_date || '日期未填']
  if (detail.health_check_file_name) parts.push(`报告 ${detail.health_check_file_name}`)
  return parts.join(' · ')
}
