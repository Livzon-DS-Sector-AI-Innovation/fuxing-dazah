'use client'

// 签署链接弹窗：把一次性签署链接交到 HR 手上。
// 短信通道尚未接入，链接没法自动发到员工手机——HR 复制后用微信 / 短信等转给员工。
// 链接只存在于接口响应里（库里只存哈希），所以每次打开弹窗都是「重新签发」：
// 旧链接随之作废，弹窗里把这一点讲清楚，避免 HR 把多条链接混着发。

import { Alert, App as AntdApp, Button, Input, Modal, Space, Typography } from 'antd'
import { LinkOutlined, ReloadOutlined } from '@ant-design/icons'

const { Text } = Typography

export default function SignLinkModal({
  open,
  url,
  employeeName,
  loading,
  onClose,
  onRegenerate,
}: {
  open: boolean
  url: string | null
  employeeName: string
  loading?: boolean
  onClose: () => void
  /** 重新签发：返回新链接，旧链接作废 */
  onRegenerate: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()

  const copy = async () => {
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      message.success('链接已复制')
    } catch {
      message.warning('复制失败，请手动选中链接复制')
    }
  }

  return (
    <Modal
      open={open}
      title="员工签署链接"
      okText="复制链接"
      cancelText="关闭"
      onOk={() => void copy()}
      onCancel={onClose}
      width={560}
      destroyOnHidden
    >
      <div className="space-y-3 pt-2">
        <Alert
          type="info"
          showIcon
          title="短信通道尚未接入，请复制链接转发给员工"
          description={`${employeeName}打开链接即可查看证明并手写签名；链接一次性使用，签字确认后自动失效。`}
        />
        {url ? (
          <div className="space-y-2">
            <Text className="text-[13px] text-[var(--color-slate)]">当前有效链接</Text>
            <Input readOnly value={url} onFocus={(e) => e.target.select()} />
            <Space wrap className="mt-1">
              <Button icon={<LinkOutlined />} onClick={() => window.open(url, '_blank')}>
                先自己打开核对
              </Button>
              <Button
                icon={<ReloadOutlined />}
                loading={loading}
                onClick={() => void onRegenerate()}
              >
                重新生成（旧链接作废）
              </Button>
            </Space>
          </div>
        ) : (
          <div className="rounded-[var(--rounded-md)] bg-[var(--color-surface)] px-3 py-4 text-center text-[13px] text-[var(--color-slate)]">
            还没有生成过链接
            <div className="mt-2">
              <Button type="primary" loading={loading} onClick={() => void onRegenerate()}>
                生成签署链接
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
