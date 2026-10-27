'use client'

import { Divider, InputNumber, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import type { CalcCfg, CalcContentMultiCfg, CalcExternalStdCfg, CalcExternalStdContentCfg, CalcGroupRrfCfg, CalcImpurityRrfStdCfg, CalcImpurityStdRatioCfg, CalcImpurityVsStdCfg, CalcNormalizationCfg, CalcStdCurveCfg } from '@/types/quality'

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
  if (cfg.mode === 'external_std_content') {
    return <ContentForm cfg={cfg} inputs={inputs} set={set} />
  }
  if (cfg.mode === 'external_std_content_multi') {
    return <ContentMultiForm cfg={cfg} inputs={inputs} set={set} />
  }
  if (cfg.mode === 'impurity_vs_std') {
    return <ImpVsStdForm cfg={cfg} inputs={inputs} set={set} />
  }
  if (cfg.mode === 'impurity_std_ratio') {
    return <ImpStdRatioForm cfg={cfg} inputs={inputs} set={set} />
  }
  if (cfg.mode === 'std_curve') {
    return <StdCurveForm cfg={cfg} inputs={inputs} set={set} />
  }
  if (cfg.mode === 'group_rrf') {
    return <GroupRrfForm cfg={cfg} inputs={inputs} set={set} />
  }
  if (cfg.mode === 'impurity_rrf_std') {
    return <ImpRrfStdForm cfg={cfg} inputs={inputs} set={set} />
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


function ContentForm({ cfg, inputs, set }: {
  cfg: CalcExternalStdContentCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const stdAreas = Array.from({ length: 6 }, (_, i) => num(inputs[`std_area_${i + 1}`]))
  const stdPresent = stdAreas.filter((v): v is number => v != null)
  const stdAvg = stdPresent.length ? stdPresent.reduce((a, b) => a + b, 0) / stdPresent.length : null
  const stdRsd = stdPresent.length >= 2 && stdAvg
    ? (Math.sqrt(stdPresent.reduce((a, v) => a + (v - stdAvg) ** 2, 0) / (stdPresent.length - 1)) / stdAvg) * 100
    : null
  const moisture = num(inputs.moisture) ?? 0
  const stdMass = num(inputs.std1_mass)
  const stdContent = num(inputs.std_content)
  const content = (i: number) => {
    const sArea = num(inputs[`sample_area_${i}`])
    const sMass = num(inputs[`sample_mass_${i}`])
    if (sArea == null || sMass == null || stdMass == null || stdContent == null || stdAvg == null) return null
    return (stdMass * stdContent * sArea) / sMass / stdAvg / (1 - moisture / 100) * 100
  }
  const vals = Array.from({ length: cfg.samples }, (_, i) => content(i + 1))
  const present = vals.filter((v): v is number => v != null)
  const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        外标法含量：含量% = 标准1质量×标准品含量×样面积/样质量/标准1平均面积/(1-水分%)×100（照达托霉素含量表公式）。
      </Text>
      <Space wrap size={10}>
        <span style={{ fontSize: 12.5 }}>标准1质量(mg)
          <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs.std1_mass}
            onChange={(v) => set('std1_mass', v)} />
        </span>
        <span style={{ fontSize: 12.5 }}>标准品含量
          <InputNumber size="small" style={{ width: 90, marginLeft: 4 }} value={inputs.std_content}
            onChange={(v) => set('std_content', v)} />
        </span>
        {cfg.has_moisture && (
          <span style={{ fontSize: 12.5 }}>水分%
            <InputNumber size="small" style={{ width: 80, marginLeft: 4 }} value={inputs.moisture}
              onChange={(v) => set('moisture', v)} />
          </span>
        )}
      </Space>
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>标准1峰面积（5 针 + 回针可选）：</Text>
        <Space wrap size={4} style={{ marginTop: 4 }}>
          {stdAreas.map((_, i) => (
            <InputNumber key={i} size="small" style={{ width: 90 }} value={inputs[`std_area_${i + 1}`]}
              onChange={(v) => set(`std_area_${i + 1}`, v)} />
          ))}
          <Text style={{ fontSize: 12 }}>平均 <Text strong>{stdAvg != null ? stdAvg.toFixed(0) : '-'}</Text>　RSD{' '}
            <Text strong type={stdRsd != null && stdRsd > 2 ? 'danger' : undefined}>{stdRsd != null ? stdRsd.toFixed(2) + '%' : '-'}</Text>
          </Text>
        </Space>
      </div>
      <Space wrap size={10}>
        {Array.from({ length: cfg.samples }, (_, i) => (
          <span key={i} style={{ fontSize: 12.5 }}>
            样{i + 1}质量(mg)
            <InputNumber size="small" style={{ width: 90, marginLeft: 4 }} value={inputs[`sample_mass_${i + 1}`]}
              onChange={(v) => set(`sample_mass_${i + 1}`, v)} />
            　样{i + 1}面积
            <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[`sample_area_${i + 1}`]}
              onChange={(v) => set(`sample_area_${i + 1}`, v)} />
            　<Text>{vals[i] != null ? vals[i].toFixed(2) + '%' : '-'}</Text>
          </span>
        ))}
      </Space>
      <div style={{ fontSize: 13 }}>
        <Text type="secondary">平均含量：</Text>
        <Tag color={avg != null ? 'blue' : 'default'}>{avg != null ? avg.toFixed(2) + '%' : '-'}</Tag>
      </div>
    </Space>
  )
}


