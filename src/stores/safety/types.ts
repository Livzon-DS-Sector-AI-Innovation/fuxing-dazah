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

// ============ Store State Types ============

export interface SafetyState {
  // Check state
  checks: SafetyCheck[]
  currentCheck: SafetyCheck | null
  checkQueryParams: SafetyCheckQueryParams
  checkTotal: number
  checkLoading: boolean

  // Hazard state
  hazards: HazardReport[]
  currentHazard: HazardReport | null
  hazardQueryParams: HazardReportQueryParams
  hazardTotal: number
  hazardLoading: boolean

  // Accident state
  accidents: Accident[]
  currentAccident: Accident | null
  accidentQueryParams: AccidentQueryParams
  accidentTotal: number
  accidentLoading: boolean

  // Training state
  trainings: SafetyTraining[]
  currentTraining: SafetyTraining | null
  trainingRecords: TrainingRecord[]
  trainingQueryParams: SafetyTrainingQueryParams
  trainingTotal: number
  trainingLoading: boolean

  // Regulation state
  regulations: OperationRegulation[]
  currentRegulation: OperationRegulation | null
  regulationQueryParams: OperationRegulationQueryParams
  regulationTotal: number
  regulationLoading: boolean

  // Revision state
  revisions: RegulationRevision[]
  currentRevision: RegulationRevision | null
  revisionQueryParams: RegulationRevisionQueryParams
  revisionTotal: number
  revisionLoading: boolean

  // AI workflow config state
  aiWorkflowConfigs: AIWorkflowConfig[]
  currentAIWorkflowConfig: AIWorkflowConfig | null
  aiWorkflowConfigQueryParams: AIWorkflowConfigQueryParams
  aiWorkflowConfigTotal: number
  aiWorkflowConfigLoading: boolean

  // Special operation personnel state
  personnel: SpecialOperationPersonnel[]
  currentPersonnel: SpecialOperationPersonnel | null
  personnelQueryParams: SpecialOperationPersonnelQueryParams
  personnelTotal: number
  personnelLoading: boolean

  // Special operation permit state
  permits: SpecialOperationPermit[]
  currentPermit: SpecialOperationPermit | null
  permitQueryParams: SpecialOperationPermitQueryParams
  permitTotal: number
  permitLoading: boolean

  // Knowledge article state
  articles: SafetyKnowledgeArticle[]
  currentArticle: SafetyKnowledgeArticle | null
  articleQueryParams: SafetyKnowledgeArticleQueryParams
  articleTotal: number
  articleLoading: boolean

  // Special operation report state
  specialOpReports: SpecialOperationReport[]
  currentSpecialOpReport: SpecialOperationReport | null
  specialOpReportQueryParams: SpecialOperationReportQueryParams
  specialOpReportTotal: number
  specialOpReportLoading: boolean

  // Daily risk report state
  dailyRiskReports: DailyRiskReport[]
  currentDailyRiskReport: DailyRiskReport | null
  dailyRiskReportQueryParams: DailyRiskReportQueryParams
  dailyRiskReportTotal: number
  dailyRiskReportLoading: boolean

  // EHS change state
  // HazardIdentification state
  hazardIdentifications: HazardIdentification[]
  currentHazardIdentification: HazardIdentification | null
  hazardIdentificationQueryParams: HazardIdentificationQueryParams
  hazardIdentificationTotal: number
  hazardIdentificationLoading: boolean

  ehsChanges: EhsChange[]
  currentEhsChange: EhsChange | null
  ehsChangeQueryParams: EhsChangeQueryParams
  ehsChangeTotal: number
  ehsChangeLoading: boolean

  // Contractor state
  contractors: Contractor[]
  currentContractor: Contractor | null
  contractorQueryParams: ContractorQueryParams
  contractorTotal: number
  contractorLoading: boolean
  contractorWorkRecords: ContractorWorkRecord[]

  // OH Hazard Monitor state
  ohHazardMonitors: OhHazardMonitor[]
  currentOhHazardMonitor: OhHazardMonitor | null
  ohHazardMonitorQueryParams: OhHazardMonitorQueryParams
  ohHazardMonitorTotal: number
  ohHazardMonitorLoading: boolean

