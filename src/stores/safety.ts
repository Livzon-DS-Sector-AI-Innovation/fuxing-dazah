import { create } from 'zustand'
import type {
  Accident,
  AccidentQueryParams,
  AIWorkflowConfig,
  AIWorkflowConfigQueryParams,
  APICallConfig,
  EhsChange,
  EhsChangeQueryParams,
  HazardReport,
  HazardReportQueryParams,
  HazardRevisionArchive,
  HazardRevisionArchiveQueryParams,
  HazardRevisionRecord,
  HazardRevisionRecordQueryParams,
  OhHazardMonitor,
  OhHazardMonitorQueryParams,
  OhHealthExam,
  OhHealthExamQueryParams,
  OperationRegulation,
  OperationRegulationQueryParams,
  RegulationRevision,
  RegulationRevisionQueryParams,
  SafetyCheck,
  SafetyCheckQueryParams,
  SafetyKnowledgeArticle,
  SafetyKnowledgeArticleQueryParams,
  SafetyTraining,
  SafetyTrainingQueryParams,
  SpecialOperationPermit,
  SpecialOperationPermitQueryParams,
  SpecialOperationPersonnel,
  SpecialOperationPersonnelQueryParams,
  SpecialOperationReport,
  SpecialOperationReportQueryParams,
  DailyRiskReport,
  DailyRiskReportQueryParams,
  TrainingRecord,
} from '@/types/safety'

// ============ Store State Types ============

interface SafetyState {
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

  // Hazard revision record state
  hazardRevisionRecords: HazardRevisionRecord[]
  currentHazardRevisionRecord: HazardRevisionRecord | null
  hazardRevisionRecordQueryParams: HazardRevisionRecordQueryParams
  hazardRevisionRecordTotal: number
  hazardRevisionRecordLoading: boolean

  // Hazard revision archive state
  hazardRevisionArchives: HazardRevisionArchive[]
  currentHazardRevisionArchive: HazardRevisionArchive | null
  hazardRevisionArchiveQueryParams: HazardRevisionArchiveQueryParams
  hazardRevisionArchiveTotal: number
  hazardRevisionArchiveLoading: boolean

  // AI workflow config state
  aiWorkflowConfigs: AIWorkflowConfig[]
  currentAIWorkflowConfig: AIWorkflowConfig | null
  aiWorkflowConfigQueryParams: AIWorkflowConfigQueryParams
  aiWorkflowConfigTotal: number
  aiWorkflowConfigLoading: boolean

  // API call config state
  apiCallConfigs: APICallConfig[]
  currentAPICallConfig: APICallConfig | null
  apiCallConfigTotal: number
  apiCallConfigLoading: boolean

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
  ehsChanges: EhsChange[]
  currentEhsChange: EhsChange | null
  ehsChangeQueryParams: EhsChangeQueryParams
  ehsChangeTotal: number
  ehsChangeLoading: boolean

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

  // Actions - Hazard Revision Record
  setHazardRevisionRecords: (records: HazardRevisionRecord[]) => void
  setCurrentHazardRevisionRecord: (record: HazardRevisionRecord | null) => void
  setHazardRevisionRecordQueryParams: (params: Partial<HazardRevisionRecordQueryParams>) => void
  setHazardRevisionRecordTotal: (total: number) => void
  setHazardRevisionRecordLoading: (loading: boolean) => void
  addHazardRevisionRecord: (record: HazardRevisionRecord) => void
  updateHazardRevisionRecord: (id: string, record: Partial<HazardRevisionRecord>) => void
  removeHazardRevisionRecord: (id: string) => void

  // Actions - Hazard Revision Archive
  setHazardRevisionArchives: (archives: HazardRevisionArchive[]) => void
  setCurrentHazardRevisionArchive: (archive: HazardRevisionArchive | null) => void
  setHazardRevisionArchiveQueryParams: (params: Partial<HazardRevisionArchiveQueryParams>) => void
  setHazardRevisionArchiveTotal: (total: number) => void
  setHazardRevisionArchiveLoading: (loading: boolean) => void
  addHazardRevisionArchive: (archive: HazardRevisionArchive) => void
  updateHazardRevisionArchive: (id: string, archive: Partial<HazardRevisionArchive>) => void
  removeHazardRevisionArchive: (id: string) => void

