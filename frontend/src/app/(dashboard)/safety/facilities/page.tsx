// 设备设施管理 —— 体系要素占位页（业务未开展，设备台账先行）

import ModulePlaceholder from '@/components/safety/ModulePlaceholder'

export default function FacilitiesPage() {
  return (
    <ModulePlaceholder
      name="设备设施管理"
      scope={`设备设施安全台账；检验/校验到期督办；安全设施（消防、监控、连锁报警）完好性管理；
设备安全操作规程库与说明书库。`}
      agentStatus={`本模块为体系当前最大空白。公司已有设备巡检（设备模块）与探测器数据（仪表模块），
但尚未接入安环 Agent 体系；消防点检 PDF 已实现归档（单点能力）。
启动路径：先在飞书多维表格建立设备台账完成直读对接，再逐步建设检验到期督办
与设备健康统计。`}
    />
  )
}
