'use client'

import { useState } from 'react'
import { App, Button, Space, Typography } from 'antd'
import { PaperClipOutlined } from '@ant-design/icons'
import { downloadTitleAttachment } from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'

interface AttachmentFile {
  file_token: string
  name: string
  size?: number
}

/** 申报附件列表：文件名可点击下载（飞书 Base 附件素材，经后端校验归属）。
 *  评委投票页与 HR 申报详情共用。 */
export default function TitleReviewAttachments({
  applicationId,
  attachments,
}: {
  applicationId: string
  attachments?: Record<string, AttachmentFile[]> | null
}) {
  const { message } = App.useApp()
  const [downloading, setDownloading] = useState<string | null>(null)

  const entries = Object.entries(attachments || {}).filter(
    ([, files]) => files && files.length > 0,
  )
  if (entries.length === 0) return null

  const handleDownload = async (token: string) => {
    setDownloading(token)
    try {
      const r = await downloadTitleAttachment(applicationId, token)
      downloadBase64File(r.base64, r.filename || '附件')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '附件下载失败')
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div>
      <Typography.Text strong>附件材料</Typography.Text>
      <div className="mt-1 space-y-1">
        {entries.map(([category, files]) => (
          <div key={category} className="text-[13px] flex items-start gap-1 flex-wrap">
            <span className="text-[var(--color-text-secondary)] shrink-0">{category}：</span>
            <Space size={[4, 4]} wrap>
              {(files || []).map((f) =>
                f.file_token ? (
                  <Button
                    key={f.file_token}
                    type="link"
                    size="small"
                    className="!px-0 !h-auto"
                    icon={<PaperClipOutlined />}
                    loading={downloading === f.file_token}
                    title="点击下载"
                    onClick={() => handleDownload(f.file_token)}
                  >
                    {f.name}
                  </Button>
                ) : (
                  <span key={f.name}>{f.name}</span>
                ),
              )}
            </Space>
          </div>
        ))}
      </div>
    </div>
  )
}
