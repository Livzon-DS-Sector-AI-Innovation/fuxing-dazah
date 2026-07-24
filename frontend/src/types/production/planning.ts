// ── Demand ──

export interface Demand {
  id: string
  demand_no: string
  source_type: 'manual' | 'sales_order' | 'forecast' | 'internal'
  source_ref: string | null
  product_id: string
  product_name: string
  demanded_quantity: number
  allocated_quantity: number
  fulfilled_quantity: number
  unit: string
  demand_date: string
  priority: 'urgent' | 'high' | 'medium' | 'low'
  status: 'pending' | 'confirmed' | 'partial' | 'fulfilled' | 'closed' | 'cancelled'
  customer_name: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface CreateDemandInput {
  demand_no?: string
  source_type?: string
  source_ref?: string
  product_id: string
  product_name: string
  demanded_quantity: number
  unit: string
  demand_date: string
  priority?: string
  customer_name?: string
  remark?: string
}

export interface UpdateDemandInput {
  product_name?: string
  demanded_quantity?: number
  unit?: string
  demand_date?: string
  priority?: string
  customer_name?: string
  remark?: string
}

// ── PlanOrder ──

export interface PlanOrder {
  id: string
  order_no: string
  title: string
  plan_version: number
  status: 'draft' | 'confirmed' | 'released' | 'completed' | 'closed'
  scheduled_start: string | null
  scheduled_end: string | null
  priority: 'urgent' | 'high' | 'medium' | 'low'
  remark: string | null
  created_at: string
  updated_at: string
}

export interface PlanOrderDetail extends PlanOrder {
  items: PlanItem[]
  demand_allocations: DemandAllocation[]
}

export interface CreatePlanOrderInput {
  order_no?: string
  title: string
  scheduled_start?: string
  scheduled_end?: string
  priority?: string
  remark?: string
}

export interface UpdatePlanOrderInput {
  title?: string
  scheduled_start?: string
  scheduled_end?: string
  priority?: string
  remark?: string
}

// ── PlanItem ──

export interface PlanItem {
  id: string
  plan_order_id: string
  item_no: number
  intermediate_type_id: string
  intermediate_type_name: string
  route_id: string | null
  equipment_id: string | null
  planned_quantity: number
  unit: string
  planned_start: string | null
  planned_end: string | null
  status: 'draft' | 'scheduled' | 'allocated' | 'in_progress' | 'completed' | 'cancelled'
  priority: 'urgent' | 'high' | 'medium' | 'low'
  sort_order: number
  remark: string | null
  created_at: string
  updated_at: string
  allocations: PlanAllocation[]
  demand_allocations: DemandAllocation[]
}

export interface CreatePlanItemInput {
  intermediate_type_id: string
  intermediate_type_name: string
  route_id?: string
  equipment_id?: string
  planned_quantity: number
  unit: string
  priority?: string
  remark?: string
}

export interface UpdatePlanItemInput {
  intermediate_type_name?: string
  route_id?: string
  equipment_id?: string
  planned_quantity?: number
  unit?: string
  priority?: string
  remark?: string
}

export interface SchedulePlanItemInput {
  planned_start?: string
  planned_end?: string
  equipment_id?: string
  sort_order?: number
}

// ── Allocations ──

export interface PlanAllocation {
  id: string
  plan_item_id: string
  batch_id: string
  allocated_quantity: number
  batch_no: string
  batch_status: string
}

export interface DemandAllocation {
  id: string
  demand_id: string
  plan_item_id: string
  allocated_quantity: number
  demand_no?: string
  plan_order_no?: string
  item_no?: number
  intermediate_type_name?: string
}

export interface CreateDemandAllocationInput {
  plan_item_id: string
  allocated_quantity: number
}

// ── Schedule View ──

export interface ScheduleViewItem {
  plan_order_id: string
  order_no: string
  order_title: string
  order_status: string
  order_priority: string
  order_scheduled_start: string | null
  order_scheduled_end: string | null
  item_id: string
  item_no: number
  intermediate_type_name: string
  equipment_id: string | null
  planned_quantity: number
  unit: string
  planned_start: string | null
  planned_end: string | null
  item_status: string
  item_priority: string
}

// ── Trace ──

export interface TraceNode {
  type: 'demand' | 'plan_item' | 'batch'
  id: string
  label: string
  quantity: number | null
  unit: string | null
  status: string | null
  children: TraceNode[]
}