function ContentMultiForm({ cfg, inputs, set }: {
  cfg: CalcContentMultiCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const moisture = num(inputs.moisture) ?? 0
  const stdMass = num(inputs.std1_mass)
  const compContent = (key: string, i: number) => {
    const sArea = num(inputs[`sample_area_${key}_${i}`])
    const sMass = num(inputs[`sample_mass_${i}`])
    const stdContent = num(inputs[`std_content_${key}`])
    const stdAreas = Array.from({ length: 6 }, (_, j) => num(inputs[`std_area_${key}_${j + 1}`]))
    const stdPresent = stdAreas.filter((v): v is number => v != null)
    const stdAvg = stdPresent.length ? stdPresent.reduce((a, b) => a + b, 0) / stdPresent.length : null
    if (sArea == null || sMass == null || stdContent == null || stdAvg == null || stdMass == null) return null
    return (stdMass * stdContent * sArea) / sMass / stdAvg / (1 - moisture / 100) * 100
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        外标法含量（多组分）：组分% = 标准1质量×组分含量×样面积/样质量/标准1平均面积/(1-水分%)×100；总含量 = Σ组分%。
      </Text>
      <Space wrap size={10}>
        <span style={{ fontSize: 12.5 }}>标准1质量(mg)
          <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs.std1_mass}
            onChange={(v) => set('std1_mass', v)} />
        </span>
        <span style={{ fontSize: 12.5 }}>水分%
          <InputNumber size="small" style={{ width: 80, marginLeft: 4 }} value={inputs.moisture}
            onChange={(v) => set('moisture', v)} />
        </span>
      </Space>
      {cfg.components.map((comp) => {
        const stdAreas = Array.from({ length: 6 }, (_, j) => num(inputs[`std_area_${comp.key}_${j + 1}`]))
        const stdPresent = stdAreas.filter((v): v is number => v != null)
        const stdAvg = stdPresent.length ? stdPresent.reduce((a, b) => a + b, 0) / stdPresent.length : null
        const stdRsd = stdPresent.length >= 2 && stdAvg
          ? (Math.sqrt(stdPresent.reduce((a, v) => a + (v - stdAvg) ** 2, 0) / (stdPresent.length - 1)) / stdAvg) * 100
          : null
        const vals = Array.from({ length: cfg.samples }, (_, i) => compContent(comp.key, i + 1))
        const present = vals.filter((v): v is number => v != null)
        const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null
        return (
          <div key={comp.key} style={{ border: '1px solid #e5e5e5', borderRadius: 8, padding: 10 }}>
            <Text strong>{comp.label}</Text>
            <Space wrap size={10} style={{ marginTop: 6 }}>
              <span style={{ fontSize: 12.5 }}>组分含量
                <InputNumber size="small" style={{ width: 80, marginLeft: 4 }} value={inputs[`std_content_${comp.key}`]}
                  onChange={(v) => set(`std_content_${comp.key}`, v)} />
              </span>
            </Space>
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>标准1峰面积（5 针+回针）：</Text>
              <Space wrap size={4} style={{ marginTop: 4 }}>
                {stdAreas.map((_, j) => (
                  <InputNumber key={j} size="small" style={{ width: 85 }} value={inputs[`std_area_${comp.key}_${j + 1}`]}
                    onChange={(v) => set(`std_area_${comp.key}_${j + 1}`, v)} />
                ))}
                <Text style={{ fontSize: 12 }}>平均 <Text strong>{stdAvg != null ? stdAvg.toFixed(0) : '-'}</Text>　RSD{' '}
                  <Text strong type={stdRsd != null && stdRsd > 2 ? 'danger' : undefined}>{stdRsd != null ? stdRsd.toFixed(2) + '%' : '-'}</Text>
                </Text>
              </Space>
            </div>
            <Space wrap size={10} style={{ marginTop: 6 }}>
              {Array.from({ length: cfg.samples }, (_, i) => (
                <span key={i} style={{ fontSize: 12.5 }}>
                  样{i + 1}面积
                  <InputNumber size="small" style={{ width: 95, marginLeft: 4 }} value={inputs[`sample_area_${comp.key}_${i + 1}`]}
                    onChange={(v) => set(`sample_area_${comp.key}_${i + 1}`, v)} />
                  　<Text>{vals[i] != null ? vals[i].toFixed(2) + '%' : '-'}</Text>
                </span>
              ))}
            </Space>
            <div style={{ marginTop: 4, fontSize: 13 }}>
              <Text type="secondary">{comp.label} 平均：</Text>
              <Tag color={avg != null ? 'blue' : 'default'}>{avg != null ? avg.toFixed(2) + '%' : '-'}</Tag>
            </div>
          </div>
        )
      })}
      <div style={{ fontSize: 13 }}>
        <Text type="secondary">样品质量（各份共用）：</Text>
        <Space wrap size={6} style={{ marginTop: 4 }}>
          {Array.from({ length: cfg.samples }, (_, i) => (
            <span key={i} style={{ fontSize: 12.5 }}>
              样{i + 1}质量(mg)
              <InputNumber size="small" style={{ width: 90, marginLeft: 4 }} value={inputs[`sample_mass_${i + 1}`]}
                onChange={(v) => set(`sample_mass_${i + 1}`, v)} />
            </span>
          ))}
        </Space>
      </div>
    </Space>
  )
}

