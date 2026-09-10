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

export const initialHazardState = {
  hazards: [] as HazardReport[],
  currentHazard: null,
  hazardQueryParams: { page: 1, page_size: 20 } as HazardReportQueryParams,
  hazardTotal: 0,
  hazardLoading: false,
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