  // OH Health Exam state
  ohHealthExams: OhHealthExam[]
  currentOhHealthExam: OhHealthExam | null
  ohHealthExamQueryParams: OhHealthExamQueryParams
  ohHealthExamTotal: number
  ohHealthExamLoading: boolean

  // Scheduled Task state
  scheduledTasks: ScheduledTask[]
  currentScheduledTask: ScheduledTask | null
  scheduledTaskQueryParams: ScheduledTaskQueryParams
  scheduledTaskTotal: number
  scheduledTaskLoading: boolean
  scheduledTaskLogs: ScheduledTaskLog[]
  scheduledTaskLogsLoading: boolean
  dataSourceOptions: DataSourceOption[]
  feishuChats: FeishuChat[]

  // Actions - Check
  setChecks: (checks: SafetyCheck[]) => void
  setCurrentCheck: (check: SafetyCheck | null) => void
  setCheckQueryParams: (params: Partial<SafetyCheckQueryParams>) => void
  setCheckTotal: (total: number) => void
  setCheckLoading: (loading: boolean) => void
  addCheck: (check: SafetyCheck) => void
  updateCheck: (id: string, check: Partial<SafetyCheck>) => void
  removeCheck: (id: string) => void

  // Actions - Hazard
  setHazards: (hazards: HazardReport[]) => void
  setCurrentHazard: (hazard: HazardReport | null) => void
  setHazardQueryParams: (params: Partial<HazardReportQueryParams>) => void
  setHazardTotal: (total: number) => void
  setHazardLoading: (loading: boolean) => void
  addHazard: (hazard: HazardReport) => void
  updateHazard: (id: string, hazard: Partial<HazardReport>) => void
  removeHazard: (id: string) => void

  // Actions - Accident
  setAccidents: (accidents: Accident[]) => void
  setCurrentAccident: (accident: Accident | null) => void
  setAccidentQueryParams: (params: Partial<AccidentQueryParams>) => void
  setAccidentTotal: (total: number) => void
  setAccidentLoading: (loading: boolean) => void
  addAccident: (accident: Accident) => void
  updateAccident: (id: string, accident: Partial<Accident>) => void
  removeAccident: (id: string) => void

  // Actions - Training
  setTrainings: (trainings: SafetyTraining[]) => void
  setCurrentTraining: (training: SafetyTraining | null) => void
  setTrainingRecords: (records: TrainingRecord[]) => void
  setTrainingQueryParams: (params: Partial<SafetyTrainingQueryParams>) => void
  setTrainingTotal: (total: number) => void
  setTrainingLoading: (loading: boolean) => void
  addTraining: (training: SafetyTraining) => void
  updateTraining: (id: string, training: Partial<SafetyTraining>) => void
  removeTraining: (id: string) => void

  // Actions - Regulation
  setRegulations: (regulations: OperationRegulation[]) => void
  setCurrentRegulation: (regulation: OperationRegulation | null) => void
  setRegulationQueryParams: (params: Partial<OperationRegulationQueryParams>) => void
  setRegulationTotal: (total: number) => void
  setRegulationLoading: (loading: boolean) => void
  addRegulation: (regulation: OperationRegulation) => void
  updateRegulation: (id: string, regulation: Partial<OperationRegulation>) => void
  removeRegulation: (id: string) => void

  // Actions - Revision
  setRevisions: (revisions: RegulationRevision[]) => void
  setCurrentRevision: (revision: RegulationRevision | null) => void
  setRevisionQueryParams: (params: Partial<RegulationRevisionQueryParams>) => void
  setRevisionTotal: (total: number) => void
  setRevisionLoading: (loading: boolean) => void
  addRevision: (revision: RegulationRevision) => void
  updateRevision: (id: string, revision: Partial<RegulationRevision>) => void
  removeRevision: (id: string) => void