type ImpRow = { key: string; label: string; v1: number | null; v2: number | null }

function ImpVsStdForm({ cfg, inputs, set }: {
  cfg: CalcImpurityVsStdCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const stdC = cfg.components.reduce((a, c) => a + (num(inputs[`std_c_area_${c.key}`]) ?? 0), 0)
  const impPct = (key: string, i: number) => (stdC > 0 ? ((num(inputs[`imp_${key}_${i}`]) ?? 0) / stdC) * 100 : null)
  const impColumns: TableColumnsType<ImpRow> = [
    { title: '项目', dataIndex: 'label', width: 160 },
    {
      title: '第1份面积', key: 'a1', width: 130,
      render: (_: unknown, r) => (
        <InputNumber size="small" style={{ width: '100%' }} value={inputs[`imp_${r.key}_1`]}
          onChange={(v) => set(`imp_${r.key}_1`, v)} />
      ),
    },
    {
      title: '第2份面积', key: 'a2', width: 130,
      render: (_: unknown, r) => (
        <InputNumber size="small" style={{ width: '100%' }} value={inputs[`imp_${r.key}_2`]}
          onChange={(v) => set(`imp_${r.key}_2`, v)} />
      ),
    },
    {
      title: '第1份%', key: 'p1', width: 90,
      render: (_: unknown, r) => r.v1 != null ? r.v1.toFixed(4) + '%' : '-',
    },
    {
      title: '第2份%', key: 'p2', width: 90,
      render: (_: unknown, r) => r.v2 != null ? r.v2.toFixed(4) + '%' : '-',
    },
    {
      title: '平均%', key: 'avg', width: 100,
      render: (_: unknown, r) => {
        const both = [r.v1, r.v2].filter((v): v is number => v != null)
        const avg = both.length ? both.reduce((a, b) => a + b, 0) / both.length : null
        return avg != null ? <Text strong>{avg.toFixed(4)}%</Text> : '-'
      },
    },
  ]
  const totalPct = (i: number) => {
    const total = num(inputs[`sample_total_${i}`])
    if (total == null || stdC <= 0) return null
    const mains = cfg.components.reduce((a, c) => a + (num(inputs[`sample_main_${c.key}_${i}`]) ?? 0), 0)
    return (Math.max(total - mains, 0) / stdC) * 100
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        有关物质（对标准溶液c归一）：杂质% = 杂质面积/标准c总面积×100；总杂% = (供试品总峰面积-主组分面积)/标准c总面积×100。
      </Text>
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>标准溶液c 峰面积：</Text>
        <Space wrap size={6} style={{ marginTop: 4 }}>
          {cfg.components.map((c) => (
            <span key={c.key} style={{ fontSize: 12.5 }}>
              {c.label}
              <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[`std_c_area_${c.key}`]}
                onChange={(v) => set(`std_c_area_${c.key}`, v)} />
            </span>
          ))}
          <Text style={{ fontSize: 12 }}>合计 <Text strong>{stdC.toFixed(0)}</Text></Text>
        </Space>
      </div>
      <Table<ImpRow>
        rowKey="key" size="small" pagination={false}
        dataSource={cfg.impurities.map((imp) => ({
          key: imp.key, label: imp.label,
          v1: impPct(imp.key, 1), v2: impPct(imp.key, 2),
        }))}
        scroll={{ x: 560 }}
        columns={impColumns}
      />
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>供试品（每份）：总峰面积 与 主组分面积：</Text>
        <Space wrap size={8} style={{ marginTop: 4 }}>
          {Array.from({ length: cfg.samples }, (_, i) => (
            <span key={i} style={{ fontSize: 12.5 }}>
              第{i + 1}份 总峰
              <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[`sample_total_${i + 1}`]}
                onChange={(v) => set(`sample_total_${i + 1}`, v)} />
              {cfg.components.map((c) => (
                <span key={c.key}>　{c.label}
                  <InputNumber size="small" style={{ width: 95, marginLeft: 4 }} value={inputs[`sample_main_${c.key}_${i + 1}`]}
                    onChange={(v) => set(`sample_main_${c.key}_${i + 1}`, v)} />
                </span>
              ))}
              　总杂 <Text strong>{totalPct(i + 1) != null ? totalPct(i + 1)!.toFixed(4) + '%' : '-'}</Text>
            </span>
          ))}
        </Space>
      </div>
    </Space>
  )
}