  // Actions - AI Workflow Config
  setAIWorkflowConfigs: (configs: AIWorkflowConfig[]) => void
  setCurrentAIWorkflowConfig: (config: AIWorkflowConfig | null) => void
  setAIWorkflowConfigQueryParams: (params: Partial<AIWorkflowConfigQueryParams>) => void
  setAIWorkflowConfigTotal: (total: number) => void
  setAIWorkflowConfigLoading: (loading: boolean) => void
  addAIWorkflowConfig: (config: AIWorkflowConfig) => void
  updateAIWorkflowConfig: (id: string, config: Partial<AIWorkflowConfig>) => void
  removeAIWorkflowConfig: (id: string) => void

  // Actions - API Call Config
  setAPICallConfigs: (configs: APICallConfig[]) => void
  setCurrentAPICallConfig: (config: APICallConfig | null) => void
  setAPICallConfigTotal: (total: number) => void
  setAPICallConfigLoading: (loading: boolean) => void
  addAPICallConfig: (config: APICallConfig) => void
  updateAPICallConfig: (id: string, config: Partial<APICallConfig>) => void
  removeAPICallConfig: (id: string) => void

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

  // Actions - EHS Change
  setEhsChanges: (changes: EhsChange[]) => void
  setCurrentEhsChange: (c: EhsChange | null) => void
  setEhsChangeQueryParams: (params: Partial<EhsChangeQueryParams>) => void
  setEhsChangeTotal: (total: number) => void
  setEhsChangeLoading: (loading: boolean) => void
  addEhsChange: (c: EhsChange) => void
  updateEhsChange: (id: string, c: Partial<EhsChange>) => void
  removeEhsChange: (id: string) => void

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

  // Actions - Reset
  resetOhHazardMonitorState: () => void
  resetOhHealthExamState: () => void
  resetCheckState: () => void
  resetHazardState: () => void
  resetAccidentState: () => void
  resetTrainingState: () => void
  resetRegulationState: () => void
  resetRevisionState: () => void
  resetHazardRevisionRecordState: () => void
  resetHazardRevisionArchiveState: () => void
  resetAIWorkflowConfigState: () => void
  resetAPICallConfigState: () => void
  resetPersonnelState: () => void
  resetPermitState: () => void
  resetArticleState: () => void
  resetSpecialOpReportState: () => void
  resetDailyRiskReportState: () => void
  resetEhsChangeState: () => void
  resetAll: () => void
}

const initialCheckState = {
  checks: [] as SafetyCheck[],
  currentCheck: null,
  checkQueryParams: { page: 1, page_size: 20 } as SafetyCheckQueryParams,
  checkTotal: 0,
  checkLoading: false,
}

const initialHazardState = {
  hazards: [] as HazardReport[],
  currentHazard: null,
  hazardQueryParams: { page: 1, page_size: 20 } as HazardReportQueryParams,
  hazardTotal: 0,
  hazardLoading: false,
}

const initialAccidentState = {
  accidents: [] as Accident[],
  currentAccident: null,
  accidentQueryParams: { page: 1, page_size: 20 } as AccidentQueryParams,
  accidentTotal: 0,
  accidentLoading: false,
}

const initialTrainingState = {
  trainings: [] as SafetyTraining[],
  currentTraining: null,
  trainingRecords: [] as TrainingRecord[],
  trainingQueryParams: { page: 1, page_size: 20 } as SafetyTrainingQueryParams,
  trainingTotal: 0,
  trainingLoading: false,
}

const initialRegulationState = {
  regulations: [] as OperationRegulation[],
  currentRegulation: null as OperationRegulation | null,
  regulationQueryParams: { page: 1, page_size: 20 } as OperationRegulationQueryParams,
  regulationTotal: 0,
  regulationLoading: false,
}

const initialRevisionState = {
  revisions: [] as RegulationRevision[],
  currentRevision: null as RegulationRevision | null,
  revisionQueryParams: { page: 1, page_size: 20 } as RegulationRevisionQueryParams,
  revisionTotal: 0,
  revisionLoading: false,
}

const initialHazardRevisionRecordState = {
  hazardRevisionRecords: [] as HazardRevisionRecord[],
  currentHazardRevisionRecord: null as HazardRevisionRecord | null,
  hazardRevisionRecordQueryParams: { page: 1, page_size: 20 } as HazardRevisionRecordQueryParams,
  hazardRevisionRecordTotal: 0,
  hazardRevisionRecordLoading: false,
}

const initialHazardRevisionArchiveState = {
  hazardRevisionArchives: [] as HazardRevisionArchive[],
  currentHazardRevisionArchive: null as HazardRevisionArchive | null,
  hazardRevisionArchiveQueryParams: { page: 1, page_size: 20 } as HazardRevisionArchiveQueryParams,
  hazardRevisionArchiveTotal: 0,
  hazardRevisionArchiveLoading: false,
}

