'use client'

import { Divider, InputNumber, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import type { CalcCfg, CalcExternalStdCfg, CalcNormalizationCfg } from '@/types/quality'

const { Text } = Typography

type Inputs = Record<string, number | undefined>

function num(v: number | undefined): number | null {
  return v != null && v > 0 ? v : null
}

/** 在线计算表动态表单：按表号 calc 配置渲染输入区 + 实时计算预览。
 *  前端预览仅展示（判定以服务端引擎为准）；inputs 键约定与后端 calc_engine 一致。 */
export default function CalcForm({ cfg, inputs, onChange }: {
  cfg: CalcCfg
  inputs: Inputs
  onChange: (inputs: Inputs) => void
}) {
  const set = (key: string, v: number | null) =>
    onChange({ ...inputs, [key]: v == null ? undefined : v })

  if (cfg.mode === 'normalization') {
    return <NormForm cfg={cfg} inputs={inputs} set={set} />
  }
  return <ExtForm cfg={cfg} inputs={inputs} set={set} />
}

function NormForm({ cfg, inputs, set }: {
  cfg: CalcNormalizationCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const rrf = cfg.rrf || 1
  const rows = [
    { key: 'total_peak', label: '总峰面积' },
    { key: 'main_peak', label: '主峰面积（Ab）' },
    ...cfg.impurities.map((i) => ({ key: i.key, label: i.label, std_name: i.std_name })),
  ]
  const denom = (i: number) => {
    const tp = num(inputs[`total_peak_${i}`])
    const mp = num(inputs[`main_peak_${i}`])
    if (tp == null || mp == null) return null
    const at = tp - mp > 0 ? tp - mp : 0
    return rrf * mp + at
  }
  const pct = (key: string, i: number, isMain: boolean) => {
    const d = denom(i)
    const v = num(inputs[`${key}_${i}`])
    if (d == null || d === 0 || v == null) return null
    return ((isMain ? rrf * v : v) / d) * 100
  }
  type NormRow = { key: string; label: string; std_name?: string; p1: number | null; p2: number | null; avg: number | null }
  const dataSource: NormRow[] = rows.map((r) => {
    const p1 = pct(r.key, 1, r.key === 'main_peak')
    const p2 = pct(r.key, 2, r.key === 'main_peak')
    const both = [p1, p2].filter((v): v is number => v != null)
    const avg = both.length ? both.reduce((a, b) => a + b, 0) / both.length : null
    return { ...r, p1, p2, avg }
  })
  const normColumns: TableColumnsType<NormRow> = [
    { title: '项目', dataIndex: 'label', width: 200, render: (v: string, r) => (
      r.key === 'main_peak' ? <Text strong>{v}</Text> : v
    ) },
    {
      title: '第一份面积', key: 'a1', width: 140,
      render: (_: unknown, r) => (
        <InputNumber size="small" style={{ width: '100%' }} value={inputs[`${r.key}_1`]}
          onChange={(v) => set(`${r.key}_1`, v)} />
      ),
    },
    {
      title: '第二份面积', key: 'a2', width: 140,
      render: (_: unknown, r) => (
        <InputNumber size="small" style={{ width: '100%' }} value={inputs[`${r.key}_2`]}
          onChange={(v) => set(`${r.key}_2`, v)} />
      ),
    },
    {
      title: '第一份%', key: 'p1', width: 100,
      render: (_: unknown, r) =>
        r.p1 != null ? r.p1.toFixed(4) + '%' : '-',
    },
    {
      title: '第二份%', key: 'p2', width: 100,
      render: (_: unknown, r) =>
        r.p2 != null ? r.p2.toFixed(4) + '%' : '-',
    },
    {
      title: '平均%', key: 'avg', width: 110,
      render: (_: unknown, r) =>
        r.avg != null
          ? <Text strong>{r.avg.toFixed(4)}%</Text>
          : '-',
    },
  ]
  const totalImpAvg = dataSource
    .filter((r) => r.key !== 'total_peak' && r.key !== 'main_peak')
    .reduce((a, r) => a + (r.avg ?? 0), 0)

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={6}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        面积归一化法（校正因子 {rrf}）：含量% = {rrf}×主峰/({rrf}×主峰+杂质总面积)×100；杂质面积留空/0 视为未检出。
      </Text>
      <Table<NormRow>
        rowKey="key" size="small" pagination={false} dataSource={dataSource}
        scroll={{ x: 720 }}
        columns={normColumns}
      />
      <div style={{ fontSize: 13 }}>
        <Text type="secondary">总杂质% = 各杂质%之和：</Text>
        <Text strong>{totalImpAvg.toFixed(4)}%</Text>
      </div>
    </Space>
  )
}

function ExtForm({ cfg, inputs, set }: {
  cfg: CalcExternalStdCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const factor = cfg.dilution_factor || 1
  const scale = cfg.ppm_scale || 1e6
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        外标法：ppm = 样面积×对照质量×含量P×{factor}/(对照平均面积×样品质量×对照稀释体积)×10⁶；对照进样 {cfg.std_injections} 针自动算平均与 RSD。
      </Text>
      {cfg.solvents.map((sol) => {
        const stdAreas = Array.from({ length: cfg.std_injections }, (_, i) => num(inputs[`${sol.key}_std_area_${i + 1}`]))
        const stdPresent = stdAreas.filter((v): v is number => v != null)
        const stdAvg = stdPresent.length ? stdPresent.reduce((a, b) => a + b, 0) / stdPresent.length : null
        const stdRsd = stdPresent.length >= 2 && stdAvg
          ? (Math.sqrt(stdPresent.reduce((a, v) => a + (v - stdAvg) ** 2, 0) / (stdPresent.length - 1)) / stdAvg) * 100
          : null
        const ppm = (i: number) => {
          const sArea = num(inputs[`${sol.key}_sample_area_${i}`])
          const sMass = num(inputs[`${sol.key}_sample_mass_${i}`])
          const stdMass = num(inputs[`${sol.key}_std_mass`])
          const stdVol = num(inputs[`${sol.key}_std_vol`])
          const purity = num(inputs[`${sol.key}_std_purity`]) ?? 1
          if (sArea == null || sMass == null || stdMass == null || stdAvg == null || stdVol == null) return null
          return (sArea * stdMass * purity * factor) / (stdAvg * sMass * stdVol) * scale
        }
        const p1 = ppm(1)
        const p2 = ppm(2)
        const both = [p1, p2].filter((v): v is number => v != null)
        const avgPpm = both.length ? both.reduce((a, b) => a + b, 0) / both.length : null
        return (
          <div key={sol.key} style={{ border: '1px solid #e5e5e5', borderRadius: 8, padding: 10 }}>
            <Text strong>{sol.label}</Text>
            {sol.limit && <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>标准：{sol.limit}</Text>}
            <Divider style={{ margin: '8px 0' }} />
            <Space wrap size={10}>
              <span style={{ fontSize: 12.5 }}>对照质量(mg)
                <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[`${sol.key}_std_mass`]}
                  onChange={(v) => set(`${sol.key}_std_mass`, v)} />
              </span>
              <span style={{ fontSize: 12.5 }}>稀释体积
                <InputNumber size="small" style={{ width: 80, marginLeft: 4 }} value={inputs[`${sol.key}_std_vol`]}
                  onChange={(v) => set(`${sol.key}_std_vol`, v)} />
              </span>
              <span style={{ fontSize: 12.5 }}>含量P
                <InputNumber size="small" style={{ width: 80, marginLeft: 4 }} value={inputs[`${sol.key}_std_purity`]}
                  onChange={(v) => set(`${sol.key}_std_purity`, v)} />
              </span>
            </Space>
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>对照峰面积（{cfg.std_injections} 针）：</Text>
              <Space wrap size={4} style={{ marginTop: 4 }}>
                {stdAreas.map((_, i) => (
                  <InputNumber key={i} size="small" style={{ width: 90 }} value={inputs[`${sol.key}_std_area_${i + 1}`]}
                    onChange={(v) => set(`${sol.key}_std_area_${i + 1}`, v)} />
                ))}
                <Text style={{ fontSize: 12 }}>平均 <Text strong>{stdAvg != null ? stdAvg.toFixed(0) : '-'}</Text>　RSD{' '}
                  <Text strong type={stdRsd != null && stdRsd > 10 ? 'danger' : undefined}>{stdRsd != null ? stdRsd.toFixed(2) + '%' : '-'}</Text>
                </Text>
              </Space>
            </div>
            <Space wrap size={10} style={{ marginTop: 6 }}>
              <span style={{ fontSize: 12.5 }}>样品质量1(mg)
                <InputNumber size="small" style={{ width: 90, marginLeft: 4 }} value={inputs[`${sol.key}_sample_mass_1`]}
                  onChange={(v) => set(`${sol.key}_sample_mass_1`, v)} />
              </span>
              <span style={{ fontSize: 12.5 }}>样面积1
                <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[`${sol.key}_sample_area_1`]}
                  onChange={(v) => set(`${sol.key}_sample_area_1`, v)} />
              </span>
              <span style={{ fontSize: 12.5 }}>样品质量2(mg)
                <InputNumber size="small" style={{ width: 90, marginLeft: 4 }} value={inputs[`${sol.key}_sample_mass_2`]}
                  onChange={(v) => set(`${sol.key}_sample_mass_2`, v)} />
              </span>
              <span style={{ fontSize: 12.5 }}>样面积2
                <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[`${sol.key}_sample_area_2`]}
                  onChange={(v) => set(`${sol.key}_sample_area_2`, v)} />
              </span>
            </Space>
            <div style={{ marginTop: 6, fontSize: 13 }}>
              第1份 <Text strong>{p1 != null ? `${p1.toFixed(0)} ppm` : '-'}</Text>　第2份{' '}
              <Text strong>{p2 != null ? `${p2.toFixed(0)} ppm` : '-'}</Text>　平均{' '}
              <Tag color={avgPpm != null ? 'blue' : 'default'}>{avgPpm != null ? `${avgPpm.toFixed(0)} ppm` : '-'}</Tag>
            </div>
          </div>
        )
      })}
    </Space>
  )
}