function ImpStdRatioForm({ cfg, inputs, set }: {
  cfg: CalcImpurityStdRatioCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const stdMass = num(inputs.std1_mass)
  const stdAreas = Array.from({ length: 5 }, (_, i) => num(inputs[`std_area_${i + 1}`]))
  const stdPresent = stdAreas.filter((v): v is number => v != null)
  const rs1 = stdPresent.length ? stdPresent.reduce((a, b) => a + b, 0) / stdPresent.length : null
  const cs1 = stdMass != null ? stdMass / cfg.std_vol / cfg.std_dilution / 100 * 1000 : null
  const cu = (i: number) => {
    const m = num(inputs[`sample_mass_${i}`])
    return m != null ? m / cfg.sample_vol / cfg.sample_dilution * 1000 : null
  }
  const pct = (key: string, i: number) => {
    const a = num(inputs[`imp_${key}_${i}`]) ?? 0
    const cuI = cu(i)
    if (cs1 == null || rs1 == null || cuI == null) return null
    return cs1 * a * 100 / (cuI * rs1)
  }
  const rows = cfg.impurities.map((imp) => ({
    key: imp.key, label: imp.label,
    a1: inputs[`imp_${imp.key}_1`], a2: inputs[`imp_${imp.key}_2`],
    v1: pct(imp.key, 1), v2: pct(imp.key, 2),
  }))
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        对照浓度比值法：Cs1 = 储备液称样量/{cfg.std_vol}/{cfg.std_dilution}/100×1000 μg/ml；Cu = 样品称样量/{cfg.sample_vol}/{cfg.sample_dilution}×1000 μg/ml；杂质% = Cs1×杂质面积×100/(Cu×标准1平均面积)。
      </Text>
      <Space wrap size={10}>
        <span style={{ fontSize: 12.5 }}>储备液称样量(mg)
          <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs.std1_mass}
            onChange={(v) => set('std1_mass', v)} />
        </span>
        <span style={{ fontSize: 12.5 }}>样品1称样量(mg)
          <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs.sample_mass_1}
            onChange={(v) => set('sample_mass_1', v)} />
        </span>
        <span style={{ fontSize: 12.5 }}>样品2称样量(mg)
          <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs.sample_mass_2}
            onChange={(v) => set('sample_mass_2', v)} />
        </span>
      </Space>
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>标准1主峰面积（5 针）：</Text>
        <Space wrap size={4} style={{ marginTop: 4 }}>
          {stdAreas.map((_, i) => (
            <InputNumber key={i} size="small" style={{ width: 95 }} value={inputs[`std_area_${i + 1}`]}
              onChange={(v) => set(`std_area_${i + 1}`, v)} />
          ))}
          <Text style={{ fontSize: 12 }}>平均 <Text strong>{rs1 != null ? rs1.toFixed(0) : '-'}</Text>　Cs1{' '}
            <Text strong>{cs1 != null ? cs1.toFixed(4) : '-'}</Text>
          </Text>
        </Space>
      </div>
      <Table<ImpRatioRow>
        rowKey="key" size="small" pagination={false} dataSource={rows} scroll={{ x: 620 }}
        columns={[
          { title: '杂质', dataIndex: 'label', width: 150 },
          {
            title: '第一份面积', key: 'a1', width: 130,
            render: (_: unknown, r) => (
              <InputNumber size="small" style={{ width: '100%' }} value={r.a1}
                onChange={(v) => set(`imp_${r.key}_1`, v)} />
            ),
          },
          {
            title: '第二份面积', key: 'a2', width: 130,
            render: (_: unknown, r) => (
              <InputNumber size="small" style={{ width: '100%' }} value={r.a2}
                onChange={(v) => set(`imp_${r.key}_2`, v)} />
            ),
          },
          {
            title: '第一份%', key: 'p1', width: 100,
            render: (_: unknown, r) => r.v1 != null ? r.v1.toFixed(4) + '%' : '-',
          },
          {
            title: '第二份%', key: 'p2', width: 100,
            render: (_: unknown, r) => r.v2 != null ? r.v2.toFixed(4) + '%' : '-',
          },
          {
            title: '平均%', key: 'avg', width: 110,
            render: (_: unknown, r) => {
              const both = [r.v1, r.v2].filter((v): v is number => v != null)
              const avg = both.length ? both.reduce((a, b) => a + b, 0) / both.length : null
              return avg != null ? <Text strong>{avg.toFixed(4)}%</Text> : '-'
            },
          },
        ]}
      />
    </Space>
  )
}