const initialAIWorkflowConfigState = {
  aiWorkflowConfigs: [] as AIWorkflowConfig[],
  currentAIWorkflowConfig: null as AIWorkflowConfig | null,
  aiWorkflowConfigQueryParams: { page: 1, page_size: 100 } as AIWorkflowConfigQueryParams,
  aiWorkflowConfigTotal: 0,
  aiWorkflowConfigLoading: false,
}

const initialAPICallConfigState = {
  apiCallConfigs: [] as APICallConfig[],
  currentAPICallConfig: null as APICallConfig | null,
  apiCallConfigTotal: 0,
  apiCallConfigLoading: false,
}

const initialPersonnelState = {
  personnel: [] as SpecialOperationPersonnel[],
  currentPersonnel: null as SpecialOperationPersonnel | null,
  personnelQueryParams: { page: 1, page_size: 20 } as SpecialOperationPersonnelQueryParams,
  personnelTotal: 0,
  personnelLoading: false,
}

const initialPermitState = {
  permits: [] as SpecialOperationPermit[],
  currentPermit: null as SpecialOperationPermit | null,
  permitQueryParams: { page: 1, page_size: 20 } as SpecialOperationPermitQueryParams,
  permitTotal: 0,
  permitLoading: false,
}

const initialArticleState = {
  articles: [] as SafetyKnowledgeArticle[],
  currentArticle: null as SafetyKnowledgeArticle | null,
  articleQueryParams: { page: 1, page_size: 20 } as SafetyKnowledgeArticleQueryParams,
  articleTotal: 0,
  articleLoading: false,
}

const initialSpecialOpReportState = {
  specialOpReports: [] as SpecialOperationReport[],
  currentSpecialOpReport: null as SpecialOperationReport | null,
  specialOpReportQueryParams: { page: 1, page_size: 20 } as SpecialOperationReportQueryParams,
  specialOpReportTotal: 0,
  specialOpReportLoading: false,
}

const initialDailyRiskReportState = {
  dailyRiskReports: [] as DailyRiskReport[],
  currentDailyRiskReport: null as DailyRiskReport | null,
  dailyRiskReportQueryParams: { page: 1, page_size: 20 } as DailyRiskReportQueryParams,
  dailyRiskReportTotal: 0,
  dailyRiskReportLoading: false,
}

const initialEhsChangeState = {
  ehsChanges: [] as EhsChange[],
  currentEhsChange: null as EhsChange | null,
  ehsChangeQueryParams: { page: 1, page_size: 20 } as EhsChangeQueryParams,
  ehsChangeTotal: 0,
  ehsChangeLoading: false,
}

const initialOhHazardMonitorState = {
  ohHazardMonitors: [] as OhHazardMonitor[],
  currentOhHazardMonitor: null as OhHazardMonitor | null,
  ohHazardMonitorQueryParams: { page: 1, page_size: 20 } as OhHazardMonitorQueryParams,
  ohHazardMonitorTotal: 0,
  ohHazardMonitorLoading: false,
}

const initialOhHealthExamState = {
  ohHealthExams: [] as OhHealthExam[],
  currentOhHealthExam: null as OhHealthExam | null,
  ohHealthExamQueryParams: { page: 1, page_size: 20 } as OhHealthExamQueryParams,
  ohHealthExamTotal: 0,
  ohHealthExamLoading: false,
}

