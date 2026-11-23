import type { Tone } from '@/components/ui-kit'
import type {
  HardwareManagedClass,
  HardwareMovementDirection,
  HardwareReceiptStatus,
  HardwareRequisitionStatus,
  HardwareRequisitionType,
  HardwareReturnStatus,
  HardwareScrapStatus,
  HardwareStocktakeStatus,
} from '@/types/warehouse-hardware'

export const MANAGED_CLASS_TONE: Record<HardwareManagedClass, Tone> = {
  stocked: 'info',
  direct: 'default',
}

export const RECEIPT_STATUS_TONE: Record<HardwareReceiptStatus, Tone> = {
  draft: 'warn',
  accepted: 'ok',
  rejected: 'danger',
}

export const REQ_TYPE_TONE: Record<HardwareRequisitionType, Tone> = {
  normal: 'default',
  urgent: 'danger',
  excess: 'warn',
}

export const REQ_STATUS_TONE: Record<HardwareRequisitionStatus, Tone> = {
  draft: 'default',
  pending: 'warn',
  approved: 'info',
  issued: 'ok',
  rejected: 'danger',
  cancelled: 'default',
}

export const MOVEMENT_DIRECTION_TONE: Record<HardwareMovementDirection, Tone> = {
  inbound: 'ok',
  outbound: 'danger',
  adjust: 'warn',
}

export const MOVEMENT_DIRECTION_LABEL: Record<HardwareMovementDirection, string> = {
  inbound: '入',
  outbound: '出',
  adjust: '调',
}

export const ERP_STATUS_TONE: Record<string, Tone> = {
  pending: 'warn',
  entered: 'ok',
}

export const RECONCILE_STATUS_TONE: Record<string, Tone> = {
  none: 'default',
  unmatched: 'danger',
  matched: 'info',
  verified: 'ok',
  discrepancy: 'warn',
}

export const STOCKTAKE_STATUS_TONE: Record<HardwareStocktakeStatus, Tone> = {
  draft: 'warn',
  counting: 'info',
  reviewed: 'warn',
  confirmed: 'ok',
  cancelled: 'default',
}

export const RETURN_STATUS_TONE: Record<HardwareReturnStatus, Tone> = {
  draft: 'warn',
  accepted: 'ok',
  rejected: 'danger',
}

export const SCRAP_STATUS_TONE: Record<HardwareScrapStatus, Tone> = {
  draft: 'default',
  pending_dept: 'warn',
  pending_final: 'warn',
  approved: 'ok',
  rejected: 'danger',
  cancelled: 'default',
}
