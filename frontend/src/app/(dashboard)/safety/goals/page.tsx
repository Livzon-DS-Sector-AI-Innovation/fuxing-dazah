// 目标责任与绩效 —— 体系要素占位页（业务未开展）

import ModulePlaceholder from '@/components/safety/ModulePlaceholder'

export default function SafetyGoalsPage() {
  return (
    <ModulePlaceholder
      name="目标责任与绩效"
      scope={`安全生产目标的制定、分解与达成跟踪；各级人员安全责任制清单；
安全投入与保险台账；管理者履职评价与绩效评定。`}
      agentStatus={`尚未建设专项能力。系统已有的 AI 调用审计、定时任务运行留痕与各业务域日报，
是未来履职数据面的天然底座——模块启动后按"留痕数据的管理化呈现"建设：
飞书多维表格建立目标指标/责任制清单/投入台账三张表，Agent 对"该开的会、该签的字、
该做的检查"进行核验并定期输出督办闭环率报告。`}
    />
  )
}