  // Actions - AI Workflow Config
  setAIWorkflowConfigs: (configs: AIWorkflowConfig[]) => void
  setCurrentAIWorkflowConfig: (config: AIWorkflowConfig | null) => void
  setAIWorkflowConfigQueryParams: (params: Partial<AIWorkflowConfigQueryParams>) => void
  setAIWorkflowConfigTotal: (total: number) => void
  setAIWorkflowConfigLoading: (loading: boolean) => void
  addAIWorkflowConfig: (config: AIWorkflowConfig) => void
  updateAIWorkflowConfig: (id: string, config: Partial<AIWorkflowConfig>) => void
  removeAIWorkflowConfig: (id: string) => void

  // Actions - Personnel
  setPersonnel: (personnel: SpecialOperationPersonnel[]) => void
  setCurrentPersonnel: (p: SpecialOperationPersonnel | null) => void
  setPersonnelQueryParams: (params: Partial<SpecialOperationPersonnelQueryParams>) => void
  setPersonnelTotal: (total: number) => void
  setPersonnelLoading: (loading: boolean) => void
  addPersonnel: (p: SpecialOperationPersonnel) => void
  updatePersonnel: (id: string, p: Partial<SpecialOperationPersonnel>) => void
  removePersonnel: (id: string) => void

  // Actions - Permit
  setPermits: (permits: SpecialOperationPermit[]) => void
  setCurrentPermit: (p: SpecialOperationPermit | null) => void
  setPermitQueryParams: (params: Partial<SpecialOperationPermitQueryParams>) => void
  setPermitTotal: (total: number) => void
  setPermitLoading: (loading: boolean) => void
  addPermit: (p: SpecialOperationPermit) => void
  updatePermit: (id: string, p: Partial<SpecialOperationPermit>) => void
  removePermit: (id: string) => void

  // Actions - Knowledge Article
  setArticles: (articles: SafetyKnowledgeArticle[]) => void
  setCurrentArticle: (a: SafetyKnowledgeArticle | null) => void
  setArticleQueryParams: (params: Partial<SafetyKnowledgeArticleQueryParams>) => void
  setArticleTotal: (total: number) => void
  setArticleLoading: (loading: boolean) => void
  addArticle: (a: SafetyKnowledgeArticle) => void
  updateArticle: (id: string, a: Partial<SafetyKnowledgeArticle>) => void
  removeArticle: (id: string) => void

  // Actions - Special Operation Report
  setSpecialOpReports: (reports: SpecialOperationReport[]) => void
  setCurrentSpecialOpReport: (r: SpecialOperationReport | null) => void
  setSpecialOpReportQueryParams: (params: Partial<SpecialOperationReportQueryParams>) => void
  setSpecialOpReportTotal: (total: number) => void
  setSpecialOpReportLoading: (loading: boolean) => void
  addSpecialOpReport: (r: SpecialOperationReport) => void
  updateSpecialOpReport: (id: string, r: Partial<SpecialOperationReport>) => void
  removeSpecialOpReport: (id: string) => void

  // Actions - Daily Risk Report
  setDailyRiskReports: (reports: DailyRiskReport[]) => void
  setCurrentDailyRiskReport: (r: DailyRiskReport | null) => void
  setDailyRiskReportQueryParams: (params: Partial<DailyRiskReportQueryParams>) => void
  setDailyRiskReportTotal: (total: number) => void
  setDailyRiskReportLoading: (loading: boolean) => void
  addDailyRiskReport: (r: DailyRiskReport) => void
  updateDailyRiskReport: (id: string, r: Partial<DailyRiskReport>) => void
  removeDailyRiskReport: (id: string) => void

  // Actions - HazardIdentification
  setHazardIdentifications: (items: HazardIdentification[], total?: number) => void
  setCurrentHazardIdentification: (item: HazardIdentification | null) => void
  setHazardIdentificationQueryParams: (params: Partial<HazardIdentificationQueryParams>) => void
  setHazardIdentificationTotal: (total: number) => void
  setHazardIdentificationLoading: (loading: boolean) => void
  addHazardIdentification: (item: HazardIdentification) => void
  updateHazardIdentification: (id: string, item: Partial<HazardIdentification>) => void
  removeHazardIdentification: (id: string) => void

