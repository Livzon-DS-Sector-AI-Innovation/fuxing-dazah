'use client'

// 候选人详情页的客户端外壳：负责按路由 id 拉取候选人，并把「重新拉取」入口下发给详情组件。
// 页面文件（[id]/page.tsx）保持为服务端组件，用于生成带姓名的标签页标题。

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Alert, Button, Empty, Spin } from 'antd'
import CandidateDetailClient from '@/components/hr/CandidateDetailClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import { fetchCandidateById } from '@/actions/hr'
import type { Candidate } from '@/types/hr'

/** 最近一次加载的结果；id 记录这份结果对应哪个候选人（上下条切换时据此判断手里的数据是否属于当前这个人） */
interface LoadState {
  id: string | null
  status: 'idle' | 'done' | 'error'
  candidate: Candidate | null
  message?: string
}

export default function CandidateDetailLoader() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [state, setState] = useState<LoadState>({ id: null, status: 'idle', candidate: null })
  // 同一个人写操作后的重新加载：只在事件回调里切换，不在 effect 里同步 setState
  const [reloading, setReloading] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchCandidateById(id)
      .then(d => {
        if (!cancelled) setState({ id, status: 'done', candidate: (d.data ?? null) as Candidate | null })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState({ id, status: 'error', candidate: null, message: err instanceof Error ? err.message : '候选人不存在或已被删除' })
      })
    return () => { cancelled = true }
  }, [id])

  // 写操作后的重新拉取入口：候选人存在本组件 state 里，router.refresh() 只重渲染服务端组件、
  // 不会重跑上面的 effect——详情页各处刷新必须走这里，否则流转/入职/保存后页面仍是旧数据
  const reloadCandidate = useCallback(async (): Promise<Candidate | null> => {
    setReloading(true)
    try {
      const d = await fetchCandidateById(id)
      const fresh = (d.data ?? null) as Candidate | null
      setState({ id, status: 'done', candidate: fresh })
      return fresh
    } catch (err: unknown) {
      setState({ id, status: 'error', candidate: null, message: err instanceof Error ? err.message : '加载失败' })
      return null
    } finally {
      setReloading(false)
    }
  }, [id])

  // 手里的候选人不是当前路由 id 的：不能把上一个人的资料留在屏幕上
  const current = state.id === id && state.candidate && state.candidate.id === id ? state.candidate : null

  if (!current) {
    if (state.id === id && state.status === 'error') {
      return (
        <div className="py-16">
          <Empty description={state.message}>
            <Button type="primary" onClick={() => router.push('/hr/recruitment')}>返回列表</Button>
          </Empty>
        </div>
      )
    }
    return <div className="flex justify-center py-24"><Spin size="large" /></div>
  }

  // 同一个人重新加载：保留原内容、上面盖加载圈，避免整块内容闪成空白
  return (
    <Spin spinning={reloading}>
      <PermissionGuard
        permission="hr:recruitment:read"
        fallback={<Alert type="warning" showIcon title="您没有招聘管理的查看权限，请联系管理员赋权。" />}
      >
        <CandidateDetailClient candidate={current} onReload={reloadCandidate} />
      </PermissionGuard>
    </Spin>
  )
}