type ImpRatioRow = { key: string; label: string; a1: number | undefined; a2: number | undefined; v1: number | null; v2: number | null }

function StdCurveForm({ cfg, inputs, set }: {
  cfg: CalcStdCurveCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const stdMass = num(inputs.std_mass)
  const stdAreas = cfg.dilutions.map((_, i) => num(inputs[`std_area_${i + 1}`]))
  const concs = cfg.dilutions.map((d) => (stdMass != null ? stdMass / cfg.volume / cfg.conc_factor / d * 1000 : null))
  const b = (() => {
    const xs = stdAreas.filter((v): v is number => v != null).map((v) => Math.log10(v))
    const ys = concs.filter((v): v is number => v != null).map((v) => Math.log10(v))
    if (xs.length < 2 || ys.length < 2) return null
    const xm = xs.reduce((a, c) => a + c, 0) / xs.length
    const ym = ys.reduce((a, c) => a + c, 0) / ys.length
    const denom = xs.reduce((a, c) => a + (c - xm) ** 2, 0)
    if (denom === 0) return null
    return xs.reduce((a, c, i) => a + (c - xm) * (ys[i] - ym), 0) / denom
  })()
  const aInt = (() => {
    if (b == null) return null
    const xs = stdAreas.filter((v): v is number => v != null).map((v) => Math.log10(v))
    const ys = concs.filter((v): v is number => v != null).map((v) => Math.log10(v))
    return ys.reduce((a, c) => a + c, 0) / ys.length - b * xs.reduce((a, c) => a + c, 0) / xs.length
  })()
  const result = (key: string) => {
    const area = num(inputs[`imp_${key}_1`])
    if (area == null || b == null || aInt == null) return null
    return 10 ** (b * Math.log10(area) + aInt)
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        标准曲线回归法：对照 3 点终浓度 = 称重/{cfg.volume}/(100/6)/稀释倍数×1000 μg/ml；log-log 回归（log浓度=b×log面积+a）；结果 = 10^(b×log面积+a) μg/ml。
      </Text>
      <Space wrap size={10}>
        <span style={{ fontSize: 12.5 }}>对照品称重(mg)
          <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs.std_mass}
            onChange={(v) => set('std_mass', v)} />
        </span>
        {cfg.dilutions.map((d, i) => (
          <span key={d} style={{ fontSize: 12.5 }}>
            {d}×面积
            <InputNumber size="small" style={{ width: 95, marginLeft: 4 }} value={inputs[`std_area_${i + 1}`]}
              onChange={(v) => set(`std_area_${i + 1}`, v)} />
          </span>
        ))}
      </Space>
      <div style={{ fontSize: 12.5 }}>
        <Text type="secondary">回归：斜率 b = </Text>
        <Text strong>{b != null ? b.toFixed(4) : '-'}</Text>
        <Text type="secondary">　截距 a = </Text>
        <Text strong>{aInt != null ? aInt.toFixed(4) : '-'}</Text>
      </div>
      <Table<{ key: string; label: string; v: number | null }>
        rowKey="key" size="small" pagination={false}
        dataSource={cfg.items.map((it) => ({ key: it.key, label: it.label, v: result(it.key) }))}
        scroll={{ x: 480 }}
        columns={[
          { title: '项目', dataIndex: 'label', width: 150 },
          {
            title: '峰面积', key: 'area', width: 140,
            render: (_: unknown, r) => (
              <InputNumber size="small" style={{ width: '100%' }} value={inputs[`imp_${r.key}_1`]}
                onChange={(v) => set(`imp_${r.key}_1`, v)} />
            ),
          },
          {
            title: '结果（μg/ml）', key: 'v', width: 130,
            render: (_: unknown, r) => r.v != null ? <Text strong>{r.v.toFixed(4)}</Text> : '-',
          },
        ]}
      />
      <Text type="warning" style={{ fontSize: 12 }}>
        注：Ch.P. 模板结果列无内置公式，系统按 10^(b×log面积+a) 计算；结果单位（μg/ml）与限度口径请与业务确认。
      </Text>
    </Space>
  )
}