  // Actions - EHS Change
  setEhsChanges: (changes: EhsChange[]) => void
  setCurrentEhsChange: (c: EhsChange | null) => void
  setEhsChangeQueryParams: (params: Partial<EhsChangeQueryParams>) => void
  setEhsChangeTotal: (total: number) => void
  setEhsChangeLoading: (loading: boolean) => void
  addEhsChange: (c: EhsChange) => void
  updateEhsChange: (id: string, c: Partial<EhsChange>) => void
  removeEhsChange: (id: string) => void

  // Actions - Contractor
  setContractors: (contractors: Contractor[]) => void
  setCurrentContractor: (c: Contractor | null) => void
  setContractorQueryParams: (params: Partial<ContractorQueryParams>) => void
  setContractorTotal: (total: number) => void
  setContractorLoading: (loading: boolean) => void
  addContractor: (c: Contractor) => void
  updateContractor: (id: string, c: Partial<Contractor>) => void
  removeContractor: (id: string) => void
  setContractorWorkRecords: (records: ContractorWorkRecord[]) => void

  // Actions - OH Hazard Monitor
  setOhHazardMonitors: (items: OhHazardMonitor[]) => void
  setCurrentOhHazardMonitor: (item: OhHazardMonitor | null) => void
  setOhHazardMonitorQueryParams: (params: Partial<OhHazardMonitorQueryParams>) => void
  setOhHazardMonitorTotal: (total: number) => void
  setOhHazardMonitorLoading: (loading: boolean) => void
  addOhHazardMonitor: (item: OhHazardMonitor) => void
  updateOhHazardMonitor: (id: string, item: Partial<OhHazardMonitor>) => void
  removeOhHazardMonitor: (id: string) => void

  // Actions - OH Health Exam
  setOhHealthExams: (items: OhHealthExam[]) => void
  setCurrentOhHealthExam: (item: OhHealthExam | null) => void
  setOhHealthExamQueryParams: (params: Partial<OhHealthExamQueryParams>) => void
  setOhHealthExamTotal: (total: number) => void
  setOhHealthExamLoading: (loading: boolean) => void
  addOhHealthExam: (item: OhHealthExam) => void
  updateOhHealthExam: (id: string, item: Partial<OhHealthExam>) => void
  removeOhHealthExam: (id: string) => void

  // Actions - Scheduled Task
  setScheduledTasks: (items: ScheduledTask[], total?: number) => void
  setCurrentScheduledTask: (item: ScheduledTask | null) => void
  setScheduledTaskQueryParams: (params: Partial<ScheduledTaskQueryParams>) => void
  setScheduledTaskTotal: (total: number) => void
  setScheduledTaskLoading: (loading: boolean) => void
  addScheduledTask: (item: ScheduledTask) => void
  updateScheduledTask: (id: string, item: Partial<ScheduledTask>) => void
  removeScheduledTask: (id: string) => void
  setScheduledTaskLogs: (logs: ScheduledTaskLog[]) => void
  setScheduledTaskLogsLoading: (loading: boolean) => void
  setDataSourceOptions: (options: DataSourceOption[]) => void
  setFeishuChats: (chats: FeishuChat[]) => void

  // Actions - Reset
  resetScheduledTaskState: () => void
  resetOhHazardMonitorState: () => void
  resetOhHealthExamState: () => void
  resetCheckState: () => void
  resetHazardState: () => void
  resetAccidentState: () => void
  resetTrainingState: () => void
  resetRegulationState: () => void
  resetRevisionState: () => void
  resetAIWorkflowConfigState: () => void
  resetPersonnelState: () => void
  resetPermitState: () => void
  resetArticleState: () => void
  resetSpecialOpReportState: () => void
  resetDailyRiskReportState: () => void
  resetEhsChangeState: () => void
  resetContractorState: () => void
  resetHazardIdentificationState: () => void
  resetAll: () => void
}
