'use client'

import { useState } from 'react'
import { Alert, Button } from 'antd'
import { SwapOutlined } from '@ant-design/icons'
import { stopImpersonate } from '@/actions/auth'
import type { ImpersonateUserInfo } from '@/types/user'

interface Props {
  targetUser: ImpersonateUserInfo
}

export function ImpersonateBanner({ targetUser }: Props) {
  const [stopping, setStopping] = useState(false)

  const handleStop = async () => {
    setStopping(true)
    try {
      await stopImpersonate()
      window.location.reload()
    } catch {
      setStopping(false)
    }
  }

  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 1001 }}>
      <Alert
        type="warning"
        banner
        showIcon
        icon={<SwapOutlined />}
        title={
          <div className="flex items-center justify-center gap-2 text-[13px]">
            <span>
              正在以 <strong>{targetUser.name}</strong>
              （{targetUser.department || '—'} · {targetUser.position || '—'}）
              的身份浏览系统
            </span>
            <Button
              type="primary"
              size="small"
              danger
              loading={stopping}
              onClick={handleStop}
            >
              退出代理
            </Button>
          </div>
        }
      />
    </div>
  )
}
