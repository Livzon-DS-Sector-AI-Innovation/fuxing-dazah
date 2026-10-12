import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ModulePlaceholder from './ModulePlaceholder'

describe('ModulePlaceholder', () => {
  it('渲染模块名、管什么、Agent 怎么管与飞书引导', () => {
    render(
      <ModulePlaceholder
        name="教育培训与行为管控"
        scope="培训计划与台账、违章行为档案与纠正"
        agentStatus="违章识别能力在隐患图片 AI 中已有"
      />,
    )
    expect(screen.getByText('教育培训与行为管控')).toBeInTheDocument()
    expect(screen.getByText('管什么')).toBeInTheDocument()
    expect(screen.getByText('Agent 怎么管')).toBeInTheDocument()
    expect(screen.getByText('培训计划与台账、违章行为档案与纠正')).toBeInTheDocument()
    expect(screen.getByText('违章识别能力在隐患图片 AI 中已有')).toBeInTheDocument()
    expect(screen.getByText(/请前往飞书多维表格操作/)).toBeInTheDocument()
    expect(screen.getByText('业务未开展')).toBeInTheDocument()
  })
})
