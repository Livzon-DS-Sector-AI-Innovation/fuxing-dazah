import type {
  SafetyCheck, SafetyCheckQueryParams,
  HazardReport, HazardReportQueryParams,
  Accident, AccidentQueryParams,
  SafetyTraining, SafetyTrainingQueryParams, TrainingRecord,
  OperationRegulation, OperationRegulationQueryParams,
  RegulationRevision, RegulationRevisionQueryParams,
  AIWorkflowConfig, AIWorkflowConfigQueryParams,
  SpecialOperationPersonnel, SpecialOperationPersonnelQueryParams,
  SpecialOperationPermit, SpecialOperationPermitQueryParams,
  SafetyKnowledgeArticle, SafetyKnowledgeArticleQueryParams,
  SpecialOperationReport, SpecialOperationReportQueryParams,
  DailyRiskReport, DailyRiskReportQueryParams,
  HazardIdentification, HazardIdentificationQueryParams,
  EhsChange, EhsChangeQueryParams,
  Contractor, ContractorQueryParams, ContractorWorkRecord,
  OhHazardMonitor, OhHazardMonitorQueryParams,
  OhHealthExam, OhHealthExamQueryParams,
  ScheduledTask, ScheduledTaskQueryParams, ScheduledTaskLog, DataSourceOption, FeishuChat,
} from '@/types/safety'

export const initialCheckState = {
  checks: [] as SafetyCheck[],
  currentCheck: null,
  checkQueryParams: { page: 1, page_size: 20 } as SafetyCheckQueryParams,
  checkTotal: 0,
  checkLoading: false,
}

export const initialHazardState = {
  hazards: [] as HazardReport[],
  currentHazard: null,
  hazardQueryParams: { page: 1, page_size: 20 } as HazardReportQueryParams,
  hazardTotal: 0,
  hazardLoading: false,
}

export const initialAccidentState = {
  accidents: [] as Accident[],
  currentAccident: null,
  accidentQueryParams: { page: 1, page_size: 20 } as AccidentQueryParams,
  accidentTotal: 0,
  accidentLoading: false,
}

export const initialTrainingState = {
  trainings: [] as SafetyTraining[],
  currentTraining: null,
  trainingRecords: [] as TrainingRecord[],
  trainingQueryParams: { page: 1, page_size: 20 } as SafetyTrainingQueryParams,
  trainingTotal: 0,
  trainingLoading: false,
}

export const initialRegulationState = {
  regulations: [] as OperationRegulation[],
  currentRegulation: null as OperationRegulation | null,
  regulationQueryParams: { page: 1, page_size: 20 } as OperationRegulationQueryParams,
  regulationTotal: 0,
  regulationLoading: false,
}

export const initialRevisionState = {
  revisions: [] as RegulationRevision[],
  currentRevision: null as RegulationRevision | null,
  revisionQueryParams: { page: 1, page_size: 20 } as RegulationRevisionQueryParams,
  revisionTotal: 0,
  revisionLoading: false,
}

export const initialAIWorkflowConfigState = {
  aiWorkflowConfigs: [] as AIWorkflowConfig[],
  currentAIWorkflowConfig: null as AIWorkflowConfig | null,
  aiWorkflowConfigQueryParams: { page: 1, page_size: 100 } as AIWorkflowConfigQueryParams,
  aiWorkflowConfigTotal: 0,
  aiWorkflowConfigLoading: false,
}

export const initialPersonnelState = {
  personnel: [] as SpecialOperationPersonnel[],
  currentPersonnel: null as SpecialOperationPersonnel | null,
  personnelQueryParams: { page: 1, page_size: 20 } as SpecialOperationPersonnelQueryParams,
  personnelTotal: 0,
  personnelLoading: false,
}

export const initialPermitState = {
  permits: [] as SpecialOperationPermit[],
  currentPermit: null as SpecialOperationPermit | null,
  permitQueryParams: { page: 1, page_size: 20 } as SpecialOperationPermitQueryParams,
  permitTotal: 0,
  permitLoading: false,
}

export const initialArticleState = {
  articles: [] as SafetyKnowledgeArticle[],
  currentArticle: null as SafetyKnowledgeArticle | null,
  articleQueryParams: { page: 1, page_size: 20 } as SafetyKnowledgeArticleQueryParams,
  articleTotal: 0,
  articleLoading: false,
}

export const initialSpecialOpReportState = {
  specialOpReports: [] as SpecialOperationReport[],
  currentSpecialOpReport: null as SpecialOperationReport | null,
  specialOpReportQueryParams: { page: 1, page_size: 20 } as SpecialOperationReportQueryParams,
  specialOpReportTotal: 0,
  specialOpReportLoading: false,
}

export const initialDailyRiskReportState = {
  dailyRiskReports: [] as DailyRiskReport[],
  currentDailyRiskReport: null as DailyRiskReport | null,
  dailyRiskReportQueryParams: { page: 1, page_size: 20 } as DailyRiskReportQueryParams,
  dailyRiskReportTotal: 0,
  dailyRiskReportLoading: false,
}

export const initialHazardIdentificationState = {
  hazardIdentifications: [] as HazardIdentification[],
  currentHazardIdentification: null as HazardIdentification | null,
  hazardIdentificationQueryParams: { page: 1, page_size: 20 } as HazardIdentificationQueryParams,
  hazardIdentificationTotal: 0,
  hazardIdentificationLoading: false,
}

export const initialEhsChangeState = {
  ehsChanges: [] as EhsChange[],
  currentEhsChange: null as EhsChange | null,
  ehsChangeQueryParams: { page: 1, page_size: 20 } as EhsChangeQueryParams,
  ehsChangeTotal: 0,
  ehsChangeLoading: false,
}

export const initialContractorState = {
  contractors: [] as Contractor[],
  currentContractor: null as Contractor | null,
  contractorQueryParams: { page: 1, page_size: 20 } as ContractorQueryParams,
  contractorTotal: 0,
  contractorLoading: false,
  contractorWorkRecords: [] as ContractorWorkRecord[],
}

export const initialOhHazardMonitorState = {
  ohHazardMonitors: [] as OhHazardMonitor[],
  currentOhHazardMonitor: null as OhHazardMonitor | null,
  ohHazardMonitorQueryParams: { page: 1, page_size: 20 } as OhHazardMonitorQueryParams,
  ohHazardMonitorTotal: 0,
  ohHazardMonitorLoading: false,
}

export const initialOhHealthExamState = {
  ohHealthExams: [] as OhHealthExam[],
  currentOhHealthExam: null as OhHealthExam | null,
  ohHealthExamQueryParams: { page: 1, page_size: 20 } as OhHealthExamQueryParams,
  ohHealthExamTotal: 0,
  ohHealthExamLoading: false,
}

export const initialScheduledTaskState = {
  scheduledTasks: [] as ScheduledTask[],
  currentScheduledTask: null as ScheduledTask | null,
  scheduledTaskQueryParams: { page: 1, page_size: 20 } as ScheduledTaskQueryParams,
  scheduledTaskTotal: 0,
  scheduledTaskLoading: false,
  scheduledTaskLogs: [] as ScheduledTaskLog[],
  scheduledTaskLogsLoading: false,
  dataSourceOptions: [] as DataSourceOption[],
  feishuChats: [] as FeishuChat[],
}
