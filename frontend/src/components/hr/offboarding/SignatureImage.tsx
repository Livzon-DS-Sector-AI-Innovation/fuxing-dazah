'use client'

// 员工手写签名图：签字确认后随档案调取。没有敏感信息权限时只显示「已签字」与时间，不给图。

import { useEffect, useState } from 'react'
import { Image, Spin, Tag } from 'antd'
import { fetchOffboardingSignatureImage } from '@/actions/hr'
import type { OffboardingSignatureImage } from '@/types/hr'
import { fmtTime } from './CasePanel'

export default function SignatureImage({ caseId }: { caseId: string }) {
  const [data, setData] = useState<OffboardingSignatureImage | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchOffboardingSignatureImage(caseId)
      .then((res) => { if (!cancelled) setData(res) })
      .catch(() => { if (!cancelled) setData({ masked: true, image: null }) })
    return () => { cancelled = true }
  }, [caseId])

  return (
    <div className="rounded-[var(--rounded-md)] border border-[var(--color-hairline)] bg-white px-3 py-2">
      <div className="mb-1 flex items-center gap-2 text-[13px] font-medium text-[var(--color-ink)]">
        员工签名
        {data?.signed_at && <Tag color="success">已签字 {fmtTime(data.signed_at)}</Tag>}
        {data?.signed_name && <span className="text-[12px] font-normal text-[var(--color-slate)]">签署人 {data.signed_name}</span>}
      </div>
      {!data ? (
        <Spin size="small" />
      ) : data.masked || !data.image ? (
        <span className="text-[12px] text-[var(--color-steel)]">
          {data.masked ? '签名图需要「查看敏感信息」权限' : '纸质当面签收，没有签名图'}
        </span>
      ) : (
        <Image src={data.image} alt="员工手写签名" height={110} style={{ objectFit: 'contain' }} />
      )}
    </div>
  )
}
