import type { EmployeeFieldFilters } from '@/types/hr'
import type { EmployeeFilterParams } from '@/actions/hr/employees'

/**
 * 筛选面板状态 → 员工列表/导出 API 字段级筛选参数（日期范围拆 after/before）。
 * 列表与导出共用，保证「所见即所得」。
 */
export function fieldFiltersToParams(f: EmployeeFieldFilters): EmployeeFilterParams {
  return {
    position: f.position,
    duty: f.duty,
    job_category: f.job_category,
    level: f.level,
    report_grade: f.report_grade,
    status_category: f.status_category,
    gender: f.gender,
    ethnicity: f.ethnicity,
    native_place: f.native_place,
    marital_status: f.marital_status,
    household_type: f.household_type,
    education: f.education,
    degree_type: f.degree_type,
    classification: f.classification,
    school: f.school,
    major: f.major,
    hr_analysis: f.hr_analysis,
    domain_account: f.domain_account,
    departure_reason: f.departure_reason,
    age_min: f.age_min,
    age_max: f.age_max,
    birth_year_min: f.birth_year?.[0],
    birth_year_max: f.birth_year?.[1],
    hire_date_after: f.hire_date?.[0],
    hire_date_before: f.hire_date?.[1],
    work_start_date_after: f.work_start_date?.[0],
    work_start_date_before: f.work_start_date?.[1],
    graduation_date_after: f.graduation_date?.[0],
    graduation_date_before: f.graduation_date?.[1],
    departure_date_after: f.departure_date?.[0],
    departure_date_before: f.departure_date?.[1],
    contract_start_date_after: f.contract_start_date?.[0],
    contract_start_date_before: f.contract_start_date?.[1],
    contract_end_date_after: f.contract_end_date?.[0],
    contract_end_date_before: f.contract_end_date?.[1],
  }
}
