// 事故事件管理 —— 体系要素占位页（业务未开展）

import ModulePlaceholder from '@/components/safety/ModulePlaceholder'

export default function IncidentsPage() {
  return (
    <ModulePlaceholder
      name="事故事件管理"
      scope={`事故与事件的报告登记、分级判定、调查与原因分析；
纠正与预防措施（CAPA）的跟踪闭环；案例警示教育与经验反馈。`}
      agentStatus={`CAPA 行动项的发起、验证、关闭闭环能力已在系统中具备，事故分级字段已预置。
启动后将建设事发即时感知与 AI 分级判定，并自动起草调查报告初稿、
推送同类场景的案例警示。`}
    />
  )
}