function GroupRrfForm({ cfg, inputs, set }: {
  cfg: CalcGroupRrfCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const mainTotal = num(inputs.main_total) ?? 0
  const areas = Object.fromEntries(cfg.items.map((it) => [it.key, num(inputs[`area_${it.key}`]) ?? 0]))
  const rrfSum = cfg.rrf_denom.reduce((a, k) => a + (areas[k] ?? 0), 0)
  const denom = mainTotal + cfg.rrf * rrfSum
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        分组校正因子归一化：校正总面积 = 主组总峰面积 + {cfg.rrf}×校正组面积；校正组成员% = {cfg.rrf}×面积/校正总面积×100。
        {cfg.review && <Text type="warning">　⚠ {cfg.review}</Text>}
      </Text>
      <span style={{ fontSize: 12.5 }}>
        {cfg.main_std_name}（主组）总峰面积
        <InputNumber size="small" style={{ width: 130, marginLeft: 6 }} value={inputs.main_total}
          onChange={(v) => set('main_total', v)} />
      </span>
      <Table<{ key: string; label: string; isRrf: boolean }>
        rowKey="key" size="small" pagination={false}
        dataSource={cfg.items.map((it) => ({ key: it.key, label: it.label, isRrf: cfg.rrf_group.includes(it.key) }))}
        scroll={{ x: 520 }}
        columns={[
          { title: '组分', dataIndex: 'label', width: 150, render: (v: string, r) => (
            <span>{v}{r.isRrf && <Text type="warning" style={{ fontSize: 11 }}>（×{cfg.rrf}）</Text>}</span>
          ) },
          {
            title: '峰面积', key: 'area', width: 140,
            render: (_: unknown, r) => (
              <InputNumber size="small" style={{ width: '100%' }} value={inputs[`area_${r.key}`]}
                onChange={(v) => set(`area_${r.key}`, v)} />
            ),
          },
          {
            title: '结果%', key: 'v', width: 130,
            render: (_: unknown, r) => {
              const a = num(inputs[`area_${r.key}`]) ?? 0
              if (denom <= 0) return '-'
              const v = (r.isRrf ? cfg.rrf * a : a) / denom * 100
              return <Text strong>{v.toFixed(4)}%</Text>
            },
          },
        ]}
      />
      <div style={{ fontSize: 13 }}>
        <Text type="secondary">{cfg.main_std_name}%：</Text>
        <Tag color="blue">{denom > 0 ? (mainTotal / denom * 100).toFixed(4) + '%' : '-'}</Tag>
      </div>
    </Space>
  )
}

