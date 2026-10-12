'use client'

import { useRef, useState } from 'react'
import { Input, Space, Button, App, Segmented, Tag, Typography, Card, Statistic } from 'antd'
import { ScanOutlined, ClearOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import { moveMaterialContainer } from '@/actions/quality'
import type { InputRef } from 'antd'

type ScanResult = { no: string; ok: boolean; detail: string; at: string }

export default function ScanStation() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [scanMode, setScanMode] = useState<'auto' | 'in' | 'out'>('auto')
  const [scanValue, setScanValue] = useState('')
  const [scanBusy, setScanBusy] = useState(false)
  const [results, setResults] = useState<ScanResult[]>([])
  const [okCount, setOkCount] = useState(0)
  const [failCount, setFailCount] = useState(0)
  const scanInputRef = useRef<InputRef>(null)

  const handleScan = async (raw: string) => {
    // 兼容富文本二维码：从扫描内容中提取容器号（首行 MC-xxx）
    // 兼容富文本二维码：从扫描内容中提取容器号（首行 MC-xxx）；
    // 物料代码可为中文（如 万古），用「非空白/分隔符」匹配而非仅 ASCII
    const matched = raw.match(/MC-[^\s,，;；]+/)
    const no = matched ? matched[0] : raw.trim()
    if (!no) return
    if (!matched && !/^MC-[^\s,，;；]+$/.test(no)) {
      message.warning('未识别到容器号（MC-物料代码-日期-流水）')
      setScanValue('')
      return
    }
    setScanBusy(true)
    try {
      const res = await moveMaterialContainer(no, scanMode)
      setOkCount((n) => n + 1)
      setResults((prev) => [{
        no,
        ok: true,
        detail: `已${res.message}`,
        at: dayjs().format('HH:mm:ss'),
      }, ...prev].slice(0, 50))
      message.success(`✅ ${no} ${res.message}`)
    } catch (err: unknown) {
      const detail = (err instanceof Error ? err.message : String(err)) || '操作失败'
      setFailCount((n) => n + 1)
      setResults((prev) => [{ no, ok: false, detail, at: dayjs().format('HH:mm:ss') }, ...prev].slice(0, 50))
      message.error(`❌ ${no}：${detail}`)
    } finally {
      setScanBusy(false)
      setScanValue('')
      // 连续扫码：保持焦点
      scanInputRef.current?.focus()
    }
  }

  if (!canManage) {
    return <Typography.Text type="secondary">无操作权限（需 quality:material:manage）</Typography.Text>
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Space wrap>
            <Segmented
              value={scanMode}
              onChange={(v) => { setScanMode(v as 'auto' | 'in' | 'out'); setResults([]) }}
              options={[
                { label: '🔁 自动判定', value: 'auto' },
                { label: '📥 入库登记', value: 'in' },
                { label: '📤 领料出库', value: 'out' },
              ]}
            />
            <Typography.Text type="secondary">
              {scanMode === 'auto'
                ? '自动：已赋码→入库；在库/合格→出库；已领出/已作废→报错'
                : scanMode === 'in'
                  ? '强制入库登记（已赋码 → 在库待验）'
                  : '强制领料出库（在库/合格 → 已领出，过期拦截）'}
            </Typography.Text>
          </Space>
          <Input
            ref={scanInputRef}
            autoFocus
            size="large"
            placeholder="扫码枪扫描容器二维码，或手工输入容器号回车"
            prefix={<ScanOutlined />}
            value={scanValue}
            disabled={scanBusy}
            onChange={(e) => setScanValue(e.target.value)}
            onPressEnter={() => handleScan(scanValue)}
            allowClear
          />
        </Space>
      </Card>

      <Card size="small" title="本次会话统计" style={{ marginBottom: 16 }}>
        <Space size={40}>
          <Statistic title="成功" value={okCount} valueStyle={{ color: '#52c41a' }} />
          <Statistic title="失败" value={failCount} valueStyle={{ color: '#ff4d4f' }} />
          <Statistic title="累计处理" value={okCount + failCount} />
        </Space>
      </Card>

      <Card
        size="small"
        title={`扫码流水（最近 ${results.length} 条）`}
        extra={results.length > 0 ? (
          <Button size="small" icon={<ClearOutlined />} onClick={() => { setResults([]); setOkCount(0); setFailCount(0) }}>
            清空
          </Button>
        ) : null}
      >
        {results.length === 0 ? (
          <Typography.Text type="secondary">暂无扫码记录——扫第一瓶试试</Typography.Text>
        ) : (
          <div style={{ maxHeight: 420, overflowY: 'auto' }}>
            {results.map((r, i) => (
              <div key={`${r.no}-${r.at}-${i}`} style={{ paddingBlock: 3 }}>
                <Tag color={r.ok ? 'green' : 'red'}>{r.ok ? '成功' : '失败'}</Tag>
                <Typography.Text code>{r.no}</Typography.Text>
                <Typography.Text type="secondary"> {r.detail}（{r.at}）</Typography.Text>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