export const useSafetyStore = create<SafetyState>((set) => ({
  // Initial states
  ...initialCheckState,
  ...initialHazardState,
  ...initialAccidentState,
  ...initialTrainingState,
  ...initialRegulationState,
  ...initialRevisionState,
  ...initialHazardRevisionRecordState,
  ...initialHazardRevisionArchiveState,
  ...initialAIWorkflowConfigState,
  ...initialAPICallConfigState,
  ...initialPersonnelState,
  ...initialPermitState,
  ...initialArticleState,
  ...initialSpecialOpReportState,
  ...initialDailyRiskReportState,
  ...initialEhsChangeState,
  ...initialOhHazardMonitorState,
  ...initialOhHealthExamState,

  // ============ Check Actions ============
  setChecks: (checks) => set({ checks }),
  setCurrentCheck: (check) => set({ currentCheck: check }),
  setCheckQueryParams: (params) =>
    set((state) => ({ checkQueryParams: { ...state.checkQueryParams, ...params } })),
  setCheckTotal: (total) => set({ checkTotal: total }),
  setCheckLoading: (loading) => set({ checkLoading: loading }),

  addCheck: (check) =>
    set((state) => ({ checks: [check, ...state.checks] })),

  updateCheck: (id, updates) =>
    set((state) => ({
      checks: state.checks.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentCheck: state.currentCheck?.id === id ? { ...state.currentCheck, ...updates } : state.currentCheck,
    })),

  removeCheck: (id) =>
    set((state) => ({
      checks: state.checks.filter((c) => c.id !== id),
      currentCheck: state.currentCheck?.id === id ? null : state.currentCheck,
    })),

  // ============ Hazard Actions ============
  setHazards: (hazards) => set({ hazards }),
  setCurrentHazard: (hazard) => set({ currentHazard: hazard }),
  setHazardQueryParams: (params) =>
    set((state) => ({ hazardQueryParams: { ...state.hazardQueryParams, ...params } })),
  setHazardTotal: (total) => set({ hazardTotal: total }),
  setHazardLoading: (loading) => set({ hazardLoading: loading }),

  addHazard: (hazard) =>
    set((state) => ({ hazards: [hazard, ...state.hazards] })),

  updateHazard: (id, updates) =>
    set((state) => ({
      hazards: state.hazards.map((h) => (h.id === id ? { ...h, ...updates } : h)),
      currentHazard: state.currentHazard?.id === id ? { ...state.currentHazard, ...updates } : state.currentHazard,
    })),

  removeHazard: (id) =>
    set((state) => ({
      hazards: state.hazards.filter((h) => h.id !== id),
      currentHazard: state.currentHazard?.id === id ? null : state.currentHazard,
    })),

  // ============ Accident Actions ============
  setAccidents: (accidents) => set({ accidents }),
  setCurrentAccident: (accident) => set({ currentAccident: accident }),
  setAccidentQueryParams: (params) =>
    set((state) => ({ accidentQueryParams: { ...state.accidentQueryParams, ...params } })),
  setAccidentTotal: (total) => set({ accidentTotal: total }),
  setAccidentLoading: (loading) => set({ accidentLoading: loading }),

  addAccident: (accident) =>
    set((state) => ({ accidents: [accident, ...state.accidents] })),

  updateAccident: (id, updates) =>
    set((state) => ({
      accidents: state.accidents.map((a) => (a.id === id ? { ...a, ...updates } : a)),
      currentAccident: state.currentAccident?.id === id ? { ...state.currentAccident, ...updates } : state.currentAccident,
    })),

  removeAccident: (id) =>
    set((state) => ({
      accidents: state.accidents.filter((a) => a.id !== id),
      currentAccident: state.currentAccident?.id === id ? null : state.currentAccident,
    })),

  // ============ Training Actions ============
  setTrainings: (trainings) => set({ trainings }),
  setCurrentTraining: (training) => set({ currentTraining: training }),
  setTrainingRecords: (records) => set({ trainingRecords: records }),
  setTrainingQueryParams: (params) =>
    set((state) => ({ trainingQueryParams: { ...state.trainingQueryParams, ...params } })),
  setTrainingTotal: (total) => set({ trainingTotal: total }),
  setTrainingLoading: (loading) => set({ trainingLoading: loading }),

  addTraining: (training) =>
    set((state) => ({ trainings: [training, ...state.trainings] })),

  updateTraining: (id, updates) =>
    set((state) => ({
      trainings: state.trainings.map((t) => (t.id === id ? { ...t, ...updates } : t)),
      currentTraining: state.currentTraining?.id === id ? { ...state.currentTraining, ...updates } : state.currentTraining,
    })),

  removeTraining: (id) =>
    set((state) => ({
      trainings: state.trainings.filter((t) => t.id !== id),
      currentTraining: state.currentTraining?.id === id ? null : state.currentTraining,
    })),

  // ============ Regulation Actions ============
  setRegulations: (regulations) => set({ regulations }),
  setCurrentRegulation: (regulation) => set({ currentRegulation: regulation }),
  setRegulationQueryParams: (params) =>
    set((state) => ({ regulationQueryParams: { ...state.regulationQueryParams, ...params } })),
  setRegulationTotal: (total) => set({ regulationTotal: total }),
  setRegulationLoading: (loading) => set({ regulationLoading: loading }),

  addRegulation: (regulation) =>
    set((state) => ({ regulations: [regulation, ...state.regulations] })),

  updateRegulation: (id, updates) =>
    set((state) => ({
      regulations: state.regulations.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentRegulation:
        state.currentRegulation?.id === id
          ? { ...state.currentRegulation, ...updates }
          : state.currentRegulation,
    })),

  removeRegulation: (id) =>
    set((state) => ({
      regulations: state.regulations.filter((r) => r.id !== id),
      currentRegulation: state.currentRegulation?.id === id ? null : state.currentRegulation,
    })),

  // ============ Revision Actions ============
  setRevisions: (revisions) => set({ revisions }),
  setCurrentRevision: (revision) => set({ currentRevision: revision }),
  setRevisionQueryParams: (params) =>
    set((state) => ({ revisionQueryParams: { ...state.revisionQueryParams, ...params } })),
  setRevisionTotal: (total) => set({ revisionTotal: total }),
  setRevisionLoading: (loading) => set({ revisionLoading: loading }),

  addRevision: (revision) =>
    set((state) => ({ revisions: [revision, ...state.revisions] })),

  updateRevision: (id, updates) =>
    set((state) => ({
      revisions: state.revisions.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentRevision:
        state.currentRevision?.id === id
          ? { ...state.currentRevision, ...updates }
          : state.currentRevision,
    })),

  removeRevision: (id) =>
    set((state) => ({
      revisions: state.revisions.filter((r) => r.id !== id),
      currentRevision: state.currentRevision?.id === id ? null : state.currentRevision,
    })),

  // ============ Hazard Revision Record Actions ============
  setHazardRevisionRecords: (records) => set({ hazardRevisionRecords: records }),
  setCurrentHazardRevisionRecord: (record) => set({ currentHazardRevisionRecord: record }),
  setHazardRevisionRecordQueryParams: (params) =>
    set((state) => ({
      hazardRevisionRecordQueryParams: { ...state.hazardRevisionRecordQueryParams, ...params },
    })),
  setHazardRevisionRecordTotal: (total) => set({ hazardRevisionRecordTotal: total }),
  setHazardRevisionRecordLoading: (loading) => set({ hazardRevisionRecordLoading: loading }),

  addHazardRevisionRecord: (record) =>
    set((state) => ({ hazardRevisionRecords: [record, ...state.hazardRevisionRecords] })),

  updateHazardRevisionRecord: (id, updates) =>
    set((state) => ({
      hazardRevisionRecords: state.hazardRevisionRecords.map((r) =>
        r.id === id ? { ...r, ...updates } : r
      ),
      currentHazardRevisionRecord:
        state.currentHazardRevisionRecord?.id === id
          ? { ...state.currentHazardRevisionRecord, ...updates }
          : state.currentHazardRevisionRecord,
    })),

  removeHazardRevisionRecord: (id) =>
    set((state) => ({
      hazardRevisionRecords: state.hazardRevisionRecords.filter((r) => r.id !== id),
      currentHazardRevisionRecord:
        state.currentHazardRevisionRecord?.id === id ? null : state.currentHazardRevisionRecord,
    })),

  // ============ Hazard Revision Archive Actions ============
  setHazardRevisionArchives: (archives) => set({ hazardRevisionArchives: archives }),
  setCurrentHazardRevisionArchive: (archive) => set({ currentHazardRevisionArchive: archive }),
  setHazardRevisionArchiveQueryParams: (params) =>
    set((state) => ({
      hazardRevisionArchiveQueryParams: { ...state.hazardRevisionArchiveQueryParams, ...params },
    })),
  setHazardRevisionArchiveTotal: (total) => set({ hazardRevisionArchiveTotal: total }),
  setHazardRevisionArchiveLoading: (loading) => set({ hazardRevisionArchiveLoading: loading }),

  addHazardRevisionArchive: (archive) =>
    set((state) => ({ hazardRevisionArchives: [archive, ...state.hazardRevisionArchives] })),

  updateHazardRevisionArchive: (id, updates) =>
    set((state) => ({
      hazardRevisionArchives: state.hazardRevisionArchives.map((a) =>
        a.id === id ? { ...a, ...updates } : a
      ),
      currentHazardRevisionArchive:
        state.currentHazardRevisionArchive?.id === id
          ? { ...state.currentHazardRevisionArchive, ...updates }
          : state.currentHazardRevisionArchive,
    })),

  removeHazardRevisionArchive: (id) =>
    set((state) => ({
      hazardRevisionArchives: state.hazardRevisionArchives.filter((a) => a.id !== id),
      currentHazardRevisionArchive:
        state.currentHazardRevisionArchive?.id === id ? null : state.currentHazardRevisionArchive,
    })),

  // ============ AI Workflow Config Actions ============
  setAIWorkflowConfigs: (configs) => set({ aiWorkflowConfigs: configs }),
  setCurrentAIWorkflowConfig: (config) => set({ currentAIWorkflowConfig: config }),
  setAIWorkflowConfigQueryParams: (params) =>
    set((state) => ({
      aiWorkflowConfigQueryParams: { ...state.aiWorkflowConfigQueryParams, ...params },
    })),
  setAIWorkflowConfigTotal: (total) => set({ aiWorkflowConfigTotal: total }),
  setAIWorkflowConfigLoading: (loading) => set({ aiWorkflowConfigLoading: loading }),

  addAIWorkflowConfig: (config) =>
    set((state) => ({ aiWorkflowConfigs: [config, ...state.aiWorkflowConfigs] })),

  updateAIWorkflowConfig: (id, updates) =>
    set((state) => ({
      aiWorkflowConfigs: state.aiWorkflowConfigs.map((c) =>
        c.id === id ? { ...c, ...updates } : c
      ),
      currentAIWorkflowConfig:
        state.currentAIWorkflowConfig?.id === id
          ? { ...state.currentAIWorkflowConfig, ...updates }
          : state.currentAIWorkflowConfig,
    })),

  removeAIWorkflowConfig: (id) =>
    set((state) => ({
      aiWorkflowConfigs: state.aiWorkflowConfigs.filter((c) => c.id !== id),
      currentAIWorkflowConfig:
        state.currentAIWorkflowConfig?.id === id ? null : state.currentAIWorkflowConfig,
    })),

  // ============ API Call Config Actions ============
  setAPICallConfigs: (configs) => set({ apiCallConfigs: configs }),
  setCurrentAPICallConfig: (config) => set({ currentAPICallConfig: config }),
  setAPICallConfigTotal: (total) => set({ apiCallConfigTotal: total }),
  setAPICallConfigLoading: (loading) => set({ apiCallConfigLoading: loading }),

  addAPICallConfig: (config) =>
    set((state) => ({ apiCallConfigs: [config, ...state.apiCallConfigs] })),

  updateAPICallConfig: (id, updates) =>
    set((state) => ({
      apiCallConfigs: state.apiCallConfigs.map((c) =>
        c.id === id ? { ...c, ...updates } : c
      ),
      currentAPICallConfig:
        state.currentAPICallConfig?.id === id
          ? { ...state.currentAPICallConfig, ...updates }
          : state.currentAPICallConfig,
    })),

  removeAPICallConfig: (id) =>
    set((state) => ({
      apiCallConfigs: state.apiCallConfigs.filter((c) => c.id !== id),
      currentAPICallConfig:
        state.currentAPICallConfig?.id === id ? null : state.currentAPICallConfig,
    })),

  // ============ Personnel Actions ============
  setPersonnel: (personnel) => set({ personnel }),
  setCurrentPersonnel: (p) => set({ currentPersonnel: p }),
  setPersonnelQueryParams: (params) =>
    set((state) => ({ personnelQueryParams: { ...state.personnelQueryParams, ...params } })),
  setPersonnelTotal: (total) => set({ personnelTotal: total }),
  setPersonnelLoading: (loading) => set({ personnelLoading: loading }),

  addPersonnel: (p) =>
    set((state) => ({ personnel: [p, ...state.personnel] })),

  updatePersonnel: (id, updates) =>
    set((state) => ({
      personnel: state.personnel.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentPersonnel: state.currentPersonnel?.id === id ? { ...state.currentPersonnel, ...updates } : state.currentPersonnel,
    })),

  removePersonnel: (id) =>
    set((state) => ({
      personnel: state.personnel.filter((r) => r.id !== id),
      currentPersonnel: state.currentPersonnel?.id === id ? null : state.currentPersonnel,
    })),

  // ============ Permit Actions ============
  setPermits: (permits) => set({ permits }),
  setCurrentPermit: (p) => set({ currentPermit: p }),
  setPermitQueryParams: (params) =>
    set((state) => ({ permitQueryParams: { ...state.permitQueryParams, ...params } })),
  setPermitTotal: (total) => set({ permitTotal: total }),
  setPermitLoading: (loading) => set({ permitLoading: loading }),

  addPermit: (p) =>
    set((state) => ({ permits: [p, ...state.permits] })),

  updatePermit: (id, updates) =>
    set((state) => ({
      permits: state.permits.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentPermit: state.currentPermit?.id === id ? { ...state.currentPermit, ...updates } : state.currentPermit,
    })),

  removePermit: (id) =>
    set((state) => ({
      permits: state.permits.filter((r) => r.id !== id),
      currentPermit: state.currentPermit?.id === id ? null : state.currentPermit,
    })),

  // ============ Knowledge Article Actions ============
  setArticles: (articles) => set({ articles }),
  setCurrentArticle: (a) => set({ currentArticle: a }),
  setArticleQueryParams: (params) =>
    set((state) => ({ articleQueryParams: { ...state.articleQueryParams, ...params } })),
  setArticleTotal: (total) => set({ articleTotal: total }),
  setArticleLoading: (loading) => set({ articleLoading: loading }),

  addArticle: (a) =>
    set((state) => ({ articles: [a, ...state.articles] })),

  updateArticle: (id, updates) =>
    set((state) => ({
      articles: state.articles.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentArticle: state.currentArticle?.id === id ? { ...state.currentArticle, ...updates } : state.currentArticle,
    })),

  removeArticle: (id) =>
    set((state) => ({
      articles: state.articles.filter((r) => r.id !== id),
      currentArticle: state.currentArticle?.id === id ? null : state.currentArticle,
    })),

  // ============ Special Operation Report Actions ============
  setSpecialOpReports: (reports) => set({ specialOpReports: reports }),
  setCurrentSpecialOpReport: (r) => set({ currentSpecialOpReport: r }),
  setSpecialOpReportQueryParams: (params) =>
    set((state) => ({ specialOpReportQueryParams: { ...state.specialOpReportQueryParams, ...params } })),
  setSpecialOpReportTotal: (total) => set({ specialOpReportTotal: total }),
  setSpecialOpReportLoading: (loading) => set({ specialOpReportLoading: loading }),

  addSpecialOpReport: (r) =>
    set((state) => ({ specialOpReports: [r, ...state.specialOpReports] })),
  updateSpecialOpReport: (id, updates) =>
    set((state) => ({
      specialOpReports: state.specialOpReports.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentSpecialOpReport: state.currentSpecialOpReport?.id === id ? { ...state.currentSpecialOpReport, ...updates } : state.currentSpecialOpReport,
    })),
  removeSpecialOpReport: (id) =>
    set((state) => ({
      specialOpReports: state.specialOpReports.filter((r) => r.id !== id),
      currentSpecialOpReport: state.currentSpecialOpReport?.id === id ? null : state.currentSpecialOpReport,
    })),

  // ============ Daily Risk Report Actions ============
  setDailyRiskReports: (reports) => set({ dailyRiskReports: reports }),
  setCurrentDailyRiskReport: (r) => set({ currentDailyRiskReport: r }),
  setDailyRiskReportQueryParams: (params) =>
    set((state) => ({ dailyRiskReportQueryParams: { ...state.dailyRiskReportQueryParams, ...params } })),
  setDailyRiskReportTotal: (total) => set({ dailyRiskReportTotal: total }),
  setDailyRiskReportLoading: (loading) => set({ dailyRiskReportLoading: loading }),

  addDailyRiskReport: (r) =>
    set((state) => ({ dailyRiskReports: [r, ...state.dailyRiskReports] })),
  updateDailyRiskReport: (id, updates) =>
    set((state) => ({
      dailyRiskReports: state.dailyRiskReports.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentDailyRiskReport: state.currentDailyRiskReport?.id === id ? { ...state.currentDailyRiskReport, ...updates } : state.currentDailyRiskReport,
    })),
  removeDailyRiskReport: (id) =>
    set((state) => ({
      dailyRiskReports: state.dailyRiskReports.filter((r) => r.id !== id),
      currentDailyRiskReport: state.currentDailyRiskReport?.id === id ? null : state.currentDailyRiskReport,
    })),

  // ============ EHS Change Actions ============
  setEhsChanges: (ehsChanges) => set({ ehsChanges }),
  setCurrentEhsChange: (currentEhsChange) => set({ currentEhsChange }),
  setEhsChangeQueryParams: (params) =>
    set((state) => ({ ehsChangeQueryParams: { ...state.ehsChangeQueryParams, ...params } })),
  setEhsChangeTotal: (ehsChangeTotal) => set({ ehsChangeTotal }),
  setEhsChangeLoading: (ehsChangeLoading) => set({ ehsChangeLoading }),
  addEhsChange: (c) =>
    set((state) => ({ ehsChanges: [c, ...state.ehsChanges] })),
  updateEhsChange: (id, updates) =>
    set((state) => ({
      ehsChanges: state.ehsChanges.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentEhsChange: state.currentEhsChange?.id === id ? { ...state.currentEhsChange, ...updates } : state.currentEhsChange,
    })),
  removeEhsChange: (id) =>
    set((state) => ({
      ehsChanges: state.ehsChanges.filter((c) => c.id !== id),
      currentEhsChange: state.currentEhsChange?.id === id ? null : state.currentEhsChange,
    })),

  // ============ OH Hazard Monitor Actions ============

  setOhHazardMonitors: (items) => set({ ohHazardMonitors: items }),
  setCurrentOhHazardMonitor: (item) => set({ currentOhHazardMonitor: item }),
  setOhHazardMonitorQueryParams: (params) =>
    set((state) => ({ ohHazardMonitorQueryParams: { ...state.ohHazardMonitorQueryParams, ...params } })),
  setOhHazardMonitorTotal: (total) => set({ ohHazardMonitorTotal: total }),
  setOhHazardMonitorLoading: (loading) => set({ ohHazardMonitorLoading: loading }),
  addOhHazardMonitor: (item) =>
    set((state) => ({ ohHazardMonitors: [item, ...state.ohHazardMonitors] })),
  updateOhHazardMonitor: (id, data) =>
    set((state) => ({
      ohHazardMonitors: state.ohHazardMonitors.map((m) => (m.id === id ? { ...m, ...data } : m)),
      currentOhHazardMonitor: state.currentOhHazardMonitor?.id === id ? { ...state.currentOhHazardMonitor, ...data } : state.currentOhHazardMonitor,
    })),
  removeOhHazardMonitor: (id) =>
    set((state) => ({
      ohHazardMonitors: state.ohHazardMonitors.filter((m) => m.id !== id),
      currentOhHazardMonitor: state.currentOhHazardMonitor?.id === id ? null : state.currentOhHazardMonitor,
    })),

  // ============ OH Health Exam Actions ============

  setOhHealthExams: (items) => set({ ohHealthExams: items }),
  setCurrentOhHealthExam: (item) => set({ currentOhHealthExam: item }),
  setOhHealthExamQueryParams: (params) =>
    set((state) => ({ ohHealthExamQueryParams: { ...state.ohHealthExamQueryParams, ...params } })),
  setOhHealthExamTotal: (total) => set({ ohHealthExamTotal: total }),
  setOhHealthExamLoading: (loading) => set({ ohHealthExamLoading: loading }),
  addOhHealthExam: (item) =>
    set((state) => ({ ohHealthExams: [item, ...state.ohHealthExams] })),
  updateOhHealthExam: (id, data) =>
    set((state) => ({
      ohHealthExams: state.ohHealthExams.map((e) => (e.id === id ? { ...e, ...data } : e)),
      currentOhHealthExam: state.currentOhHealthExam?.id === id ? { ...state.currentOhHealthExam, ...data } : state.currentOhHealthExam,
    })),
  removeOhHealthExam: (id) =>
    set((state) => ({
      ohHealthExams: state.ohHealthExams.filter((e) => e.id !== id),
      currentOhHealthExam: state.currentOhHealthExam?.id === id ? null : state.currentOhHealthExam,
    })),

  // ============ Reset Actions ============
  resetCheckState: () => set(initialCheckState),
  resetHazardState: () => set(initialHazardState),
  resetAccidentState: () => set(initialAccidentState),
  resetTrainingState: () => set(initialTrainingState),
  resetRegulationState: () => set(initialRegulationState),
  resetRevisionState: () => set(initialRevisionState),
  resetHazardRevisionRecordState: () => set(initialHazardRevisionRecordState),
  resetHazardRevisionArchiveState: () => set(initialHazardRevisionArchiveState),
  resetAIWorkflowConfigState: () => set(initialAIWorkflowConfigState),
  resetAPICallConfigState: () => set(initialAPICallConfigState),
  resetPersonnelState: () => set(initialPersonnelState),
  resetPermitState: () => set(initialPermitState),
  resetArticleState: () => set(initialArticleState),
  resetSpecialOpReportState: () => set(initialSpecialOpReportState),
  resetDailyRiskReportState: () => set(initialDailyRiskReportState),
  resetEhsChangeState: () => set(initialEhsChangeState),
  resetOhHazardMonitorState: () => set(initialOhHazardMonitorState),
  resetOhHealthExamState: () => set(initialOhHealthExamState),

  resetAll: () =>
    set({
      ...initialCheckState,
      ...initialHazardState,
      ...initialAccidentState,
      ...initialTrainingState,
      ...initialRegulationState,
      ...initialRevisionState,
      ...initialHazardRevisionRecordState,
      ...initialHazardRevisionArchiveState,
      ...initialAIWorkflowConfigState,
      ...initialAPICallConfigState,
      ...initialPersonnelState,
      ...initialPermitState,
      ...initialArticleState,
      ...initialSpecialOpReportState,
      ...initialDailyRiskReportState,
      ...initialEhsChangeState,
      ...initialOhHazardMonitorState,
      ...initialOhHealthExamState,
    }),
}))
