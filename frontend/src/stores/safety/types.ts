import type {
  HazardReport, HazardReportQueryParams,
  SafetyTraining, SafetyTrainingQueryParams, TrainingRecord,
  OperationRegulation, OperationRegulationQueryParams,
  RegulationRevision, RegulationRevisionQueryParams,
  SpecialOperationPersonnel, SpecialOperationPersonnelQueryParams,
  SpecialOperationPermit, SpecialOperationPermitQueryParams,
  SafetyKnowledgeArticle, SafetyKnowledgeArticleQueryParams,
  SpecialOperationReport, SpecialOperationReportQueryParams,
  HazardIdentification, HazardIdentificationQueryParams,
  EhsChange, EhsChangeQueryParams,
  Contractor, ContractorQueryParams, ContractorWorkRecord,
} from '@/types/safety'

// ============ Store State Types ============

export interface SafetyState {
  // Hazard state
  hazards: HazardReport[]
  currentHazard: HazardReport | null
  hazardQueryParams: HazardReportQueryParams
  hazardTotal: number
  hazardLoading: boolean

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

  // Actions - Hazard
  setHazards: (hazards: HazardReport[]) => void
  setCurrentHazard: (hazard: HazardReport | null) => void
  setHazardQueryParams: (params: Partial<HazardReportQueryParams>) => void
  setHazardTotal: (total: number) => void
  setHazardLoading: (loading: boolean) => void
  addHazard: (hazard: HazardReport) => void
  updateHazard: (id: string, hazard: Partial<HazardReport>) => void
  removeHazard: (id: string) => void

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

  // Actions - Reset
  resetHazardState: () => void
  resetTrainingState: () => void
  resetRegulationState: () => void
  resetRevisionState: () => void
  resetPersonnelState: () => void
  resetPermitState: () => void
  resetArticleState: () => void
  resetSpecialOpReportState: () => void
  resetEhsChangeState: () => void
  resetContractorState: () => void
  resetHazardIdentificationState: () => void
  resetAll: () => void
}
