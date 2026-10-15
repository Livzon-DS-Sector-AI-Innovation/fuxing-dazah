'use client'

import { useEffect, useRef, useState } from 'react'
import { Input, Space, Button, App, Segmented, Tag, Typography, Card, Statistic, Select, theme } from 'antd'
import { ScanOutlined, ClearOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import { moveMaterialContainer, fetchStocktakes, scanStocktake, finishStocktake } from '@/actions/quality'
import { broadcastSignal } from './useCrossTabSignal'
import type { InputRef } from 'antd'
import type { StocktakeSheet } from '@/types/quality'

type ScanResult = { no: string; ok: boolean; detail: string; at: string }

export default function ScanStation() {
  const { message } = App.useApp()
  const { token } = theme.useToken()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [scanMode, setScanMode] = useState<'auto' | 'in' | 'out' | 'stocktake'>('auto')
  const [scanValue, setScanValue] = useState('')
  const [scanBusy, setScanBusy] = useState(false)
  const [results, setResults] = useState<ScanResult[]>([])
  const [okCount, setOkCount] = useState(0)
  const [failCount, setFailCount] = useState(0)
  const scanInputRef = useRef<InputRef>(null)
  const [stSheets, setStSheets] = useState<StocktakeSheet[]>([])
  const [stActive, setStActive] = useState<string | undefined>()
  const [stStats, setStStats] = useState<{ scanned: number; extra: number }>({ scanned: 0, extra: 0 })

  const loadStocktakes = async () => {
    try {
      const res = await fetchStocktakes('in_progress')
      setStSheets(res.data)
    } catch {
      // 静默
    }
  }

  useEffect(() => { if (scanMode === 'stocktake') { (async () => { await loadStocktakes() })() } }, [scanMode])

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
    if (scanMode === 'stocktake') {
      if (!stActive) {
        message.warning('请先选择进行中的盘点单')
        setScanBusy(false)
        setScanValue('')
        scanInputRef.current?.focus()
        return
      }
      try {
        const res = await scanStocktake(stActive, no)
        setStStats((p) => ({ scanned: p.scanned + 1, extra: p.extra + (res.data.result !== 'matched' ? 1 : 0) }))
        setResults((prev) => [{ no, ok: true, detail: res.message, at: dayjs().format('HH:mm:ss') }, ...prev].slice(0, 50))
        message.success(`${no} ${res.message}`)
      } catch (err: unknown) {
        const detail = (err instanceof Error ? err.message : String(err)) || '盘点扫码失败'
        setFailCount((n) => n + 1)
        setResults((prev) => [{ no, ok: false, detail, at: dayjs().format('HH:mm:ss') }, ...prev].slice(0, 50))
        message.error(`${no}：${detail}`)
      } finally {
        setScanBusy(false)
        setScanValue('')
        scanInputRef.current?.focus()
      }
      return
    }
    try {
      const res = await moveMaterialContainer(no, scanMode)
      setOkCount((n) => n + 1)
      setResults((prev) => [{
        no,
        ok: true,
        detail: `已${res.message}`,
        at: dayjs().format('HH:mm:ss'),
      }, ...prev].slice(0, 50))
      message.success(`${no} ${res.message}`)
    } catch (err: unknown) {
      const detail = (err instanceof Error ? err.message : String(err)) || '操作失败'
      setFailCount((n) => n + 1)
      setResults((prev) => [{ no, ok: false, detail, at: dayjs().format('HH:mm:ss') }, ...prev].slice(0, 50))
      message.error(`${no}：${detail}`)
    } finally {
      setScanBusy(false)
      setScanValue('')
      // 连续扫码：保持焦点
      scanInputRef.current?.focus()
    }
  }

  const onFinishStocktake = async () => {
    if (!stActive) return
    try {
      const res = await finishStocktake(stActive)
      message.success(res.message)
      broadcastSignal('material-changed')
      setStStats({ scanned: 0, extra: 0 })
      loadStocktakes()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '结束盘点失败')
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
                { label: '自动判定', value: 'auto' },
                { label: '入库登记', value: 'in' },
                { label: '领料出库', value: 'out' },
                { label: '盘点', value: 'stocktake' },
              ]}
            />
            {scanMode === 'stocktake' && (
              <Space wrap>
                <Select
                  placeholder="选择进行中的盘点单"
                  style={{ width: 240 }}
                  value={stActive}
                  onChange={(v) => { setStActive(v); setStStats({ scanned: 0, extra: 0 }); setResults([]) }}
                  options={stSheets.map((sh) => ({ value: sh.id, label: `${sh.sheet_no}（在库 ${sh.expected_count}）` }))}
                />
                <Button danger onClick={onFinishStocktake} disabled={!stActive}>结束盘点</Button>
                <Typography.Text type="secondary">已扫 {stStats.scanned}（其中异常 {stStats.extra}）</Typography.Text>
              </Space>
            )}
            <Typography.Text type="secondary">
              {scanMode === 'auto'
                ? '自动：已赋码入库；在库/合格出库；已领出/已作废报错'
                : scanMode === 'in'
                  ? '强制入库登记（已赋码 在库待验）'
                  : '强制领料出库（在库/合格 已领出，过期拦截）'}
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
          <Statistic title="成功" value={okCount} valueStyle={{ color: token.colorSuccess }} />
          <Statistic title="失败" value={failCount} valueStyle={{ color: token.colorError }} />
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