function ImpRrfStdForm({ cfg, inputs, set }: {
  cfg: CalcImpurityRrfStdCfg
  inputs: Inputs
  set: (k: string, v: number | null) => void
}) {
  const stdKeys = cfg.std_keys ?? ['std']
  const rrfInput = cfg.rrf_from_input ? (num(inputs[cfg.rrf_from_input]) ?? 1) : null
  const pct = (key: string, rrf: number | undefined, i: number) => {
    const stdK = stdKeys[Math.min(i - 1, stdKeys.length - 1)]
    const stdArea = num(inputs[`std_area_${stdK}_${i}`])
    const a = num(inputs[`imp_${key}_${i}`]) ?? 0
    if (stdArea == null) return null
    return a * (rrf ?? rrfInput ?? 1) / stdArea
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Text type="secondary" style={{ fontSize: 12.5 }}>
        校正因子对标准面积：杂质% = 杂质面积×校正因子/标准面积。
        {cfg.review && <Text type="warning">　⚠ {cfg.review}</Text>}
      </Text>
      <Space wrap size={6}>
        {Array.from({ length: cfg.samples }, (_, i) => (
          <span key={i} style={{ fontSize: 12.5 }}>
            标准面积{stdKeys.length > 1 ? `（${stdKeys[i]}）` : ''}·第{i + 1}份
            <InputNumber size="small" style={{ width: 110, marginLeft: 4 }} value={inputs[`std_area_${stdKeys[Math.min(i, stdKeys.length - 1)]}_${i + 1}`]}
              onChange={(v) => set(`std_area_${stdKeys[Math.min(i, stdKeys.length - 1)]}_${i + 1}`, v)} />
          </span>
        ))}
        {cfg.rrf_from_input && (
          <span style={{ fontSize: 12.5 }}>
            {cfg.rrf_from_input}
            <InputNumber size="small" style={{ width: 100, marginLeft: 4 }} value={inputs[cfg.rrf_from_input]}
              onChange={(v) => set(cfg.rrf_from_input!, v)} />
          </span>
        )}
      </Space>
      <Table<{ key: string; label: string; rrf?: number }>
        rowKey="key" size="small" pagination={false}
        dataSource={cfg.items.map((it) => ({ key: it.key, label: it.label, rrf: it.rrf }))}
        scroll={{ x: 620 }}
        columns={[
          { title: '项目', dataIndex: 'label', width: 160 },
          {
            title: '第1份面积', key: 'a1', width: 130,
            render: (_: unknown, r) => (
              <InputNumber size="small" style={{ width: '100%' }} value={inputs[`imp_${r.key}_1`]}
                onChange={(v) => set(`imp_${r.key}_1`, v)} />
            ),
          },
          {
            title: '第2份面积', key: 'a2', width: 130,
            render: (_: unknown, r) => (
              <InputNumber size="small" style={{ width: '100%' }} value={inputs[`imp_${r.key}_2`]}
                onChange={(v) => set(`imp_${r.key}_2`, v)} />
            ),
          },
          {
            title: '第1份%', key: 'p1', width: 100,
            render: (_: unknown, r) => {
              const v = pct(r.key, r.rrf, 1)
              return v != null ? v.toFixed(4) + '%' : '-'
            },
          },
          {
            title: '第2份%', key: 'p2', width: 100,
            render: (_: unknown, r) => {
              const v = pct(r.key, r.rrf, 2)
              return v != null ? v.toFixed(4) + '%' : '-'
            },
          },
          {
            title: '平均%', key: 'avg', width: 110,
            render: (_: unknown, r) => {
              const both = [pct(r.key, r.rrf, 1), pct(r.key, r.rrf, 2)].filter((v): v is number => v != null)
              const avg = both.length ? both.reduce((a, b) => a + b, 0) / both.length : null
              return avg != null ? <Text strong>{avg.toFixed(4)}%</Text> : '-'
            },
          },
        ]}
      />
    </Space>
  )
}
