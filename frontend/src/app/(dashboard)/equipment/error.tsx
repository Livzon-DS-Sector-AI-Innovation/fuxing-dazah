'use client'

import { useEffect } from 'react'
import { Alert, Button, Space } from 'antd'

export default function EquipmentErrorPage({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string }
  unstable_retry: () => void
}) {
  useEffect(() => {
    console.error('[设备模块] 页面渲染错误:', error)
  }, [error])

  return (
    <div style={{ padding: 24 }}>
      <Alert
        type="error"
        showIcon
        title="设备模块加载失败"
        description={
          <div>
            <p style={{ margin: '4px 0' }}>{error.message}</p>
            {error.digest && (
              <p style={{ margin: '4px 0', fontSize: 12, color: '#787671' }}>
                错误标识: <code>{error.digest}</code>（在服务端日志中搜索此标识查看完整堆栈）
              </p>
            )}
            <Space style={{ marginTop: 8 }}>
              <Button size="small" type="primary" onClick={() => unstable_retry()}>
                重试
              </Button>
              <Button size="small" onClick={() => window.location.reload()}>
                刷新页面
              </Button>
            </Space>
          </div>
        }
      />
    </div>
  )
}
